# EQ-AL55i Pro firmware fixes

Unofficial fixes for the Sky-Watcher EQ-AL55i Pro mount's motor-controller firmware
(file `MC016_Ver0348.mcf`, v3.48).

> [!WARNING]
> **Unofficial and unsupported. Use entirely at your own risk.**
>
> This tool modifies your mount's firmware. It is not made, tested or endorsed by Sky-Watcher.
> Flashing modified firmware may void your warranty. A failed or interrupted flash, or a bad
> setting, can leave the mount unresponsive or moving unexpectedly until it's recovered, and in
> the worst case it may need a repair. The authors accept no
> responsibility for damage to your mount, telescope or other equipment.
>
> Only continue if you are comfortable recovering the mount yourself (see
> [Going back](#going-back)). Keep the stock firmware file, and never leave the mount
> unattended while flashing or testing.

## Why

Firmware v3.48 has a few bugs, two of which affect everyday use:

- **Garbled replies over USB.** Drivers see corrupted or mismatched replies and need several
  retries, so users find an EQMOD cable on the hand-controller port works better than USB.
- **Late Dec guide corrections.** At the start of a Dec guide pulse, the motor doesn't move
  for about 0.3–0.45 s. Short corrections arrive late or come up short.

These bugs are easy to mistake for backlash. See [GUIDING.md](GUIDING.md) for how guiding
behaves before and after `--recommended`.

## What the fixes do

The script takes the **official** `MC016_Ver0348.mcf` from Sky-Watcher and builds a patched
copy on your computer. You flash it with Sky-Watcher's firmware loader, like any update.

**USB fix.** The mount sends each reply over USB without waiting for the previous one to
finish. If the next command arrives quickly, its reply overwrites the buffer while the last
one is still being sent, or gets dropped. The fix makes each reply wait until the previous
transfer has finished (with a short timeout, so it can never hang).

**Dec feed-forward.** The servo only pushes the motor in proportion to how far it has fallen
behind its target. At guide speed, that error builds slowly, so Dec sits still until the push
is strong enough to overcome gear friction. Feed-forward adds a fixed push in the direction of
travel as soon as a Dec move starts. It's removed when the move stops, so it adds nothing at
rest, and RA is not changed.

**Dec settling.** After a goto, Dec stops a few counts short of or past its target. The
servo's integral term then has to build up enough drive to move it the rest of the way against
friction. With the stock gain that's slow, so the last few counts take 1–2 s. Doubling the Dec
integral gain (8 → 16) makes it build twice as fast. RA is not changed.

**Rounding (`--round`).** At every change of speed the firmware restarts its internal target
from the current target position, cutting it to a whole encoder count by rounding toward the
mount's home position. A guide pulse has about four speed changes, so pulses toward home gain
up to 3 counts and pulses away from home lose up to 3. Away from home this shows up as one
direction of guide pulse consistently coming in longer than the other, on both axes. The fix
rounds to the nearest count instead.

**In-position status (`--in-position N`).** The mount tells apps a move has finished (the
`:f` status) the moment its planned motion ends, while the axis can still be sliding the last
10–37 counts (up to about 13″) onto the target. With this option the mount reports "stopped"
only once the axis is within N counts of the target and nearly still, or after 1 s at most.
It changes only what the mount reports, not how it moves. With N = 5 an app that starts an
exposure or plate solve on "stopped" sees the axis within about 2″.

**`:D` reply fix.** The `:D` command returns its value without the carriage return that
ends every other reply. Some drivers then wait for, or mis-read, the next reply.

**`:X 06` fix.** This extended command sets a position and rate on both axes. A firmware bug
uses a memory address instead of the RA rate it was sent, so RA runs thousands of counts
past its target. The fix uses the rate that was actually sent.

The firmware still reports itself as v3.48, so drivers and apps treat it as normal. The
update and recovery code is never touched, so you can always flash the stock file again.

## Usage

Needs Python 3.8 or newer. Nothing else to install.

```
python eqal55i_patch.py MC016_Ver0348.mcf --recommended
```

This writes `MC016_Ver0348_p1p2p6_ff240_dki16_rnd_ip5.mcf` and prints every change it made.
Flash it with Sky-Watcher's loader, with the mount bare and powered from a stable supply.

**Choose all your options in one command.** Each build starts from the official stock file,
and the script won't accept an already-patched file. To add or change a fix later, build again
from the stock file with the full set of options. For example, `--recommended` is the same as:

```
python eqal55i_patch.py MC016_Ver0348.mcf --fix-usb --fix-d-cr --fix-x06 --dec-ff 240 --dec-ki 16 --round --in-position 5
```

### Options

| Option | What it does |
| --- | --- |
| `--recommended` | All three fixes, Dec feed-forward 240, Dec integral gain 16, rounding and in-position status at 5 counts. The tested combination. |
| `--fix-usb` | USB reply fix only. |
| `--fix-d-cr` | `:D` reply fix only. |
| `--fix-x06` | `:X 06` fix only. |
| `--fix-all` | All three fixes above, without changing Dec motion. |
| `--dec-ff N` | Dec feed-forward strength, in motor-drive units out of 2401. Range 1–300; `--recommended` uses 240. 180–240 suits most setups. |
| `--round` | Round the firmware's target to the nearest count instead of toward home. Both axes. Included in `--recommended`. |
| `--in-position N` | Report "stopped" only when the axis is within N counts (1–10) and nearly still, or after 1 s. Both axes. `--recommended` uses 5, the value tested. |
| `--check FILE` | Shows which fixes a `.mcf` file contains. |

### Advanced options

**Leave these alone.** `--recommended` already includes the one servo change that helped on
the bench (Dec integral gain 16). The settings below adjust the servo tuning: the gains, and
how hard the motor may hold or brake. Apart from Dec integral gain 16, none of them improved
anything in testing, and a bad value can make an axis hunt, buzz or overshoot. Only touch them
if you understand servo tuning and can measure the result.

Both axes have the same limits: twice the higher of the two stock values.

| Option | Stock (Dec / RA) | Range | What it does |
| --- | --- | --- | --- |
| `--cap F` | 0.10 (shared) | 0.05–0.20 | The share of full motor drive allowed when holding, braking or pulling back. Tested at 0.15 and 0.20 with no measurable effect. Too high can cause hunting at rest. |
| `--dec-ki N` | 8 / — | 1–32 | Dec integral gain. `--recommended` uses 16, the only value tested above stock. Higher closes the last few counts faster after a move. |
| `--dec-kp N`, `--ra-kp N` | 25 / 20 | 1–50 | Proportional gain. |
| `--ra-ki N` | — / 16 | 1–32 | RA integral gain. |

## Going back

- **To return to stock:** flash the stock `MC016_Ver0348.mcf` with the loader.
- **If the loader can't connect to the mount:** see [RECOVERY.md](RECOVERY.md).
- **If a flash is interrupted:** the mount should start in update mode by itself. Flash again.

## Results

Tested on an EQ-AL55i Pro, bare mount, over USB:

- **USB:** 0 bad replies in over 70,000 commands, and no retries in a 25-minute driver
  session.
- **Dec start:** moves within 50 ms. Stock took 300–450 ms.
- **Dec delivery:** 500 ms pulses in the same direction land within about 1 count of target
  (1 count ≈ 0.36″).
- **Settling after gotos:** after gotos of 0.1–45°, Dec is within 2″ of target almost
  immediately (stock gain: 1.3–1.7 s) and within 2 counts (under 1″) in about 1 s. RA is
  unchanged at about 0.7 s.
- **Rounding:** in ASCOM ConformU's pulse-guide tests, the difference between East and West RA
  pulses dropped from about 3.5 counts to under 1, and between North and South Dec pulses
  from about 2.5 to 1.5 counts.
- **In-position status:** "stopped" was reported with the axis within 5 counts on all 48 test
  gotos, 0.1–1.0 s later than stock. Guide pulses report "stopped" about 40 ms after they end.
- **ConformU:** a full ASCOM ConformU telescope test with `--recommended`, over USB, ran for
  21 minutes with every response time within ConformU's targets and no dropped connection.
  All 16 directional pulse-guide tests (North, South, East and West at four hour angles, 5 s
  each) landed within tolerance on their own axis: Dec within 1″ of the expected 37.6″, RA
  within 0.07 s of the expected 2.51 s. Asynchronous single- and dual-axis pulse guiding
  passed.
- **At rest:** Dec held still.

### Dec guide pulses, before and after a mechanical service

The same mount was tested three times: on stock firmware, again on stock after a full
strip, clean and re-lube, then on `--recommended`. Each test sent 20 Dec pulses each way at
0.5, 2 and 5 s, at 0.5× sidereal with the mount at home and tracking on, and read the position
2 s after each pulse. The values are how much of the requested movement was delivered.

| Dec | Stock, before service | Stock, after service | `--recommended` |
| --- | --- | --- | --- |
| Worst pulse length | 39.7% | 76.6% | 90.0% |
| Range | 39.7–99.2% | 76.6–104.4% | 90.0–97.8% |
| Pulse-to-pulse spread (avg SD) | 0.42″ | 0.30″ | 0.23″ |
| 0.5 s pulses, North / South | 55.5% / 39.7% | 92.4% / 76.6% | 90.4% / 90.0% |
| 2 s pulses, North / South | 94.1% / 86.5% | 104.4% / 97.2% | 95.1% / 95.1% |

The service brought short pulses most of the way up, but left North and South as uneven as
before. `--recommended` evens them out and tightens the spread. Dec still comes up about 1–2
counts (under 1″) short per pulse. RA was within 94–104% in all three tests, with no clear
change.

## License

MIT, for the script only. The firmware belongs to Sky-Watcher; don't share patched files.
