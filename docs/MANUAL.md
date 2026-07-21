# Brookfield DV1 Viscosity Logger — Sample Prep & Measurement Manual

This manual covers everything from preparing a sample to exporting a finished
data set, using the DV1 Logger application alongside the physical DV1
viscometer. It assumes the app is already installed (see README.md for
setup/installer instructions).

---

## 1. Before you start

**Equipment checklist:**
- Brookfield DV1 viscometer, powered and on a stable, level bench
- The correct spindle(s) for your expected viscosity range (see Section 6)
- Sample container(s) wide enough that the spindle doesn't come within
  roughly one spindle-diameter of the container wall
- A water bath or other temperature control, if your measurement needs to be
  at a controlled temperature (strongly recommended for polymer gels —
  viscosity is very temperature-sensitive)
- Guard leg accessory, if you have one (centers the spindle, protects against
  accidental contact)
- A PC with the DV1 Logger app installed, USB-B–to–USB-A/C cable if you plan
  to use the Serial (Discovery)/auto-capture features

**Important limitation to know up front:** the DV1 does not have a publicly
documented command set for live auto-logging. This app's primary workflow is
**manual entry** — you read the value off the DV1's own display and type it
into the app. This is fully functional for logging, plotting, statistics, and
export. See Section 11 and the app's About tab for details.

---

## 2. Preparing your sample

1. Bring the sample to your target temperature before measuring, and keep it
   there for the duration (a water bath around the sample container works
   well). Note the temperature — you'll enter it with each reading.
2. Fill the container so the spindle will sit at the correct immersion depth
   with adequate clearance on all sides and below the spindle.
3. Check for trapped air bubbles near where the spindle will sit — they read
   as artificially low torque/viscosity. Give the sample time to settle, or
   degas if needed.
4. **For polymer gels / concentration series specifically:** viscosity can
   change by orders of magnitude across a concentration series, and gels are
   typically shear-thinning (viscosity drops as speed/shear rate increases).
   Plan on re-selecting spindle/speed for each concentration (Section 6), and
   decide up front whether you want each reading individually optimized into
   the 10–100% torque window, or a fixed spindle/speed held constant across
   the whole series so the *shear rate* stays comparable between samples —
   the app's Statistics tab can fit a power-law model (n, K) if you take
   multiple readings at different speeds on the same spindle/sample.

---

## 3. Mounting the spindle on the DV1

1. With the motor off, screw the spindle onto the coupling by hand until
   snug. Brookfield spindle couplings are **left-hand threaded** — turn
   counter-clockwise to tighten.
2. Lower the spindle into the sample until the liquid surface sits exactly at
   the immersion groove/mark etched on the spindle shaft. Under-immersion is
   one of the most common causes of bad readings.
3. If you have a guard leg, attach it now, centered around the spindle.

---

## 4. Installing and launching the app

1. Run `DV1Logger-Setup.exe` (Start Menu shortcut afterward), or launch
   `DV1Logger.exe` directly from the `dist\DV1Logger\` folder.
2. On first launch you'll see a brief splash screen (EML logo), then the
   **Dashboard** tab opens — this is the main screen you'll use for every
   measurement.
3. The Dashboard is tall; scroll down within it to reach the data table and
   live plot at the bottom.

---

## 5. (Optional) Connecting the instrument

The DV1's USB-B port (the one marked with a small monitor/PC icon, not the
one marked with the plain USB trident icon) can be connected to your PC for
raw protocol discovery and automatic capture of whatever the instrument
streams — but **not** for auto-filled readings yet (see Section 11).

1. Plug the USB-B cable from that port into your PC.
2. Windows should auto-install a driver and show a new COM port in Device
   Manager within a few seconds.
3. In the Dashboard's **Viscometer** panel: click **Search** to refresh the
   port list, select your port (it'll show a description like "USB Serial
   Port (FTDI)"), leave Baud at 9600, click **Connect**.
4. This step is entirely optional for basic logging — skip it and go
   straight to Section 6 if you only need manual entry.

---

## 6. Deciding which spindle and speed to use

You need this decision made *before* taking a reading, for every sample /
concentration.

**Option A — use the built-in advisor (recommended):**
1. In the Dashboard's **Viscometer** panel, set **Model** to your DV1
   variant.
2. In the **Spindle / Speed Advisor** section, type your best estimate of
   this sample's viscosity (cP) — from a spec sheet, a prior batch, or a
   guess — and click **Suggest Spindle & Speed**.
3. The table lists spindle/speed combinations predicted to land in
   Brookfield's recommended 10–100% torque window, ranked closest to 50%
   (the most accurate part of the range). Double-click a row to load it into
   Spindle/Speed above.

**Option B — trial and error (if you have no viscosity estimate at all):**
1. Start with a mid-sized spindle (e.g. LV2 or RV3) at a moderate speed
   (~30–60 RPM). Select this same spindle/speed on the physical DV1 too.
2. Take a reading (Section 7) and check **% Torque**.
3. Torque under 10% → move to a larger spindle number or slower speed.
   Torque over 100% → move to a smaller spindle number or faster speed.
4. Repeat until torque lands in 10–100%.

---

## 7. Taking one measurement

1. **On the physical DV1:** select the spindle and speed you decided on in
   Section 6, start the motor, and let the reading stabilize (several full
   spindle rotations at minimum — longer for viscous gels).
2. Read off the DV1's display: **Viscosity (cP)**, **% Torque**, and
   **Temperature** (or read your bath thermometer).
3. **In the app's Dashboard**, "Manual Reading Entry" section: type in the
   Viscosity, % Torque, and Temperature you just read, and confirm Speed
   (RPM) matches what the instrument is actually running.
4. (Optional) Fill in **Product Name** / **Batch** in Sample Info to tag
   which sample/concentration this reading belongs to.
5. Click **Add Reading** (or press **Ctrl+Enter**). The reading appears in
   the live readout boxes at the top, the data table, and the live plot at
   the bottom of the Dashboard. If torque was outside 10–100%, the app flags
   it immediately — go back to Section 6 and re-select spindle/speed if so.

---

## 8. Repeating for a full data set

Depending on what you're trying to produce:

- **Single reading per sample:** repeat Section 7 once per sample/concentration.
- **Shear-rate sweep (recommended for gels):** keep the same spindle and
  sample, and repeat Section 7 at several different speeds. This is what
  the Statistics tab's power-law fit needs — at least 2 points, more is
  better.
- **Concentration series:** repeat Sections 6–7 for each concentration.
  Expect to re-select spindle/speed as viscosity changes across the series.
- **Timed/paced entry:** if you want a reminder every fixed interval instead
  of clicking Add Reading whenever you happen to look up, set **Data
  Interval** (mm:ss) and **Num. of Data Points** in "Test Setup and Status",
  then click **RUN**. The status bar flashes "Reading due now" on each
  interval; click **STOP** to end early.

---

## 9. Reviewing your data

- **Data Table tab:** every reading logged this session. Select a row and
  click **Delete Selected Row(s)** to remove a bad point.
- **Plots tab:** Viscosity vs Time, Viscosity vs Shear Rate (the one that
  shows a gel's shear-thinning curve), % Torque vs Time, Temperature vs Time.
  Every plot has a zoom/pan toolbar (box-zoom, home, save image).
- **Statistics tab:** click **Refresh Statistics** for mean/stdev/min/max
  per field, counts of out-of-range torque readings, and — if you have
  multiple shear-rate points on one spindle — a **power-law fit** reporting:
  - **n** (flow behavior index): n < 1 → shear-thinning (typical of polymer
    gels), n ≈ 1 → Newtonian, n > 1 → shear-thickening
  - **K** (consistency index)
  - **R²** (fit quality — most meaningful when your points span a real
    range of shear rates, not just one)

---

## 10. Saving and exporting

- **Save Session...** (Ctrl+S): saves everything logged so far to a JSON
  file you can reopen later with **Load Session...** (Ctrl+O) — use this if
  you need to pause a long run and come back to it.
- **Export to Excel...** (Ctrl+E) or **Export to CSV...**: the final
  deliverable — every reading with all derived columns (shear rate, shear
  stress, FSR, torque status) in one file.
- **Clear Session**: wipes everything logged this session — only use this
  once you've exported/saved what you need.

---

## 11. Troubleshooting / limitations quick reference

- **"% Torque out of range" popup:** re-select spindle/speed per Section 6
  and retake the reading — readings outside 10–100% aren't reliable.
- **Live auto-fill / auto-logging of Viscosity/Torque isn't available:**
  the DV1 doesn't publish an open serial command set (it's designed to talk
  to Brookfield's own Wingather SQ software). The Serial (Discovery) tab can
  auto-capture the instrument's raw data stream, but its fields aren't
  decoded — manual entry is the reliable path today. If you obtain
  Brookfield's official interface command reference, this can be wired up
  for real.
- **Speed cannot be changed from the app:** for the same reason — sending an
  unverified command to actually drive the motor is not something this app
  will guess at.
- **Dropdown closes immediately when clicked:** fixed in the current build
  (a Windows-specific Qt popup bug); update if you're on an older build.
- **Can't find your COM port:** check Device Manager for a new port after
  plugging in the DV1's USB-B (PC) port specifically, not the other USB port.

---

## 12. Reference

- Spindle/model constants and FSR/shear-rate formulas: Brookfield DV1
  Operating Instructions manual (M14-023-A0416), Appendix D.
- Power-law (Ostwald–de Waele) model: standard rheology literature
  convention for shear-thinning/thickening fluids.
- Keyboard shortcuts: Ctrl+S save session, Ctrl+O load session, Ctrl+E
  export to Excel, Ctrl+Enter add reading, Ctrl+Q quit.
