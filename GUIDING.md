# Guiding: before and after

How the mount behaves when guiding, with stock v3.48 and with a `--recommended` build.
Numbers are from the [Results](README.md#results) in the README.

## It isn't all backlash

Backlash is play in the gears. It only shows when an axis **reverses**: the motor turns a
little before the sky moves.

Stock v3.48 has a Dec delay that looks the same in a guiding log, but it happens at the start
of **every** Dec pulse, even two in a row in the same direction. If you see lag on
same-direction pulses, it's the firmware, not (only) the gears.

The patches don't remove real gear play. They remove the firmware problems that get mistaken
for it.

## Dec guide pulses

**Before:** at the start of a pulse, Dec sits still for 0.3–0.45 s until the servo pushes hard
enough to beat gear friction. Short corrections arrive late or come up short. The guider sends
more, then they all land at once and overshoot.

**After:** an extra push in the direction of travel (feed-forward) gets Dec moving within
50 ms. A 500 ms pulse lands within about 1 count (0.36″).

```
500 ms pulse
Before: ......>>>
After:  >>>>>>>>>
```

## North vs South, East vs West

**Before:** at each speed change the firmware rounds its target toward home. Pulses one way
always gain a little and pulses the other way always lose a little, up to about 1″ each. One
direction feels "stiffer", which gets blamed on backlash or balance.

**After (`--round`):** rounds to the nearest count, so the errors average out. In ConformU the
East/West difference went from about 3.5 counts to under 1.

## After a goto, dither or flip

**Before:** the mount says "stopped" while the axis is still sliding up to about 13″, and Dec
takes another 1–2 s to finish. The first guide frames see the star drifting into place.

**After (`--in-position 5`, Dec gain 16):** Dec finishes about twice as fast, and "stopped"
is only reported once the axis is within about 2″.

## USB

**Before:** replies sent quickly can overwrite each other, so the driver retries and pulses
arrive late at random.

**After:** each reply waits for the last one. 0 bad replies in over 70,000 commands.

## After flashing

- Redo guider calibration.
- Measure backlash again before using any Dec backlash compensation.
- If you raised Dec aggressiveness to make up for the delay, try going back toward the
  default.
