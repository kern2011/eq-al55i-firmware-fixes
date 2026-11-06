# Guiding: before and after

How the mount behaves when guiding, with stock v3.48 and with a `--recommended` build.
Numbers are from the [Results](README.md#results) in the README.

## It isn't all backlash

Backlash is play in the gears. When an axis reverses, the motor has to take up that play
before the sky moves, so corrections in the new direction arrive late.

Stock v3.48 adds a delay of its own that looks just like it in a guiding log.

The patches remove that delay. They can't remove gear play, but if your mount has some, they
may make it less of a problem.

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

## Holding power cuts slow moves short

The firmware drops the motor to holding power (10% of full drive) as soon as its **target**
reaches the goal, not when the **axis** does. Whatever the axis still has to travel, it has to
cover on holding power.

**Before:** on a slow move like a guide pulse, Dec has barely started when the target
finishes, so most of the move is left to holding power. The axis creeps the rest of the way or
stops short.

**After:** feed-forward gets Dec moving straight away, which breaks the stiction, and keeps
it with the target. When holding power takes over, the axis is already moving and has little
left to cover. Dec gain 16 closes the rest about twice as fast.

Holding power stays at 10%. The patch leaves it less to do instead of raising it. Raising it
(`--cap`) made no measurable difference in testing.

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

## After flashing

- Redo guider calibration.
- Measure backlash again before using any Dec backlash compensation.
- If you raised Dec aggressiveness to make up for the delay, try going back toward the
  default.
