#!/usr/bin/env python3
"""eqal55i_patch - unofficial firmware fixes for the Sky-Watcher EQ-AL55i Pro.

Part of eq-al55i-firmware-fixes. Works on the official MC016 v3.48 motor-controller
firmware file.

Builds a patched copy of the official MC016_Ver0348.mcf (EQ-AL55i Pro). The input is
never modified. Only the official v3.48 file is accepted, every patch site is checked
for the stock bytes before it is changed, and the bootloader (update/recovery code) and
the end-of-image "application valid" word are never touched.

Not affiliated with Sky-Watcher. Use entirely at your own risk. See README.md.

Examples:
  python eqal55i_patch.py MC016_Ver0348.mcf --recommended
  python eqal55i_patch.py MC016_Ver0348.mcf --fix-usb --fix-d-cr --fix-x06 --dec-ff 240 --dec-ki 16
  python eqal55i_patch.py MC016_Ver0348.mcf --recommended --round --in-position 5
  python eqal55i_patch.py --check MC016_Ver0348_p1p2p6_ff240_dki16.mcf
"""
import argparse
import hashlib
import os
import struct
import sys

__version__ = "1.1.0"

if sys.version_info < (3, 8):
    sys.exit("eqal55i_patch needs Python 3.8 or newer")

# ---------------------------------------------------------------------------
# The official image
# ---------------------------------------------------------------------------
STOCK_NAME = "MC016_Ver0348.mcf"
STOCK_SHA256 = "fe121f81dd673bb147af678b06400b71cf1963604fadfbca07796c72e77b7a26"
IMAGE_SIZE = 0x20000            # 128 KB, loaded at 0x08000000
FLASH_BASE = 0x08000000
APP_START = 0x7000              # below this is the bootloader: never written
VALID_WORD = 0x1FFFC            # "application valid" word: never written
RECOMMENDED_SHA256 = "71e6ab332625c440e50405351eb624228a6676b4487b3c782fea9a18f89f680e"
# --recommended of version 1.0.0 (no Dec Ki change), still recognised by --check.
RECOMMENDED_V1_SHA256 = "d5b06ac4d2e11c899fd963ebb13887dbcbd692b51ae25831508fd2bc58601273"

# ---------------------------------------------------------------------------
# Patch data (file offsets; flash address = 0x08000000 + offset)
# ---------------------------------------------------------------------------
# P1: the :D handler jumps past the store of its carriage return.
D_CR = (0xDDF0, bytes.fromhex("37e0"), bytes.fromhex("35e0"))

# P2: :X 06 converts the command-buffer pointer instead of the parsed RA rate.
X06 = (0xC8E2, bytes.fromhex("2046"), bytes.fromhex("c046"))

# P6: USB replies are handed to the bootloader's transmit routine without waiting,
# so the next reply can overwrite the buffer mid-transfer. The hook calls a stub that
# makes the same call and then waits (bounded) for the transmit-busy flag to clear.
USB_HOOK = (0x10524, bytes.fromhex("00989047"), bytes.fromhex("01f06cf8"))  # bl 0x08011600
USB_STUB_AT = 0x11600
USB_STUB = bytes.fromhex(
    "0098"      # ldr  r0,[sp]        reply buffer
    "10b5"      # push {r4,lr}
    "9047"      # blx  r2             bootloader CDC transmit
    "074b"      # ldr  r3,=0x20000340 USB class-data pointer
    "8522"      # movs r2,#0x85
    "9200"      # lsls r2,r2,#2       r2 = 0x214 (transmit-busy offset)
    "0124"      # movs r4,#1
    "2404"      # lsls r4,r4,#16      timeout: 65536 passes (tens of ms)
    "1868"      # loop: ldr r0,[r3]
    "0028"      # cmp  r0,#0
    "04d0"      # beq  done           USB de-initialised
    "8158"      # ldr  r1,[r0,r2]     transmit-busy flag
    "0029"      # cmp  r1,#0
    "01d0"      # beq  done           previous transfer finished
    "013c"      # subs r4,#1
    "f7d1"      # bne  loop
    "10bd"      # done: pop {r4,pc}
    "c046"      # nop
    "40030020"  # .word 0x20000340
)

# P5: Dec feed-forward. Right after the servo sums its PID terms (before the
# standstill cap), add +/-N in the direction of the Dec target's velocity while the
# target moves (velocity is a non-zero float). Nothing at rest, nothing on RA.
FF_HOOK = (0x98E4, bytes.fromhex("25468035"), bytes.fromhex("07f0acfe"))    # bl 0x08011640
FF_STUB_AT = 0x11640
FF_STUB = bytes.fromhex(
    "2546"      # mov  r5,r4          (displaced instruction)
    "8035"      # adds r5,#0x80       (displaced instruction)
    "012f"      # cmp  r7,#1          Dec axis?
    "08d1"      # bne  done
    "626f"      # ldr  r2,[r4,#0x74]  target velocity (float)
    "5300"      # lsls r3,r2,#1
    "1b0e"      # lsrs r3,r3,#24      exponent
    "04d0"      # beq  done           target not moving
    "024b"      # ldr  r3,=N
    "002a"      # cmp  r2,#0
    "00da"      # bge  add
    "5b42"      # rsbs r3,r3,#0       moving to lower counts
    "c018"      # add: adds r0,r0,r3
    "7047"      # done: bx lr
)               # followed by .word N

# P9: round instead of truncate. At every speed change the firmware restarts its
# target trajectory from the current target position, converted to whole counts by
# truncating toward 0 (0x08010B38). A guide pulse has about four speed changes, so
# moves toward the home position gain up to ~3 counts and moves away lose up to ~3.
# The hook calls a stub that rounds to the nearest count instead: trunc(x + 0.5*sign(x)).
ROUND_HOOK = (0x10B38, bytes.fromhex("f7f72eff"), bytes.fromhex("00f0c2fd"))  # bl 0x080116C0
ROUND_STUB_AT = 0x116C0
ROUND_STUB = bytes.fromhex(
    "10b5"      # push {r4,lr}
    "c10f"      # lsrs r1,r0,#31      sign of x
    "c907"      # lsls r1,r1,#31
    "034a"      # ldr  r2,=0.5f
    "1143"      # orrs r1,r2          +/-0.5
    "fff74bfc"  # bl   0x08010F64     float add (firmware's own)
    "f7f763f9"  # bl   0x08008998     float -> int, truncating (the call that was replaced)
    "10bd"      # pop  {r4,pc}
    "0000003f"  # .word 0.5f          (word-aligned at +0x14)
)

# P7: "in position" status. Stock :f reports "stopped" the moment the commanded move
# ends, while the axis may still be sliding the last 10-37 counts in. The hook (where
# the :f reply reads the running flag) calls a stub that keeps reporting "running"
# until |servo error| <= N counts AND the measured speed (the firmware's own 100 ms
# sample) is under 50 counts/s, or 1 s has passed since the stop. It then latches
# "stopped" in axis flag bit 7, which the firmware clears whenever a move starts and
# never uses otherwise, so the reply can't flip back. Only the :f reply changes.
INPOS_HOOK = (0xDA34, bytes.fromhex("027ad206"), bytes.fromhex("03f0b4fe"))   # bl 0x080117A0
INPOS_STUB_AT = 0x117A0
INPOS_STUB = bytes.fromhex(
    "0bb5"      # push {r0,r1,r3,lr}  r0 = axis data
    "8268"      # ldr  r2,[r0,#8]     flags
    "d306"      # lsls r3,r2,#27      running (bit 4)?
    "1dd4"      # bmi  running
    "1306"      # lsls r3,r2,#24      already latched stopped (bit 7)?
    "19d4"      # bmi  stopped
    "8269"      # ldr  r2,[r0,#0x18]  servo error (target - encoder)
    "d317"      # asrs r3,r2,#31
    "5a40"      # eors r2,r3
    "d21a"      # subs r2,r2,r3       |error|
    "0d4b"      # ldr  r3,=N
    "9a42"      # cmp  r2,r3
    "05dc"      # bgt  timeout        outside the window
    "026f"      # ldr  r2,[r0,#0x70]  measured speed (float)
    "5200"      # lsls r2,r2,#1
    "5208"      # lsrs r2,r2,#1       |speed|
    "0b4b"      # ldr  r3,=50.0f
    "9a42"      # cmp  r2,r3
    "07d3"      # blo  latch          in window and slow: stopped
    "fcf703fc"  # timeout: bl 0x0800DFD0  microsecond clock (low word)
    "009a"      # ldr  r2,[sp]
    "126c"      # ldr  r2,[r2,#0x40]  time of the stop
    "801a"      # subs r0,r0,r2
    "084b"      # ldr  r3,=1000000
    "9842"      # cmp  r0,r3
    "06d3"      # blo  running        under 1 s: still settling
    "0098"      # latch: ldr r0,[sp]
    "8268"      # ldr  r2,[r0,#8]
    "8023"      # movs r3,#0x80
    "1a43"      # orrs r2,r3
    "8260"      # str  r2,[r0,#8]     set bit 7
    "0022"      # stopped: movs r2,#0 (N = 0)
    "0bbd"      # pop  {r0,r1,r3,pc}
    "0122"      # running: movs r2,#1
    "d207"      # lsls r2,r2,#31      (N = 1)
    "0bbd"      # pop  {r0,r1,r3,pc}
    "c046"      # nop                 (literal alignment)
)               # followed by .word N, 50.0f, 1000000
INPOS_VMAX = 50.0
INPOS_TIMEOUT_US = 1000000
INPOS_DEFAULT = 5               # the value bench-tested
INPOS_MIN, INPOS_MAX = 1, 10

# P3: standstill/braking drive cap, a double used once at boot (stock 0.1).
CAP_AT = 0x9628
CAP_STOCK = 0.10

# P4: servo gains, written at boot as "movs rN,#imm" (byte 0 = imm, byte 1 = 0x20|reg).
# Limits are the same on both axes: twice the higher stock value (Kp 25/20, Ki 8/16).
KP_MAX, KI_MAX = 50, 32
GAINS = {   # option: (offset, register, stock, max, label, name-tag)
    "dec_kp": (0x9A6A, 1, 25, KP_MAX, "Dec Kp", "dkp"),
    "dec_ki": (0x9A6E, 1, 8, KI_MAX, "Dec Ki", "dki"),
    "ra_kp": (0x9A8C, 0, 20, KP_MAX, "RA Kp", "rkp"),
    "ra_ki": (0x9A90, 0, 16, KI_MAX, "RA Ki", "rki"),
}
ADVANCED_GAINS = ("dec_kp", "ra_kp", "ra_ki")   # need --experimental; dec_ki does not
DKI_DEFAULT = 16                                # --recommended; the value bench-tested

FF_DEFAULT = 240
FF_MAX = 300
CAP_MIN, CAP_MAX = 0.05, 0.20

# Every byte range any patch may change, by option. Everything else must stay
# exactly as in the official file.
APP_END = 0x1154C               # end of the official program; free flash after it
RANGES = {
    "d_cr": [(D_CR[0], 2)],
    "x06": [(X06[0], 2)],
    "usb": [(USB_HOOK[0], 4), (USB_STUB_AT, len(USB_STUB))],
    "ff": [(FF_HOOK[0], 4), (FF_STUB_AT, len(FF_STUB) + 4)],
    "cap": [(CAP_AT, 8)],
    "round": [(ROUND_HOOK[0], 4), (ROUND_STUB_AT, len(ROUND_STUB))],
    "inpos": [(INPOS_HOOK[0], 4), (INPOS_STUB_AT, len(INPOS_STUB) + 12)],
}
for _k, (_off, _r, _s, _m, _l, _t) in GAINS.items():
    RANGES[_k] = [(_off, 2)]
# SHA-256 of the official file with all of the above ranges zeroed. An image whose
# masked hash matches this is identical to the official file outside the patch sites.
MASKED_STOCK_SHA256 = "9bf254145b249fbc3599c15aa28195674d7a9220df9a39dfc4b63e96dcbb45a2"


def thumb_bl(src, dst):
    """Encode a Thumb BL from file offset src to file offset dst."""
    off = dst - (src + 4)
    s = (off >> 24) & 1
    i1, i2 = (off >> 23) & 1, (off >> 22) & 1
    j1, j2 = (1 - i1) ^ s, (1 - i2) ^ s
    return struct.pack("<HH", 0xF000 | (s << 10) | ((off >> 12) & 0x3FF),
                       0xD000 | (j1 << 13) | (j2 << 11) | ((off >> 1) & 0x7FF))


def _self_check():
    """Catch any inconsistency in the patch data before touching a file."""
    assert thumb_bl(USB_HOOK[0], USB_STUB_AT) == USB_HOOK[2]
    assert thumb_bl(FF_HOOK[0], FF_STUB_AT) == FF_HOOK[2]
    spans = sorted(r for rs in RANGES.values() for r in rs)
    for (a, n), (b, _) in zip(spans, spans[1:]):
        assert a + n <= b, "patch ranges overlap"
    for a, n in spans:
        assert APP_START <= a and a + n <= VALID_WORD, "patch outside the application"
    assert thumb_bl(ROUND_HOOK[0], ROUND_STUB_AT) == ROUND_HOOK[2]
    assert thumb_bl(INPOS_HOOK[0], INPOS_STUB_AT) == INPOS_HOOK[2]
    assert ROUND_STUB[0x0A:0x0E] == thumb_bl(ROUND_STUB_AT + 0x0A, 0x10F64)
    assert ROUND_STUB[0x0E:0x12] == thumb_bl(ROUND_STUB_AT + 0x0E, 0x8998)
    assert ROUND_STUB[0x12:0x14] == bytes.fromhex("10bd") and ROUND_STUB_AT % 4 == 0
    # ldr r2,[pc,#imm8*4] at +0x06 reads Align(pc+4,4) + imm: must land on the 0.5f literal.
    lit = ((ROUND_STUB_AT + 0x06 + 4) & ~3) + ROUND_STUB[0x06] * 4 - ROUND_STUB_AT
    assert ROUND_STUB[0x07] == 0x4A and struct.unpack_from("<f", ROUND_STUB, lit)[0] == 0.5
    # The three ldr r3,=literal in the in-position stub must hit N, 50.0f and the timeout.
    for at, want in ((0x14, 0), (0x20, 1), (0x30, 2)):
        assert INPOS_STUB[at + 1] == 0x4B
        assert ((INPOS_STUB_AT + at + 4) & ~3) + INPOS_STUB[at] * 4 == INPOS_STUB_AT + 0x4C + 4 * want
    assert INPOS_STUB[0x26:0x2A] == thumb_bl(INPOS_STUB_AT + 0x26, 0xDFD0)
    assert len(INPOS_STUB) == 0x4C and (INPOS_STUB_AT + 0x4C) % 4 == 0
    for a, n in ((USB_STUB_AT, len(USB_STUB)), (FF_STUB_AT, len(FF_STUB) + 4),
                 (ROUND_STUB_AT, len(ROUND_STUB)), (INPOS_STUB_AT, len(INPOS_STUB) + 12)):
        assert a >= APP_END and a % 4 == 0, "new code must be word-aligned free flash"
    kp = [g[2] for k, g in GAINS.items() if k.endswith("kp")]
    ki = [g[2] for k, g in GAINS.items() if k.endswith("ki")]
    assert KP_MAX == 2 * max(kp) and KI_MAX == 2 * max(ki), "limits: 2x the higher stock value"
    for _off, _reg, stock_val, top, _l, _t in GAINS.values():
        assert stock_val < top <= 255
    assert 1 <= DKI_DEFAULT <= GAINS["dec_ki"][3] and set(ADVANCED_GAINS) < set(GAINS)


_self_check()


# ---------------------------------------------------------------------------
def fail(msg):
    sys.exit("error: " + msg)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def read_image(path):
    """Read a file, refusing anything that isn't the size of an MC016 image."""
    try:
        size = os.path.getsize(path)
        if size != IMAGE_SIZE:
            return None
        with open(path, "rb") as f:
            data = f.read(IMAGE_SIZE + 1)
    except OSError as e:
        fail("cannot read {}: {}".format(path, e.strerror or e))
    return data if len(data) == IMAGE_SIZE else None


def masked_sha256(data):
    m = bytearray(data)
    for rs in RANGES.values():
        for off, n in rs:
            m[off:off + n] = bytes(n)
    return sha256(m)


def load_stock(path):
    data = read_image(path)
    if data is None or sha256(data) != STOCK_SHA256:
        if data is not None and masked_sha256(data) == MASKED_STOCK_SHA256:
            fail("{} has been modified (already patched, or damaged). Build from the "
                 "unmodified official {} instead."
                 .format(path, STOCK_NAME))
        fail("{} is not the official {} (v3.48). Only that file is supported."
             .format(path, STOCK_NAME))
    return data


def put(img, off, old, new, what):
    if off < APP_START or off + len(new) > VALID_WORD:
        fail("internal: refusing to write outside the application ({})".format(what))
    if bytes(img[off:off + len(old)]) != old:
        fail("internal: unexpected bytes at 0x{:08X} ({})".format(FLASH_BASE + off, what))
    img[off:off + len(new)] = new
    print("  0x{:08X}  {}".format(FLASH_BASE + off, what))


def movs(reg, imm):
    return bytes([imm, 0x20 | reg])


# ---------------------------------------------------------------------------
def build(stock, opt):
    img = bytearray(stock)
    tags = []
    if opt["d_cr"]:
        put(img, D_CR[0], D_CR[1], D_CR[2], ":D reply carriage return (P1)")
        tags.append("p1")
    if opt["x06"]:
        put(img, X06[0], X06[1], X06[2], ":X 06 RA rate (P2)")
        tags.append("p2")
    if opt["usb"]:
        put(img, USB_STUB_AT, b"\xff" * len(USB_STUB), USB_STUB, "USB reply wait, new code (P6)")
        put(img, USB_HOOK[0], USB_HOOK[1], USB_HOOK[2], "USB reply wait, hook (P6)")
        tags.append("p6")
    if opt["ff"] is not None:
        code = FF_STUB + struct.pack("<I", opt["ff"])
        put(img, FF_STUB_AT, b"\xff" * len(code), code,
            "Dec feed-forward {}, new code (P5)".format(opt["ff"]))
        put(img, FF_HOOK[0], FF_HOOK[1], FF_HOOK[2], "Dec feed-forward, hook (P5)")
        tags.append("ff{}".format(opt["ff"]))
    if opt["cap"] is not None:
        put(img, CAP_AT, struct.pack("<d", CAP_STOCK), struct.pack("<d", opt["cap"]),
            "drive cap {} -> {} (P3)".format(CAP_STOCK, opt["cap"]))
        tags.append("cap" + "{:g}".format(opt["cap"]).replace(".", ""))
    for key, (off, reg, stock_val, _top, label, tag) in GAINS.items():
        val = opt[key]
        if val is not None:
            put(img, off, movs(reg, stock_val), movs(reg, val),
                "{} {} -> {} (P4)".format(label, stock_val, val))
            tags.append("{}{}".format(tag, val))
    if opt["round"]:
        put(img, ROUND_STUB_AT, b"\xff" * len(ROUND_STUB), ROUND_STUB, "round to nearest count, new code (P9)")
        put(img, ROUND_HOOK[0], ROUND_HOOK[1], ROUND_HOOK[2], "round to nearest count, hook (P9)")
        tags.append("rnd")
    if opt["inpos"] is not None:
        code = INPOS_STUB + struct.pack("<IfI", opt["inpos"], INPOS_VMAX, INPOS_TIMEOUT_US)
        put(img, INPOS_STUB_AT, b"\xff" * len(code), code,
            "in-position status, {} counts, new code (P7)".format(opt["inpos"]))
        put(img, INPOS_HOOK[0], INPOS_HOOK[1], INPOS_HOOK[2], "in-position status, hook (P7)")
        tags.append("ip{}".format(opt["inpos"]))
    verify(stock, bytes(img), opt)
    return bytes(img), tags


def verify(stock, img, opt):
    """Prove that only the selected patch ranges differ from the official file."""
    allowed = set()
    for key, rs in RANGES.items():
        if opt.get(key) not in (None, False):
            for off, n in rs:
                allowed.update(range(off, off + n))
    changed = [i for i in range(IMAGE_SIZE) if img[i] != stock[i]]
    stray = [i for i in changed if i not in allowed]
    if (len(img) != IMAGE_SIZE or stray or img[:APP_START] != stock[:APP_START]
            or img[VALID_WORD:] != stock[VALID_WORD:]
            or masked_sha256(img) != MASKED_STOCK_SHA256):
        fail("internal: verification failed, nothing written")


def describe(data):
    """Return (lines, patched?) describing which patches an image contains."""
    lines, patched = [], False

    def site(name, off, stock_b, patched_b):
        nonlocal patched
        have = data[off:off + len(stock_b)]
        if have == stock_b:
            lines.append("  {:<26} stock".format(name))
        elif have == patched_b:
            lines.append("  {:<26} PATCHED".format(name))
            patched = True
        else:
            lines.append("  {:<26} unknown bytes".format(name))
            patched = True

    site(":D carriage return (P1)", *D_CR)
    site(":X 06 RA rate (P2)", *X06)
    usb_hook = data[USB_HOOK[0]:USB_HOOK[0] + 4]
    usb_code = data[USB_STUB_AT:USB_STUB_AT + len(USB_STUB)]
    if usb_hook == USB_HOOK[1] and usb_code == b"\xff" * len(USB_STUB):
        lines.append("  {:<26} stock".format("USB reply wait (P6)"))
    elif usb_hook == USB_HOOK[2] and usb_code == USB_STUB:
        lines.append("  {:<26} PATCHED".format("USB reply wait (P6)"))
        patched = True
    else:
        lines.append("  {:<26} unknown bytes".format("USB reply wait (P6)"))
        patched = True
    ff_hook = data[FF_HOOK[0]:FF_HOOK[0] + 4]
    ff_code = data[FF_STUB_AT:FF_STUB_AT + len(FF_STUB)]
    if ff_hook == FF_HOOK[1] and ff_code == b"\xff" * len(FF_STUB):
        lines.append("  {:<26} stock (off)".format("Dec feed-forward (P5)"))
    elif ff_hook == FF_HOOK[2] and ff_code == FF_STUB:
        n = struct.unpack_from("<I", data, FF_STUB_AT + len(FF_STUB))[0]
        lines.append("  {:<26} PATCHED, {}".format("Dec feed-forward (P5)", n))
        patched = True
    else:
        lines.append("  {:<26} unknown bytes".format("Dec feed-forward (P5)"))
        patched = True
    cap = struct.unpack_from("<d", data, CAP_AT)[0]
    if cap == CAP_STOCK:
        lines.append("  {:<26} stock (0.10)".format("Drive cap (P3)"))
    else:
        lines.append("  {:<26} CHANGED, {:g}".format("Drive cap (P3)", cap))
        patched = True
    for off, reg, stock_val, _top, label, _ in GAINS.values():
        b = data[off:off + 2]
        name = "{} (P4)".format(label)
        if b[1] != 0x20 | reg:
            lines.append("  {:<26} unknown bytes".format(name))
            patched = True
        elif b[0] == stock_val:
            lines.append("  {:<26} stock ({})".format(name, stock_val))
        else:
            lines.append("  {:<26} CHANGED, {}".format(name, b[0]))
            patched = True
    site("Round to nearest (P9)", ROUND_HOOK[0], ROUND_HOOK[1], ROUND_HOOK[2])
    rcode = data[ROUND_STUB_AT:ROUND_STUB_AT + len(ROUND_STUB)]
    if data[ROUND_HOOK[0]:ROUND_HOOK[0] + 4] == ROUND_HOOK[2] and rcode != ROUND_STUB:
        lines[-1] = "  {:<26} unknown bytes".format("Round to nearest (P9)")
    name = "In-position status (P7)"
    ihook = data[INPOS_HOOK[0]:INPOS_HOOK[0] + 4]
    icode = data[INPOS_STUB_AT:INPOS_STUB_AT + len(INPOS_STUB)]
    if ihook == INPOS_HOOK[1] and icode == b"\xff" * len(INPOS_STUB):
        lines.append("  {:<26} stock (off)".format(name))
    else:
        n, vmax, tmo = struct.unpack_from("<IfI", data, INPOS_STUB_AT + len(INPOS_STUB))
        if (ihook == INPOS_HOOK[2] and icode == INPOS_STUB and INPOS_MIN <= n <= INPOS_MAX
                and vmax == INPOS_VMAX and tmo == INPOS_TIMEOUT_US):
            lines.append("  {:<26} PATCHED, {} counts".format(name, n))
        else:
            lines.append("  {:<26} unknown bytes".format(name))
        patched = True
    return lines, patched


def check(path):
    data = read_image(path)
    print(path)
    if data is None:
        print("  NOT an MC016 v3.48 image (wrong size). Do not flash.")
        return 1
    print("  sha256 {}".format(sha256(data)))
    if sha256(data) == STOCK_SHA256:
        print("  official MC016 v3.48, unmodified")
        return 0
    if masked_sha256(data) != MASKED_STOCK_SHA256:
        print("  NOT built from the official v3.48: bytes outside the known patch sites")
        print("  differ (possibly the bootloader). Do not flash.")
        return 1
    print("  everything outside the patch sites matches the official v3.48")
    if sha256(data) == RECOMMENDED_SHA256:
        print("  matches the tested --recommended build")
    elif sha256(data) == RECOMMENDED_V1_SHA256:
        print("  matches the --recommended build of version 1.0.0 (without Dec Ki 16)")
    lines, _ = describe(data)
    print("\n".join(lines))
    if any("unknown" in line for line in lines):
        print("  Some patch sites hold unknown bytes. Do not flash.")
        return 1
    return 0


def default_name(tags):
    """e.g. ['p1', 'p2', 'p6', 'ff240'] -> MC016_Ver0348_p1p2p6_ff240.mcf"""
    fixes = "".join(t for t in tags if t in ("p1", "p2", "p6"))
    parts = ([fixes] if fixes else []) + [t for t in tags if t not in ("p1", "p2", "p6")]
    return "MC016_Ver0348_{}.mcf".format("_".join(parts))


def write_output(out, inp, img):
    """Write atomically, never over the input or any file this tool didn't make."""
    if not out.lower().endswith(".mcf"):
        fail("the output file name must end in .mcf")
    if os.path.exists(out):
        try:
            same = os.path.samefile(out, inp)
        except OSError:
            same = True
        if same:
            fail("output would overwrite the input file")
        old = read_image(out)
        if old is None or masked_sha256(old) != MASKED_STOCK_SHA256 or sha256(old) == STOCK_SHA256:
            fail("{} already exists and isn't a patched image from this tool; "
                 "refusing to overwrite it".format(out))
    folder = os.path.dirname(os.path.abspath(out))
    tmp = os.path.join(folder, "." + os.path.basename(out) + ".tmp")
    try:
        with open(tmp, "wb") as f:
            f.write(img)
            f.flush()
            os.fsync(f.fileno())
        with open(tmp, "rb") as f:
            if f.read() != img:
                raise OSError("read-back mismatch")
        os.replace(tmp, out)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        fail("could not write {}: {}".format(out, e.strerror or e))
    if read_image(out) != img:
        fail("{} did not verify after writing. Do not flash it.".format(out))


# ---------------------------------------------------------------------------
def parse_args(argv):
    ap = argparse.ArgumentParser(
        prog="eqal55i_patch.py",
        description="Unofficial firmware fixes for the Sky-Watcher EQ-AL55i Pro "
                    "(MC016 v3.48 motor controller). Choose all options in one command; "
                    "every build starts from the official " + STOCK_NAME + ".",
        epilog="Not affiliated with Sky-Watcher. Use entirely at your own risk.")
    ap.add_argument("input", nargs="?", metavar="IN.mcf",
                    help="the official " + STOCK_NAME)
    ap.add_argument("output", nargs="?", metavar="OUT.mcf",
                    help="output file (default: named after the options)")
    ap.add_argument("--version", action="version", version="%(prog)s " + __version__)

    g = ap.add_argument_group("presets")
    g.add_argument("--recommended", action="store_true",
                   help="all fixes, Dec feed-forward {} and Dec Ki {} (the tested combination)"
                        .format(FF_DEFAULT, DKI_DEFAULT))

    g = ap.add_argument_group("fixes")
    g.add_argument("--fix-usb", action="store_true",
                   help="USB replies wait for the previous one to finish (no garbled replies)")
    g.add_argument("--fix-d-cr", action="store_true",
                   help=":D reply gets its missing carriage return")
    g.add_argument("--fix-x06", action="store_true",
                   help=":X 06 uses the RA rate it was sent")
    g.add_argument("--fix-all", action="store_true",
                   help="all three fixes, without changing Dec motion")

    g = ap.add_argument_group("Dec motion")
    g.add_argument("--dec-ff", type=int, metavar="N",
                   help="Dec feed-forward strength, 1-{} of 2401 (--recommended uses {})"
                        .format(FF_MAX, FF_DEFAULT))
    g.add_argument("--dec-ki", type=int, metavar="N",
                   help="Dec integral gain, 1-{} (stock {}; --recommended uses {}, the only "
                        "value tested above stock)".format(KI_MAX, GAINS["dec_ki"][2], DKI_DEFAULT))

    g = ap.add_argument_group("both axes")
    g.add_argument("--round", action="store_true",
                   help="round the firmware's target to the nearest count instead of truncating "
                        "(removes the ~3-count direction bias on guide pulses)")
    g.add_argument("--in-position", type=int, metavar="N",
                   help="after a move, :f reports 'stopped' only once the axis is within N counts "
                        "({}-{}) and nearly still, or after 1 s ({} was tested)"
                        .format(INPOS_MIN, INPOS_MAX, INPOS_DEFAULT))

    g = ap.add_argument_group("advanced (leave at stock; need --experimental)")
    g.add_argument("--experimental", action="store_true",
                   help="required for any option in this group")
    g.add_argument("--cap", type=float, metavar="F",
                   help="hold/brake drive share, {}-{} (stock {})".format(CAP_MIN, CAP_MAX, CAP_STOCK))
    for key in ADVANCED_GAINS:
        _, _, stock_val, top, label, _ = GAINS[key]
        g.add_argument("--" + key.replace("_", "-"), type=int, metavar="N",
                       help="{}, 1-{} (stock {})".format(label, top, stock_val))

    g = ap.add_argument_group("other")
    g.add_argument("--check", metavar="FILE", help="show which fixes a .mcf file contains")
    return ap.parse_args(argv)


def main(argv=None):
    a = parse_args(argv)
    if a.check:
        if a.input or any(getattr(a, k) not in (None, False) for k in
                          ("recommended", "fix_usb", "fix_d_cr", "fix_x06", "fix_all",
                           "dec_ff", "cap", "experimental", "round", "in_position")
                          + tuple(GAINS)):
            fail("use --check FILE on its own")
        return check(a.check)
    if not a.input:
        fail("give the official {} as input (see --help)".format(STOCK_NAME))

    opt = {
        "usb": a.fix_usb or a.fix_all or a.recommended,
        "d_cr": a.fix_d_cr or a.fix_all or a.recommended,
        "x06": a.fix_x06 or a.fix_all or a.recommended,
        "ff": a.dec_ff if a.dec_ff is not None else (FF_DEFAULT if a.recommended else None),
        "cap": a.cap,
        "round": a.round,
        "inpos": a.in_position,
    }
    for key in GAINS:
        opt[key] = getattr(a, key)
    if opt["dec_ki"] is None and a.recommended:
        opt["dec_ki"] = DKI_DEFAULT

    if opt["inpos"] is not None and not INPOS_MIN <= opt["inpos"] <= INPOS_MAX:
        fail("--in-position must be {}..{}".format(INPOS_MIN, INPOS_MAX))
    if opt["ff"] is not None and not 1 <= opt["ff"] <= FF_MAX:
        fail("--dec-ff must be 1..{}".format(FF_MAX))
    advanced = [k for k in ("cap",) + ADVANCED_GAINS if opt[k] is not None]
    if advanced and not a.experimental:
        fail("--{} is an advanced option: leave it at stock unless you can measure the "
             "result. To use it anyway, add --experimental."
             .format(advanced[0].replace("_", "-")))
    if opt["cap"] is not None and not CAP_MIN <= opt["cap"] <= CAP_MAX:
        fail("--cap must be {}..{}".format(CAP_MIN, CAP_MAX))
    if opt["cap"] is not None and opt["cap"] == CAP_STOCK:
        fail("--cap {} is the stock value; leave the option out".format(opt["cap"]))
    for key, (_, _, stock_val, top, _, _) in GAINS.items():
        if opt[key] is not None and not 1 <= opt[key] <= top:
            fail("--{} must be 1..{}".format(key.replace("_", "-"), top))
        if opt[key] == stock_val:
            fail("--{} {} is the stock value; leave the option out"
                 .format(key.replace("_", "-"), stock_val))
    if not any(v not in (None, False) for v in opt.values()):
        fail("no fixes selected. Try --recommended (see --help).")

    stock = load_stock(a.input)
    print("Building from {}:".format(a.input))
    img, tags = build(stock, opt)

    out = a.output or os.path.join(os.path.dirname(a.input), default_name(tags))
    write_output(out, a.input, img)
    print("Wrote {}".format(out))
    print("  sha256 {}".format(sha256(img)))
    if sha256(img) == RECOMMENDED_SHA256:
        print("  (matches the tested --recommended build)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
