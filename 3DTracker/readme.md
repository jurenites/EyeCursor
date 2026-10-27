This project provides a real-time 3D eye tracking system using a near-eye infrared camera, OpenCV, and optional OpenGL visualization. It detects the pupil in each frame, fits an ellipse to estimate eye orientation, and projects a 3D gaze direction vector from the user's eye center through the pupil.

Use Orlosky3DEyeTracker.py for single-eye tracking or Orlosky3DEyeTrackerStereo.py for simultaneous left- and right-eye tracking. The optional gl_sphere.py module provides a render of the 3D sphere. In the GUI that runs with the application, you’ll be prompted to select a camera stream or video file. The main display shows the detected pupil and 3D origin and direction vector. If gl_sphere is available, a 3D model will be rendered in a separate OpenGL window. A video with DIY tracking glasses and sample output can be found here: https://youtu.be/zuoOvywtwtA

An inexpensive eye tracking camera and extension cables for testing can be found here:
- GC0308 Eye Tracking Camera ($17): https://amzn.to/41x8p2W
- USB extension cables ($10): https://amzn.to/43SznVl

To help support this software and other open-source projects, please consider subscribing to my YouTube channel: https://www.youtube.com/@jeoresearch, or joining for $1 per month: https://www.youtube.com/@jeoresearch/join.

Requirements
- Python 3 or above
- OpenCV (opencv-python)
- NumPy
- (Optional) PyOpenGL and gl_sphere.py for 3D visualization

To install dependencies via terminal:
```bash
pip install opencv-python numpy tkinter
```

Stereo Tracking

Run the stereo tracker from the project directory:

```bash
python Orlosky3DEyeTrackerStereo.py
```

The input window contains separate controls for the left- and right-eye cameras:

1. Select the camera index for each eye. When two cameras are available, the initial selections default to the first camera for the left eye and the second camera for the right eye.
2. Use **Start Left Camera** and **Start Right Camera** to begin tracking. Either eye can also be started or stopped independently.
3. Use each camera's **flip image** checkbox if its image is mounted upside down.
4. Move each eye through several gaze directions while the tracker estimates the eye sphere. Press **F**, or select **fixed eye sphere**, once the estimated sphere is stable. Press F again or clear the checkbox to resume automatic adjustment.

The stereo camera windows support these keys:

- **Q**: stop both cameras.
- **Space**: pause or resume both camera streams.
- **F**: toggle automatic eye-sphere adjustment.
- **E**: toggle capture of persistent pupil ellipses for inspection.
- **C**: clear the captured ellipses.

The **Browse Video** option processes one recorded video with the currently active eye state; simultaneous stereo tracking is intended for two live camera inputs.

Stereo Output

Orlosky3DEyeTrackerStereo.py continuously writes one comma-separated line containing 12 values to `gaze_vector.txt`, in this order:

```text
left_origin_x,left_origin_y,left_origin_z,left_direction_x,left_direction_y,left_direction_z,right_origin_x,right_origin_y,right_origin_z,right_direction_x,right_direction_y,right_direction_z
```

An eye that has not produced a valid gaze result remains represented by six zeroes. Use `EyeTrackerStereo.cs` in Unity to read this 12-value format; update its `GazeFilePath` constant to the absolute location of `gaze_vector.txt` on your system.

Output
- gaze_vector.txt: Continuously updated with the current origin and direction vector. You can read this into Unity using the GazeFollower.cs script. It just reads the file constantly and updates the position and direction of the object it's attached to.
- Gaze vectors are also shown in the bottom-left corner of the OpenCV display.

Notes
- Press Q to quit or Space to pause a frame.

## Native macOS calibration

On an Apple Silicon Mac, run the new launcher from the repository root. It uses
the single-eye `Orlosky3DEyeTracker.py` pupil detector and an AVFoundation camera
capture, without Tkinter or the optional OpenGL sphere:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r 3DTracker/requirements-macos.txt
.venv/bin/python 3DTracker/setup_hybrid.py
.venv/bin/python 3DTracker/monitor_demo.py
```

The Python launcher starts **EyeCursor** in the macOS menu bar and opens live
diagnostics without starting calibration. Prepare the cameras and glasses, then
press **Start calibration** when ready. The default
live mode combines the glasses-mounted IR camera with the built-in laptop webcam.
It builds a small AppKit application on first launch using the macOS Swift compiler.
No browser or OpenCV window is opened by default. Grant camera access to the
application running the command in **System Settings → Privacy & Security → Camera**
if macOS asks.

After the first build, you can also double-click `.venv/EyeCursor.app` in Finder.
It starts the project's `.venv/bin/python 3DTracker/monitor_demo.py` backend,
opens diagnostics, and keeps its controls in the menu bar. Opening the app again
shows diagnostics; **Quit** stops its tracker process and releases the cameras.
You can copy the built app into `/Applications`. Its bundle records this project's
absolute path so the installed copy can find the tracking runtime. Keep the
project and its `.venv` in place; after moving the project, rebuild and recopy the
app. Startup errors appear in an alert, with details in `.venv/eyecursor.log`.

For the IR feed, the launcher selects **USB Camera** or **USB 2.0 Camera** and
refuses to substitute an iPhone or built-in camera. The separate head-tracking
feed defaults to the built-in FaceTime camera; `--head-camera-id` can explicitly
select an external webcam instead. It cannot be the IR device. No camera is
silently substituted. Use `--list-cameras` to see device names and IDs;
use `--camera-id` when more than one USB camera is connected. Reconnection follows
the same unique ID even if its camera index changes. Brief missing-frame intervals
keep the session open. After three seconds without a frame, it releases the
session and retries with a one-to-five-second backoff. A reopened session restarts
onboarding. The preview holds its last image and labels it paused during an outage.

### IR capture watchdog

Each USB IR camera now owns an isolated capture process. The parent receives only
the latest complete frame and its capture timestamp, so a driver blocked in
`VideoCapture.read()`, opening, or releasing cannot block the application thread.
A new worker gets eight seconds to produce its first frame. Once running, three
seconds without frames triggers termination (forced after 0.5 seconds if needed)
and the existing one-to-five-second retry backoff. Every open resolves the saved
USB device ID again, since camera indices can change after reconnecting. The other
IR camera continues independently. Incomplete/stale frames never become detections.
Workers exit if their parent exits, and shutdown releases them explicitly.

This handles blocked driver calls as well as ordinary failed reads. A reopened
capture still starts a new tracking session under the existing calibration
invalidation rules; it does not silently reuse samples from the interrupted
session. Diagnostics exposes waiting/reconnecting status. Physical cable faults
still require a working USB signal; the watchdog cannot repair the hardware.

### What each calibration can establish

| Stage | Uses | Establishes | Does not establish |
| --- | --- | --- | --- |
| Circular eye sweep | IR pupil/iris shapes | A diagnostic eye-center model, if coverage and stability pass | Anatomically verified center or screen coordinates |
| Center fixation with head motion | Paired IR pupil positions and webcam head poses | Empirical correction within the sampled head-motion range | Independent webcam gaze or camera-to-screen 3D geometry |
| Center plus four corners | Head-corrected IR pupil positions and known targets | A screen map when all five positions pass consistency checks | Independently measured gaze accuracy |

The webcam currently uses face rotation, translation and apparent size for head
compensation. Its iris landmarks are visual diagnostics, not a separately calibrated
gaze estimator. The face preview automatically crops around the observer; capture
requests 1280x720 while inference remains at at most 640 pixels wide. Preview crops
use the available original pixels, with a 0.5-second hold through face loss. Camera
hardware may supply a lower resolution. Cropping changes neither calibration
coordinates nor gaze inference, and does not create additional optical detail.

Diagnostics report eye-model readiness, head-correction readiness, captured screen
points and the current blocking condition. A timed-out target retains its stage and
reason in the status. The screen-gaze inset stays uncalibrated until a complete map
exists; it must never substitute the requested calibration target for measured gaze.
The current one-minute timeout and strict fixation/head bounds remain potential
usability bottlenecks. Passing synthetic tests does not validate physical accuracy.

### Combined IR and webcam onboarding

Open the laptop display and put on the glasses. Keep the IR camera fixed on the
frame. Face the laptop webcam and inspect the live previews. Press **Start
calibration** in the calibration panel when ready; seeing a face and pupil alone
does not start onboarding. Both feeds must be visible to collect measurements.
The small target appears above normal application windows on the **built-in laptop
display**, even if another monitor is set as the primary display. It does not take
keyboard focus or intercept clicks.

One press runs two learning stages automatically:

1. **Five dots.** Keep your head comfortably still and follow the center, then
   four corners. The center needs about one second of usable paired IR/webcam
   data. Each corner travels for 0.55 seconds, settles for 0.2 seconds, and captures
   for 1.2 seconds. Usable anchors establish the initial approximate screen map.
2. **Head movement.** The target moves smoothly back to the center. Keep watching
   it while following Slide sideways, Closer / farther, Nod and Turn cues beside
   that same target. Each cue lasts four seconds on a shared repeating timeline
   for both eyes. Collection and independent checking each cover a full cycle.
   The stage budget is 36 seconds, with up to sixteen extra seconds only to
   finish an already-started check. All four motion checks must pass before an
   early completion (after at least 33 seconds). Measurements come directly from paired camera
   frames, without mouse movement or a separate Start action. Only validated
   corrections are applied. If none qualifies, the five-dot fit is retained and
   the final result says so; reaching the time limit does not claim a good fit.
The desktop cursor resumes after the head stage. There is no automatic second
round of screen targets. Press **Check Accuracy** only when you want to measure
the resulting error. Its five new dots
never train the map; completing them is not required to use the cursor.

While any stage is running, **Stop calibration** hides the target and stops
collecting samples. The button becomes **Retry step N**, which restarts that
stage while keeping completed prerequisites. Calibration stays stopped until
you retry, including after a camera reconnect. If the first stage lacks usable
corner measurements, it stops with the reason and **Retry step 1**. Alternate
manual actions stay hidden or disabled during the guided sequence.

The panel has **Start/Restart calibration** and **Learn at cursor**.
The duplicate standalone head-learning and dot-learning buttons are removed from
normal controls. Their endpoints remain available for saved sessions and diagnostic
replay, but are not extra required setup modes. A legacy head session already in
progress retains a Finish action. **Align with IR preview** stays removed.

Choose **Learn at cursor** to refine the initial map. Move the pointer,
then deliberately look at it for about one second until the ring completes.
An accepted fixation stays green with a checkmark, even during a blink or lost
eye detection. Moving the pointer more than 5 logical screen pixels from the
saved position (a 10-pixel diameter) clears the checkmark and starts a new hold.
Once the pointer has been stationary for 1.25 seconds, smooth nodding and shifts
can contribute half-second paired movement blocks without freezing the pupils.
The eye and head trajectories must be coherent; abrupt pupil jumps, missing
frames and changing mouse targets cannot become movement anchors. Moving the
head by 0.25 in normalized pose distance re-arms the ring at the same target
(scales: 0.14/0.14/0.18 rad yaw/pitch/roll, 0.04/0.04 image position, 0.12 log face width).
Both eyes retain independent samples and corrections from the same known target.
Use **Control–Option–L** to toggle learning without moving the pointer or looking
at another part of the display. The menu offers the same on/off control and shows
whether learning is enabled. Stop before looking elsewhere. If another app owns
that shortcut, the menu remains available and its tooltip reports the conflict.
Each saved anchor records the corrected IR pupil coordinates, six webcam pose
features, and the known normalized screen position. Saved offsets now interpolate
across eye positions instead of fading away just because the pupil moved away
from the saved fixation. Repeat fixations at the same screen point with different
head poses teach a regularized head correction in the observed directions only.
Different screen targets alone cannot establish that correction. Unsupported
head poses still have no valid estimate; neither fitting nor rendering invents
an anatomical eyeball center.
Cursor alignment already trains empirical head compensation; the fixed-target
geometric follow-up is optional, not an additional prerequisite. Saved fixations can provide local
corrections even when a general head model cannot be accepted. Diagnostics now
distinguish insufficient repeats, insufficient motion, and inconsistent fitting
from a learned model. `/state` reports `head_correction_status`, contributing
pair count, and attempted fit residual separately from the accepted model error.
Those residuals are internal fit checks, not measured gaze accuracy. Cursor
journal samples carry a shared `fixation_id` per completed hold so evaluation
can keep whole fixations separate rather than treating adjacent frames as
independent validation evidence.
Brief detection gaps preserve the hold, but stale/duplicate samples and unstable
fixations cannot fabricate anchors. A conflicting anchor leaves the prior map intact.
The live gaze dot is calculated from camera data, not copied from the pointer.

Learning is explicit: ordinary mouse movement outside this mode collects nothing.
**Stop learning** keeps the accepted corrections for the current session.
Reopening alignment in that session retains representative fitting anchors (up
to 100). The fitted model is not restored across app restarts. Accepted numeric
observations are separately journaled under `.venv/calibration-sessions/<session>.jsonl`,
including each frame of accepted cursor fixations, the center, and corner captures.
These files survive restart but are evidence, not automatically reused models.
The underlying head-learning engine also supports explicit continuous capture
through the legacy diagnostic endpoint. It is no longer a separate menu action:
normal users learn head movement inside the guided flow or save new head poses
while looking at the system cursor. Only checked fits are applied; ordinary use
does not provide known gaze targets and never trains the map.

Fitting runs in a background worker after at least eight seconds of clear paired
samples and observed movement. It uses a recent 120-second window capped at 3,600
frames; all accepted measurements remain in the numeric journal. A frozen candidate
is fitted separately from live capture. The live diagnostics payload includes only
the latest 120 motion measurements plus the initial/manual references, so its size
does not grow throughout continuous capture. The candidate
is checked against the next four seconds of fresh measurements before application.
Failed fits and checks leave the current map active and collection continues.
Diagnostics and the numeric journal distinguish fitting failures from checking
failures and preserve the rejection reason. Finishing without a checked update
explicitly says that no new head correction was accepted.

If the assumed-optics geometry cannot fit the capture, `head_motion_map.py`
learns a robust, regularized pupil displacement from the six webcam head features.
A chronological inner split chooses linear/quadratic complexity and regularization;
0.4-second blocks prevent frame count from weighting a held pose excessively.
It corrects the measured pupil before the original screen mapping, retaining its
response to eye movement instead of predicting a constant center. Beyond measured
head bounds it uses the previous map, without extrapolating the polynomial.
The frozen empirical candidate must reduce fresh-check p80 error by at least 25%,
with no regression in median or p95, and p80 <=0.30 UV. Errors above 0.06 are
reported as reduced drift requiring further refinement, not accurate calibration.
This deliberately permits checked partial improvements that the former all-or-nothing
0.06 limit discarded. Center checks alone do not validate the entire screen.
Both eyes can fit and validate their own head correction during the same capture.

`replay_head_motion.py <events.jsonl> --eye-side left` replays a saved five-anchor,
steady-head session without changing the running app. Its chronological fitting
and checking intervals are disjoint. Because a recording can inform code design,
retrospective replay is not an independent real-world accuracy claim.

The geometric candidate uses `geometric_gaze.py`. In units
of screen width, it reconstructs the selected IR eye origin A from unmirrored webcam
position and full head rotation. Initial center/corner anchors plus the fixed B
observations fit an affine IR-pupil-to-head-local ray-tangent model and a bounded
depth scale (0.65 to 3.3 screen widths). Every prediction rotates the local eye
ray into the screen frame and intersects it with Z=0. The fixed target is used
only as a fitting/checking label; it never substitutes for the predicted cursor.
The fit jointly searches bounded effective vertical FOV candidates (30, 45, 60,
75 degrees) and depth rather than imposing a universal 45-degree lens. The fitted
FOV is still an estimate, not measured camera intrinsics. Central principal point,
eye separation (6.4/30.2 screen widths), lens mount, and face-size depth changes
remain assumptions. Each eye's independent mounting transform is learned from its
own pupil samples. Head fitting uses the exact committed center/corner capture
windows; earlier discarded detector candidates cannot shift those anchors.
Unsupported head poses no longer silently revert to uncompensated raw screen
predictions. The prior map is usable only where its caller explicitly supports it.
This is an approximate geometric model, not measured anatomical eye geometry.

Training is balanced between screen anchors and 0.4-second motion blocks.
Robust fitting downweights motion residuals against the eye/head/target relation,
using a median/MAD cutoff, rather than discarding genuine head extremes against
a global median. At least 70% and ten motion blocks must remain consistent.
Strong iris support can reject grossly squeezed or misoriented pupil ellipses
from this calibration; it does not force the pupil to the iris shape or change
live detection. Fresh-check residuals are not filtered by the candidate itself.
The fresh four-second check does not refit coefficients. Geometric acceptance requires at least
15 fresh samples spanning two seconds, observed head movement, an 80th-percentile
screen-UV miss no greater than 0.06, and improvement over the previous map
(15%, with a 0.015 UV tolerance for already-small errors). These are validation
checks on the known center target, not a full-screen accuracy guarantee. On
failure the previous cursor map remains active and the reason is shown. Validated
poses define the geometric model's supported range; elsewhere the previous map
is used only where it had support. Later cursor alignments retain the geometric
base and calculate their corrections at each anchor's own head pose.

The 3D scene receives the fitted depth and eye-spacing assumptions from the same
model. Successful training and checking samples appear as saved white rays.
`/state` exposes `geometry_calibration` (phase, remaining time and check residuals)
and `geometry_model`; these fits are still session-local. A replay of older saved
samples can fail the consistency check; the new procedure does not silently
install a model fitted to a previous wearing of the glasses.

The initial empirical map uses the IR pupil center directly and the webcam's face landmarks for
head rotation, position, and apparent size. It follows the landmark approach in
`Webcam3DTracker` using MediaPipe Face Landmarker, without launching that script's
separate calibration or mouse controls. It does not depend on the blue eye-sphere
estimate, reconstruct a physical eyeball center, or perform metric triangulation.
The webcam preview also marks both iris centers; the IR camera supplies fine eye
movement for the cursor. Eye-center/radius fitting now runs concurrently on those
same IR frames throughout the hybrid session, including the center and rectangular
steps. When its evidence becomes stable, the eye model freezes independently of
the screen mapping. The diagnostic green center-to-pupil ray and estimated
camera-space yaw/pitch appear only after the eye-center model passes stability checks. The blue outline is the image-space iris, not an eyeball sphere. These are
model-based angles, not a direct measurement of anatomical gaze or monitor angles.
`/state` exposes them as `eye_direction` only on fresh accepted IR frames with a
model estimate; `model_ready` indicates whether the estimate has passed stability
checks. A missing eye model does not block the empirical two-camera screen map.

The diagnostic webcam preview contains only the camera image and eye outlines;
the duplicate `Combined screen gaze` inset is removed. The 3D scene retains every
accepted sample from center/corners and successful cursor/preview fixations,
without the former 80-ray limit. White rays and endpoint markers are rendered
in one batch; samples at similar poses naturally overlap. **Accepted samples**
shows their count. Each record includes original and corrected IR coordinates,
captured head features, capture timestamp, known target, source/device identity,
and screen viewport. A new session gets a separate journal and scene cache key.
These are reference constraints, not independent physical ray measurements. The
latest pre-correction miss is shown in logical screen pixels, not advertised as
an independent accuracy score.

The 3D scene's pink left-eye and orange right-eye beams join the approximate
head-derived eye origins to the same smoothed, fenced endpoints as the independent
desktop eye rings. They visualize calibrated screen maps, not independently
measured physical rays. Their endpoints never use the calibration target or a
copy of the combined cursor. Missing estimates fade with the desktop rings.
The white scene marker remains the combined cursor. Screen-estimate labels retain
the unbounded UV values and say when the displayed endpoint is fenced at an edge.

**Show raw camera directions** remains on by default, but raw IR directions now
appear as short gray stubs. Blue webcam rays remain separate diagnostics. Their
assumed mounting rotation and origins cannot replace a learned screen map.

**Cursor eyes** in diagnostics offers **Both eyes**, **Left eye only**, and
**Right eye only** without resetting either calibration or stopping detection.
The selection is session-local and can change outside active calibration; changing
it clears the old accuracy report. An explicitly selected eye never silently falls
back to the other eye if missing. Both-eye mode uses the equal midpoint of the
two screen-fenced eye positions, sharing their display easing so the white cursor
stays between the colored markers. Disagreement above 8% of screen width remains
a diagnostic and no longer hides that midpoint. Raw estimates remain unchanged;
the midpoint is not an accuracy guarantee. Capture skew above 120 ms still fades
the cursor rather than mixing different moments. One available
calibrated eye can supply the cursor in Both-eye mode. **Show both eye cursors**
continues to display each eye independently regardless of the cursor-eye choice.

Both detectors have separate eye-sphere readiness checks. The companion now
freezes its own stable sphere and passes its readiness to the preview renderer,
so its arrow is no longer unconditionally suppressed. A new camera session or
calibration resets that readiness. These approximate sphere arrows do not train
the screen maps or guarantee gaze accuracy.

In **Camera setup**, each camera has a **Fixed eye sphere** checkbox. Checked
holds that detector's current estimated center and radius; unchecked resumes
automatic sphere adjustment. Pupil detection continues in both modes. Toggle it
after the sphere has settled to compare the effect without resetting the current
estimate, camera stream, or screen calibration. This affects the original 3D eye
model and its diagnostic rays; hybrid screen mapping uses measured pupil centers.
The explicit choice is saved independently for each camera slot and survives
relaunches. Existing settings keep readiness-based freezing until you change the
checkbox. A checked box does not establish that the eye model is calibrated.

The left camera's configured 180° rotation is applied exactly once, before pupil
detection and target collection. There is no assumption that the cameras are
mirror images: each eye's target labels learn its own orientation, scale, and
translation in processed-image coordinates. The laboratory's approximate raw-ray
mounting is separate and does not contribute to those screen maps. Raw directions
therefore no longer report a screen hit, an `outside` verdict, or an angular/plane
error; those would imply a measured mounting transform that does not exist.
Calibrated screen estimates retain their real outside/fenced status. Missing eye
maps now show **needs target samples**, distinct from temporarily missing paired
observations. The screen-estimate section has room to show both eye rows.

Both eyes learn from five shared targets, not separate passes. During each
stationary target, each camera independently collects a contiguous stable block
(at least six fresh samples spanning 300 ms) with its own paired webcam poses.
Once completed, that eye's block stays saved while the other settles; a later
blink cannot erase it. Live collection does not restrict the companion to the
primary eye's selected interval, or require the primary pupil to be accepted
before collecting the companion. Target progress reflects both configured eyes.
A missing camera gets a bounded wait of about eight seconds per target; its
samples are never invented. Each map uses only its own camera's measurements,
and a missing target reports its eye and target number. Legacy replay without
independent capture blocks retains the original timestamp-window selection.
Subsequent explicit cursor fixations still update both maps.
The `/onboarding/accuracy-start` endpoint remains available for independent checks.
Starting refinement clears the old accuracy report. Stopping
the accuracy check preserves the existing mapping and marks the report incomplete.
The report is an accuracy measurement, not an automatic claim of usable cursor
precision. Session audit logs include completed or interrupted check results.


### Learning from known targets

The legacy **Learn from dots** endpoint remains available to diagnostic clients.
Its redundant button is removed from the normal interface. This is a supervised
learning pass, not an accuracy score. The optional **Check accuracy** button now
calls only the independent checking endpoint. Five displayed targets provide
the labels. The same independent per-eye capture blocks used by onboarding keep
each completed eye while waiting for the other at the shared target (up to eight
seconds). Each IR camera independently collects fresh, stable pupil coordinates
and its paired webcam pose and timestamp. Neither predicted screen position nor
left/right agreement gates collection. All accepted observations are logged as
`dot_learning_sample`; the final `dot_learning_result` contains the settled
per-target blocks and each eye's outcome.

The old mappings stay untouched and gaze output is hidden during capture. After
all five targets, each eye's labelled anchors update its own map. If the old map
cannot support those anchors, a fresh five-point map is fitted from the new pass.
A missing or degenerate eye capture keeps that eye's previous map and reports it
unchanged. One missing camera does not fabricate data or prevent the other from
learning. Stop preserves both existing maps; Retry dot learning starts a new pass.

Left and right desktop rings use the same 24-point DotView component and differ
only in color. The 3D head has equal eye outlines with no selected-eye center dots.

### Rotation and translation calibration

The webcam scale feature now corrects projected cheek width for head rotation and
camera aspect ratio. A yaw turn or roll at constant distance should not be treated
as moving farther from the screen. This is a weak-perspective face-width estimate,
not a measured absolute depth; near-profile faces are rejected for this purpose.
New logs identify the feature convention as `rotation_corrected_face_scale_v1`.
Do not mix earlier raw-face-width logs into these fits without reprocessing them.

The underlying head-learning engine accepts the current manual cursor map's
saved anchors as well as guided calibration anchors. While looking at the same
fixed dot, gently turn and slide sideways in any order. There are no prescribed
movements or timeout. Training and checking report
rotation and independently observed translation separately. Position changes
explained only by turns are not counted as an independent translation check.
A run that observes only one movement can retain its useful fit, but explicitly
reports which movement still needs checking. The initial steady-head map remains
active until a geometric fit passes its fresh-data accuracy check.

The geometric model uses `D = R_head D_eye` and `P = A + (-A.z/D.z)D` for a screen
at z=0. Translation changes A; rotation changes D and the anatomical eye offset.
If the head translates with unchanged eye and face directions, the screen landing
point moves. Holding a fixed screen target instead requires an eye counter-turn.
The IR/head pairing, unbounded intersection and desktop fencing remain separate.

Continuous calibration currently fits the selected IR eye with the paired webcam
head pose. The second IR camera provides independent diagnostic tracking; its ray
is not yet a separately calibrated contribution to the cursor. This update does
not introduce binocular fusion or metric multi-camera triangulation.

### Short detector glitches and cursor response

Each detector now has an independent `RasterHold`. A rejected/low-confidence
frame can retain the last reliable preview pupil for at most 120 ms, only when
the actual pupil neighbourhood is nearly unchanged. Comparison excludes tiny
saturated glints and tolerates small sensor noise, but rejects changed edges,
blinks, saccades, and large brightness changes. The time limit is measured from
the original reliable frame and cannot be extended by subsequent held frames.
Source/rotation changes reset this state with the detector.

The held pupil is carried separately as `display_hold`; raw confidence and raw
ellipse stay unchanged. `prediction_observations_at` can combine that short-held
pupil with a fresh paired head pose for cursor display. `observations_at`, target
captures, sphere estimation, head fitting, and click acceptance continue to use
raw observations only. A successful held display is not a calibration sample.

Cursor smoothing is adaptive: purposeful moves use a 20 ms Python low-pass and
a 25 ms native spring response instead of the former 80/70 ms combination.
Small fixation noise retains slower filtering. Existing median/spike rejection,
display fencing, and loss fading remain. Both individual eye markers and the
combined white marker use the same native motion component.

### Head-movement collection outcomes

The second eye now collects center-target movement independently even when the
primary pupil is rejected. Its own paired webcam timestamps, fit, and later check
remain separate. Initial fit readiness is checked every 250 ms; being slightly
short of the eight-second capture no longer incurs a six-second retry delay.
The retry backoff still applies after a rejected candidate.

The guided capture asks for small repeated turns and shifts, returning to the
starting position, and repeats those movements during checking. A failed fit is
shown as **No correction learned**, rather than a completion checkmark. Learning
for only one configured eye is reported as **One eye corrected**. Neither a timer
nor a reduced residual on training data can grant an applied correction.

The October 19 v0.40 session contained head movement but its later checking
capture did not validate the fitted correction. Offline replay still rejects
that recording with the current fit safeguards; no improved real-world head
accuracy is claimed from these changes. New capture guidance and independent-eye
collection require a fresh wearer calibration to evaluate.


### Optional second face webcam

In **Diagnostics → Camera setup → Second face webcam**, select the table or
side webcam. Its stable device ID is saved separately in `.venv/head-cameras.json`.
The two IR assignments and the primary head webcam are excluded; identical model
names remain individually selectable. **Disabled** returns to the primary webcam.
The second feed has its own preview, frame rate, alignment progress, and assistance
status. It captures in a separate process, so a low-rate or blocked USB driver
does not hold the primary camera or pupil tracking loop.

Before gaze calibration, click **Learn second view**. Keep both cameras fixed and
the same person visible. Slowly turn, nod, tilt, shift sideways and up/down, and
lean toward/away from the screen; repeat the range of movements. After at least
80 distinct paired frames and 20 seconds, click **Finish alignment**. A later
quarter of the capture validates the view mapping without being used for fitting.
If the motion is insufficient or the views disagree, keep moving and try finishing
again. Then start normal eye/screen calibration. Changing the view alignment clears
old gaze calibration; finish or stop an active calibration before changing it.

This is **empirical head-pose fusion in the primary camera's coordinates**, not
metric stereo triangulation. It learns a local mapping of second-camera rotation,
image position, and face scale to primary-camera features. Only observed motion
ranges are supported. Fresh, consistent observations contribute up to 25%; their
weight falls with timestamp skew and reaches zero at 120 ms. The correction is
applied to the current primary pose so an older second-camera frame does not
replay old head motion. Missing faces, stale frames, unsupported poses, or view
disagreement use the primary alone. Losing the primary still suspends valid gaze.
Both IR eyes, gaze calibration, and the diagnostics scene consume the same fused
head features. Camera samples use capture-return timestamps, not synchronized
hardware exposures; a source with hidden buffering may be rejected by alignment.

Alignment is intentionally session-local: learn again after launching, reconnecting,
moving either webcam, or changing the person. Repeated inconsistent view pairs
invalidate it automatically, but subtle camera movements cannot always be detected.
A passed alignment establishes consistency with the primary view, not measured
screen-gaze accuracy. Use the existing gaze accuracy check after screen calibration.
Measured stereo depth would additionally need calibrated lens intrinsics, distortion,
and camera-to-camera/screen geometry; existing screen geometry assumptions remain.

### What the geometry can establish

The left and right IR cameras observe different pupils, so these images are not
a stereo pair of the same 3D point. Their calibrated maps remain independent.
Screen gaze combines each eye's calibrated direction with webcam head rotation
and position, then intersects the resulting ray with the screen plane. Following
one fixed target during head movement supplies counter-rotation evidence; it does
not imply that pupil coordinates stay constant. Cursor refinement supplies the
same kind of known target plus measured eye/head evidence at additional poses.

The optional second webcam currently learns an empirical pose alignment to the
laptop webcam. It does not supply measured stereo intrinsics/extrinsics. True
metric triangulation would require those camera calibrations and their transform
to the screen; neither a target snap nor the illustrated 3D beams proves physical
millimetre accuracy. The expanded FOV search retains later-data checks and does
not automatically apply old logs as calibration for the current wearer.

### Nodding evidence and validation

A candidate's live pose bounds no longer prevent its evaluation on fresh checking
poses. Validation evaluates the frozen mathematical model first, keeps the same
accuracy/improvement requirements, and expands live bounds only around successful
checked poses. It does not enable unconstrained extrapolation during normal use.
The audit reports `outside_training_support`, `missing_predictions`, actual
candidate/baseline error, and checking head-angle span separately. This avoids
misreporting an untested pose as a ten-screen mathematical error.

Explicit cursor learning adds `cursor_learning_update` records containing the
known target, capture kind, signed head-angle and translation-feature changes,
paired eye estimates before the update, and the head correction's status/rank.
`cursor_started`/`cursor_finished` log the labeling toggle. No satisfaction score
is inferred from cursor proximity; these are user-authorized target labels and
training feedback, not an independent accuracy measurement. Head compensation
still requires observations at different poses: seeing blue face-direction rays
alone does not establish calibrated IR-camera mounting or metric eye origins.

### Four head motions

The guided center-target stage distinguishes sideways shifting with the face
forward, moving closer/farther with the face level, nodding with eye
counter-rotation, and turning with eye counter-rotation. The depth check requires
change in rotation-corrected face scale; sideways image motion cannot satisfy it.
Both independent eye solvers classify samples by the same visible cue clock,
even when they finish fitting at different times.

A teal animated instructional head in the 3D scene demonstrates the movement
relative to the starting head pose. Its thin teal sight lines remain on the known
center target and are explicitly labelled Guide. The measured head and pink/orange
gaze beams remain separate and unchanged. The illustrated amplitudes are small
examples, not measured distances or required positions. Check
results retain separate sample counts, movement presence and prediction errors
for each cue. A fit that works in one segment cannot pass by averaging that
success with a failed segment. The underlying six webcam features and independent
IR observations remain available in the audit; the cues do not manufacture angles.

Empirical head fitting can now include cross terms (yaw × pitch, yaw × translation,
and other observed combinations), rather than only separate linear/quadratic axes.
Model order and regularization still use held-out time blocks, and acceptance
still requires a later frozen-model check. Old square-only model snapshots retain
their original feature interpretation.

After a check concludes, its explicitly labeled observations are retained for
future fits even if the candidate failed. They never refit the candidate whose
check they were part of. A failed or partial guided pass exposes **Retry head
movement**, preserving screen anchors and the movement observations in memory;
full restart remains available from the menu. This does not restore measurements
after changing the camera mounting or restarting the application.

### Recording gaze paths and dwell

Choose **Record & replay…** in the EyeCursor menu. This opens the local recording
page; it does not start capture. After calibration, select the display and press
**Start recording**, then **Stop** before quitting EyeCursor. Screen capture uses
macOS Screen Recording permission. Recordings stay under `recordings/` in the
project. The page can also run with `.venv/bin/python 3DTracker/session_recorder.py`.

New sessions preserve the original observations in `gaze.jsonl`, screen video,
and cursor coordinates. The recorder polls at up to 30 Hz and retains per-eye
capture timestamps, detector validity, unbounded screen estimates, head features,
confidence and the separate displayed position. Retina display point coordinates
are converted independently of video pixel dimensions. Repeated camera samples
are deduplicated for review. Held preview values, calibration samples, missing
samples, and off-screen positions do not contribute to fixation dwell. The capture
is not a high-speed saccade instrument: timestamps on the replay are state-observation
times, not a guarantee of sensor-exposure synchronization. No eye images are saved
separately by this screen recorder.

Replay offers a measured path, flagged points, a duration-weighted heatmap, and
static areas of interest. A short low-confidence A→B→A spike is labelled a
**possible glitch** only when neighboring points agree and the jump is large.
The raw record is unchanged. A→B→B keeps the new location from its first sample;
there is no extra live smoothing or delayed cursor animation. Lines only connect
observed points, and gaps are left open. This is a retrospective heuristic, not
proof that a particular movement was an artifact.

Fixations use screen-space bounding-box dispersion and minimum duration (default
45 video pixels, 120 ms); missing intervals over 100 ms break them. These are
adjustable review assumptions, not anatomically calibrated visual-angle thresholds.
The heatmap sums fixation durations and applies a Gaussian drawing kernel;
its radius changes display softness, not the claimed spatial accuracy. Original
measurement timing and raw coordinates remain available separately. This follows
the general separation of raw gaze, fixation classification and visualization
used in [Pupil Player](https://docs.pupil-labs.com/core/software/pupil-player/).

Set a time range and press **Review range**. Pause and use **Mark an area** to draw
a rectangle over a text block or control. The report counts fixation centers and
their duration inside each rectangle; overlapping rectangles can count the same
fixation. Boxes are stored locally in the browser for that recording and included
in **Export review JSON**, along with thresholds, sample classifications and
fixations. They are not attached to moving content: for scrolling pages, scene
cuts or video, select short stable intervals. No semantic text/object recognition,
reading/comprehension inference, or gaze-to-content registration is performed.
Looking near a paragraph does not establish that the entire paragraph was read.
