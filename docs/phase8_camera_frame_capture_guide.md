# Capturing the Full-Rack Camera Frame (Track A)

**Goal:** one clear still image of a **full rack (all 10 pins standing)** from a lane's T-Camera, grabbed through your **VIXLW USB dongle** into your **Windows laptop**. That single image lets me calibrate the pin detection (`PIN_SPOTS` + brightness threshold) and unblocks the whole scoring pipeline.

## What you need
- VIXLW USB capture dongle (you have it)
- Windows laptop
- The lane's **T-Camera composite video cable** (we borrow it for ~5 min)
- Maybe an **RCA coupler/adapter** if the camera cable end doesn't match the dongle's RCA jack
- A capture app (options in Step 3)

## Heads-up (low stress)
The camera video is low-voltage and harmless. The only consideration: you'll briefly unplug the camera from the scoring box, which **pauses that lane's auto-scoring for a few minutes** — the pinsetter itself keeps running fine. Use a **pilot lane (21 or 22)** during a slow time.

## Steps

**1. Set a full rack.** At lane 21 or 22, cycle the machine so a fresh, complete set of **10 pins is standing** on the deck (normal first-ball-ready state). That's the "full rack" the camera should see.

**2. Find the T-Camera's video cable.** The camera is mounted above/behind the pin deck, aimed at the pins. Follow its thin cable back to the **scoring box** (QubicaAMF / T-VISION unit) and find where that camera's composite video lead plugs in — usually an **RCA or BNC** connector.

**3. Set up the dongle + app on the laptop.**
- Plug the VIXLW into USB. Windows usually detects it automatically; if it came with a driver (CD or download link), install that.
- Open a capture app — easiest first:
  - **VLC** (free): *Media → Open Capture Device →* pick the VIXLW as the video device *→ Play*, then *Video → Take Snapshot* to save a still.
  - **OBS Studio** (free): add a *Video Capture Device* source → pick VIXLW → right-click the preview → *Screenshot*.
  - Or the **app bundled with the dongle**.
- If the app asks for a video standard, choose **NTSC**.

**4. Connect the camera to the dongle.** Unplug the T-Camera's composite lead from the scoring box and plug it into the VIXLW's **yellow RCA (video)** input (use an adapter if needed). You should now see the pin deck in your capture app.

**5. Grab a clean full-rack still.** With all 10 pins standing and the deck lit normally:
- Confirm the image shows the **whole pin deck, all 10 pins**, reasonably in focus and lit.
- **Take a snapshot / screenshot → save as PNG or JPG.**

**6. (Bonus — if easy) grab 2–3 more states** for calibration robustness:
- **Empty deck** (strike — bowl/cycle to clear all pins)
- **Partial rack** (a few down, e.g. leave the 7 or the 10) — gives me lit-vs-dark contrast per pin
- Name the files if you can (`full`, `empty`, `partial`)

**7. Reconnect** the camera lead to the scoring box (restores that lane's auto-scoring).

**8. Send me the image(s).**

## What "good" looks like
All 10 pin positions visible, deck fills a good part of the frame, pins clearly lighter than the dark deck, normal lighting. **Don't overthink focus** — even a slightly soft frame is fine for calibration.

## If you get no picture
- Confirm the video lead is in the dongle's **yellow** RCA jack.
- Confirm the app's selected device is the **VIXLW** and the standard is **NTSC**.
- Confirm the camera still has power (unplugging the video lead shouldn't unpower it — but check).
- If "no signal," try an adapter or reseat the connector.

That's the whole job — one good full-rack frame and we're into real pin detection.
