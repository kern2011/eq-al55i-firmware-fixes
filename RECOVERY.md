# Recovery

> [!CAUTION]
> **These recovery steps are untested.** They are based on reading the firmware, not on
> recovering a real mount. They may not work, and there is no guarantee your mount can be
> recovered if something goes wrong. Use at your own risk.

You should rarely need this page. Normally, going back to stock is just a matter of flashing
the official `MC016_Ver0348.mcf` with Sky-Watcher's firmware loader.

Use this page only if the loader **can't connect** to the mount over USB, after you have
already tried:

1. Turning the mount off, waiting 10 seconds, and turning it on again.
2. Unplugging and replugging the USB cable, or trying another USB port.

## Put the mount into update mode through the hand-controller port

The mount has a second way in: the hand-controller port. Sending one command there should switch
the mount into update mode, where the loader can connect over USB again.

**You need:**

- An **EQMOD cable**: a USB cable that plugs into the mount's hand-controller socket.
- A Windows PC with **PuTTY** installed (free, from putty.org).

**Steps:**

1. Turn the mount off. Unplug the hand controller and plug the EQMOD cable into its socket.
   Connect the other end to the PC.
2. Turn the mount on.
3. Find the cable's COM port number: open **Device Manager** (right-click the Start button),
   expand **Ports (COM & LPT)**, and note the number next to the cable, e.g. **COM3**.
4. Open **PuTTY**. Under **Connection type**, select **Serial**.
5. In **Serial line**, type the port, e.g. `COM3`. In **Speed**, type `9600`.
6. Click **Open**. A black window appears.
7. Type `:Q155AA` exactly (colon, capital Q, one, five, five, capital A, capital A), then press
   **Enter**. Nothing will appear in the window; that's normal. If you make a typo, just press
   Enter and type it again.
8. Close PuTTY, unplug the EQMOD cable, and connect the mount's USB cable.
9. Run Sky-Watcher's firmware loader and flash the stock `MC016_Ver0348.mcf`.

## If a flash was interrupted

If the power or cable was lost while flashing, the mount should start in update mode by itself
the next time it is powered on (this is what the firmware's start-up code does, but it hasn't
been tested). Run the loader again with the stock file.

## If nothing works

The mount may need a repair. Reprogramming the board directly with a hardware programmer might be
possible, but it hasn't been tried, it means opening the mount, and it's outside the scope of this
project. No support is provided.
