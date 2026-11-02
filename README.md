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

This writes `MC016_Ver0348_p1p2p6_ff240.mcf` and prints every change it made. Flash it with
Sky-Watcher's loader, with the mount bare and powered from a stable supply.

**Choose all your options in one command.** Each build starts from the official stock file,
and the script won't accept an already-patched file. To add or change a fix later, build again
from the stock file with the full set of options. For example, `--recommended` is the same as:

```
python eqal55i_patch.py MC016_Ver0348.mcf --fix-usb --fix-d-cr --fix-x06 --dec-ff 240
```

### Options

| Option | What it does |
| --- | --- |
| `--recommended` | All four fixes, with Dec feed-forward at 240. The tested combination. |
| `--fix-usb` | USB reply fix only. |
| `--fix-d-cr` | `:D` reply fix only. |
| `--fix-x06` | `:X 06` fix only. |
| `--fix-all` | All three fixes above, without changing Dec motion. |
| `--dec-ff N` | Dec feed-forward strength, in motor-drive units out of 2401. Range 1–300; `--recommended` uses 240. 180–240 suits most setups. |
| `--check FILE` | Shows which fixes a `.mcf` file contains. |

### Advanced options (untested on hardware; need `--experimental`)

**You don't need these.** `--recommended` fixes the problems above without them.

These options change the servo's built-in tuning: the gains, and how hard the motor may hold or
brake. None of them has been tested on a mount. A bad value can make an axis hunt, buzz or
overshoot. Only touch them if you understand servo tuning and can measure the result. Each one
is limited to twice its stock value.

| Option | Stock | What it does |
| --- | --- | --- |
| `--cap F` | 0.10 | The share of full motor drive allowed when holding, braking or pulling back. Shared by both axes. Range 0.05–0.20. Too high can cause hunting at rest. |
| `--dec-kp N`, `--dec-ki N` | 25, 8 | Dec servo gains (proportional, integral). Range 1–50 and 1–16. |
| `--ra-kp N`, `--ra-ki N` | 20, 16 | RA servo gains (proportional, integral). Range 1–40 and 1–32. |

## Going back

- **To return to stock:** flash the stock `MC016_Ver0348.mcf` with the loader.
- **If the loader can't connect to the mount:** see [RECOVERY.md](RECOVERY.md).
- **If a flash is interrupted:** the mount should start in update mode by itself. Flash again.

## Results

Tested on an EQ-AL55i Pro, bare mount, over USB:

- **USB:** 0 bad replies in over 70,000 commands, and no retries in a 25-minute driver
  session. Stock needed 3–10 retries.
- **Dec start:** moves within 50 ms. Stock took 300–450 ms.
- **Dec delivery:** 500 ms pulses in the same direction land within about 1 count of target
  (1 count ≈ 0.36″).
- **At rest:** Dec held still. RA is unchanged by the patches.

## License

MIT, for the script only. The firmware belongs to Sky-Watcher; don't share patched files.
