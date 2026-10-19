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

The Python launcher starts **EyeCursor** in the macOS menu bar and automatically
begins onboarding when both the IR pupil and your face are visible. The default
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
frame. Face the laptop webcam; both feeds must be visible before onboarding starts.
The small target appears above normal application windows on the **built-in laptop
display**, even if another monitor is set as the primary display. It does not take
keyboard focus or intercept clicks.

1. Look at the center dot with your head comfortably still. About one second of
   usable paired IR/webcam data establishes the center and steady-head reference.
2. Look at four corner dots during one finite pass. Each travels for 0.55 seconds,
   settles for 0.2 seconds, and captures for 1.2 seconds. Screen capture takes
   7.8 seconds total; it never waits for a ring to fill or repeats automatically.
3. Usable anchors enable an **initial approximate map**. A piecewise map through
   center and corners supports non-affine eye geometry without requiring a single
   global affine fit. Degenerate or inconsistent measurements are not called ready.
   If the pass lacks usable data, it stops with the reason and **Retry step 2**.
   It never starts cursor learning automatically. Retrying preserves the center
   reference and gives the four dots a fresh finite capture pass.

While a calibration step is running, **Stop calibration** hides the target and
stops collecting samples. The button becomes **Retry step N**, which restarts
that step while keeping completed prerequisites. Calibration stays stopped until
you retry, including after a camera reconnect.

After the initial map, **Align with IR preview** places a small fixed marker over
the current pupil image. Look at that marker for one second. Keep looking at the
same screen point while gently turning or shifting your head, pausing at each
new pose. Both cameras supply each saved anchor; the pointer and live pupil do
not move the target. **Finish preview alignment** retains the accepted anchors.
The marker is a measured screen reference, not proof that the eyeball, IR lens,
and monitor are physically collinear. The raw green arrow remains relative to
the estimated eyeball center, with length proportional to the pupil offset; it
is not forced to zero by calibration.

Choose **Align with system cursor** to refine the initial map. Move the pointer,
then deliberately look at it for about one second until the ring completes.
An accepted fixation stays green with a checkmark, even during a blink or lost
eye detection. Moving the pointer more than 5 logical screen pixels from the
saved position (a 10-pixel diameter) clears the checkmark and starts a new hold.
Keeping the pointer at the same B while moving the head to a new A also starts
a new one-second hold. The change must exceed 0.6 in normalized pose distance
(scales: 0.14/0.14/0.18 rad yaw/pitch/roll, 0.04/0.04 image position, 0.12 log face width).
This excludes small tracking jitter. Hold the new pose still while watching B.
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
**Finish cursor alignment** keeps the accepted corrections for the current session.
Reopening alignment in that session retains representative fitting anchors (up
to 100). The fitted model is not restored across app restarts. Accepted numeric
observations are separately journaled under `.venv/calibration-sessions/<session>.jsonl`,
including each frame of accepted cursor fixations, the center, and corner captures.
These files survive restart but are evidence, not automatically reused models.
The former directional head-practice sequence is replaced by **Calibrate head
movement at fixed dot** in the EyeCursor menu. After the initial five-point fit,
watch the stationary center marker while gently turning or shifting your head
in comfortable directions. There is no left/right/up/down examination. Ten
seconds collect paired camera samples; the next five seconds check a frozen
candidate on new samples. A single well-observed head direction is sufficient.
The countdown advances by elapsed time, and the run ends even if capture fails.
Stop preserves collected data; invoking the menu again resumes an unfinished run.

This follow-up uses a new geometric cursor path in `geometric_gaze.py`. In units
of screen width, it reconstructs the right-eye origin A from unmirrored webcam
position and full head rotation. Initial center/corner anchors plus the fixed B
observations fit an affine IR-pupil-to-head-local ray-tangent model and a bounded
depth scale (0.65 to 3.3 screen widths). Every prediction rotates the local eye
ray into the screen frame and intersects it with Z=0. The fixed target is used
only as a fitting/checking label; it never substitutes for the predicted cursor.
Webcam vertical FOV (45 degrees), central principal point, eye separation
(6.4/30.2 screen widths), lens mount, and face-size depth changes remain assumptions.
This is an approximate geometric model, not measured anatomical eye geometry.

Training is balanced between screen anchors and 0.4-second motion blocks. The
fresh five-second check does not refit coefficients. Acceptance requires at least
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
an independent accuracy score. The live estimated ray remains visible outside
the monitor plane rectangle and transitions to red on loss, holding its last
known direction. Translation is disabled, orbit elevation is bounded, and zoom
is limited to 35–240 scene units.

Unbounded gaze projection and desktop presentation are separate. A finite,
valid off-screen estimate is fenced 8 logical pixels inside the display, keeping
the whole cursor circle visible. Missing/invalid eye or head observations remain
missing and use the existing fade; they are never clamped into fake gaze samples.
`unclamped_gaze` in `/state` retains the raw estimate for scene diagnostics.

The native path animates at 60 Hz using the same monotonic clock as capture.
Travel and settling frames do not train corner anchors. The short-pass ring shows
capture time at the current target, not an overall accuracy percentage. The app
checks anchor geometry and within-fixation repeatability before enabling an initial
map. Actual pointing accuracy must be checked by the wearer and refined as needed.

In cursor learning, the ring represents the one-second deliberate fixation.
It stays full after an anchor is saved until the pointer moves. Rejected unstable
or conflicting captures report their reason without replacing accepted corrections.
The target is white/gray in the laboratory, green/red outside it. White/green means
an accepted sample, not an independently accurate gaze. No floating tooltip text
is added to the target.

Head correction is an empirical approximation valid around the poses observed at
the center dot. Larger head movements, loss of the face, or mismatched camera timing
stop live gaze updates. The desktop circle carries its displayed velocity forward
while fading to transparent over 1.5 seconds. Returning measurements smoothly
redirect the circle and restore its opacity; after a full fade it fades in at the
fresh position. Prediction affects only the visual circle, never calibration or
click coordinates. Disabling the cursor or starting calibration still hides it
immediately. Both cameras run locally; this flow does not upload or record
footage. The model setup downloads a pinned, checksum-verified
[Google Face Landmarker model](https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker).

#### Adding cameras: supported now and the next geometry work

The runtime currently fuses **one IR eye camera and one explicitly selected head
webcam**. An external head camera can replace the built-in camera by device ID;
simultaneous stereo head tracking and a second IR eye are not implemented. Head
packets now identify their device and `camera_local` frame. Do not average poses
from different cameras as though they shared a coordinate frame.

A second desk-mounted webcam could improve head depth and reduce occlusion,
without adding a cable to the glasses. To obtain metric triangulation, both
views need synchronized corresponding landmarks, intrinsics/distortion
calibration, their relative transform, and a transform to the monitor plane.
Mounting a camera to the side by itself supplies none of those transforms.
This follows the requirements of OpenCV's
[stereo calibration and triangulation](https://docs.opencv.org/3.4.18/d9/d0c/group__calib3d.html).

A second IR camera could provide a second eye's gaze and improve resilience when
one pupil is obscured. Both eyes can be calibrated simultaneously while watching
the same targets in one procedure; the software learns a separate model for each
eye in a common head/screen frame. For a fixed monitor, intersect each calibrated eye ray with the known
screen plane and combine them by confidence; do not rely solely on the unstable
intersection of two noisy rays to infer depth. Binocular depth estimation is
ill-conditioned, as discussed in this
[gaze-on-3D-geometry paper](https://www.davidlindlbauer.com/docs/2015etvis_3Dgaze.pdf).

Suggested order: first validate this software change on held-out targets with
the head still, then repeat with head motion. If errors grow mainly with head
motion, investigate calibrated desk cameras before adding another glasses cable.
If single-eye pupil detection remains the dominant failure, investigate a second
IR eye. A small hub off the glasses can consolidate the host connection, but
does not eliminate the two camera leads or their bandwidth/power requirements.
No numeric accuracy improvement is promised without measurements of this rig.
Calibration-reference residuals are not a replacement for a separate
[accuracy validation](https://docs.pupil-labs.com/core/software/pupil-capture/#gaze-mapping-and-accuracy).

The center step has a 30-second timeout. The screen step ends after its single
7.8-second pass and either enables the initial cursor or stops with **Retry step 2**. Choose **Restart calibration**
from the menu to start over. Camera reconnection restarts the
fit. A delayed UI status response hides stale visual output without cancelling or
erasing calibration. Fresh gaze restores the desktop cursor automatically. The
menu and diagnostics distinguish incomplete/cancelled calibration, missing
tracking, and gaze outside the calibrated range. Phase transitions and their
messages are written to `.venv/eyecursor.log` to diagnose an interrupted attempt.
Hybrid fits are not saved for reuse yet. Anchor repeatability checks internal consistency; it is not an independent
measurement of real-world cursor accuracy.

The native app and backend must be updated together. An older copy in
`/Applications/EyeCursor.app` can otherwise render stationary corner targets while
the project backend records a moving path, invalidating their association. After
building `.venv/EyeCursor.app`, update the installed copy before launching it.

Use `--hybrid` to select this mode explicitly, or `--ir-only` to retain the previous
single-camera workflow described below. Video and legacy browser modes use IR-only
tracking.

### IR-only onboarding

Put on the glasses with the camera mounted and fixed relative to your eye. There
are no acceptance buttons or separate eye-model and monitor-calibration actions:

1. Follow the slowly moving dot above your normal desktop while keeping your
   head still. The target is a small transparent overlay above application
   windows, including full-screen apps. It does not darken the screen, take
   keyboard focus, or intercept mouse clicks. The original
   3DTracker estimator gathers pupil ellipses and estimates an eye center and
   radius. The dot animates locally at 60 Hz, independently of tracker/API updates.
   Its ring and percentage report collected evidence: clear pupil views, movement
   coverage, eye-center samples, and stability. A short message explains what is
   still missing in the menu and diagnostics. The desktop overlay shows only
   the dot and ring. Elapsed time alone does not advance the progress indicator.
   The app advances automatically once measurements cover both directions and
   the estimate is stable. The orbit stops after at most two rotations (about
   16.8 seconds); an incomplete estimate pauses instead of looping indefinitely.
2. Look at the five stationary targets on the main display: center and four
   corners. Each target collects a second of steady gaze. Its ring pauses through
   brief detection misses. The center is held out to check the corner mapping.
   The same visible dot travels smoothly from the orbit to the center and
   between corners in 0.55 seconds. Travel time is excluded from sampling.
3. After one five-point pass and a successful center check, the target overlay
   becomes the desktop eye cursor. A failed check pauses without repeating the pass.

The native app registers all connected displays using macOS logical-point
arrangement. Hybrid mode calibrates the laptop and extrapolates that map onto
external screens. The cursor passes through shared edges and sticks to the outer
outline, including offset edges and empty desktop gaps. External accuracy still
requires real-gaze validation; this is not independent calibration of each monitor.
Connecting, moving, or removing external displays preserves the laptop map.
Changing the calibration display or its logical size resets calibration.
The legacy non-hybrid workflow uses a separate mapping for each display; without
head-pose measurement, overlapping maps cannot identify the intended display.

The target is completion within a minute. A 60-second overall deadline stops an
incomplete attempt. **Restart calibration** starts a new attempt; failed or
cancelled attempts stay paused. Switching applications does not interrupt calibration.
Diagnostics can remain open alongside the target. After success, rejected or absent
eye detections hide the cursor but retain the mapping. A USB source reconnection
still restarts fitting, because the camera may have moved relative to the eye.

### Returning to a previous IR-only fit

A successful IR-only session saves the last eye model and display mappings locally in
`.venv/calibration-profile.json` with owner-only permissions. It saves numerical
parameters, not camera footage, and does not identify a person. Camera ID, flip
settings, eye search area, and display layout must match before reuse is considered.

The app first obtains a fresh eye estimate. If its center and radius are close to
the saved model, it checks three non-collinear targets per display instead of
collecting all five. The old mapping is used only after all checks pass. A failed
check automatically falls back to full five-point calibration. A different fit
starts full calibration directly. No screen coordinates are inferred by physical
3D triangulation; they come from the measured eye-to-display mapping.

### Eye camera diagnostics

**Eye camera diagnostics & 3D scene** in the menu, or **Cmd+D**, opens the combined diagnostics window.
In hybrid mode, the IR eye and webcam previews appear side by side and refresh
independently. The footer reports each processing rate. After calibration, cyan
lines connect detected webcam eyes to a small screen map; its dot and fading
trail show the combined calibrated estimate used by the desktop cursor, before
cursor smoothing. These are schematic connections, not measured 3D webcam rays.
Invalid paired samples, stale data, and monitor changes clear the trail. Eye-area
selection and the detection threshold belong to the IR panel only. The preview
publishes every processed frame and the native window requests images up to 30
FPS. Its footer reports measured tracking and preview-source FPS; these are not
camera-advertised rates or measured display-refresh rates. JPEG serving has a
separate lock so it does not wait for pupil detection to finish. Green is an
accepted pupil ellipse; red is a rejected candidate. The **Detection threshold**
slider adjusts acceptance from 0.20 to 0.95 (default 0.50) for tracking, model-ray
collection and model readiness. This is a detector quality score, not a calibrated
probability. The confidence label remains gray; only its numeric score changes
color. Brief rejected frames hold the previous green overlay for up to 0.25 seconds,
while the number continues to show the current raw confidence. Display hysteresis
keeps an acquired pupil green down to 0.08 below the threshold; an absent pupil or
a larger drop releases it after the brief grace interval. This does not lower the
threshold for calibration samples or clicks.
A thin muted teal ellipse traces the iris when enough enclosing boundary is visible.
Both side arcs must agree; edges whose gradient resembles an eyelid are rejected.
Once the iris is verified, the pupil is selected from grayscale edges **inside**
that iris, without searching for the darkest patch. The iris is normalized to a
unit circle; dark-to-light edge arcs inside it vote for a smaller circle. Mapping
back gives an inner ellipse with the iris's axis ratio and rotation, its own
radius, and a small independently fitted center offset. This is a conditional
image-space approximation, not an anatomical equality.

The fit requires distributed arcs, compatible edge-gradient directions, enclosure,
a darker pupil core relative to the iris, and boundary evidence in all four
directions. Reflections and bright halos are excluded. A dark rectangle, eyelid,
outer iris boundary, or a visible iris with no pupil cannot pass solely because
it is dark or because an ellipse can be drawn. Conflicting shapes are rejected
rather than forced into a detection.

On subsequent frames the last pupil only locates the outer iris search. The outer
boundary is verified again in the current image before searching its interior.
While that iris remains visible, missing pupil edges produce no detection and
cannot fall back to a dark blob. Loss of the outer boundary resets this guide.
Initial acquisition and reacquisition after iris loss still use the original
threshold seed to locate a candidate and discover its enclosing iris. Without a
strong iris, the existing threshold detector and conservative shape repair remain
available; this change does not implement independent whole-frame iris acquisition.

After each fit, `pupil_tracking.py` compares the candidate with up to five recent
reliable observations. It predicts center motion and checks major-axis size,
axis ratio, and orientation before updating gaze or calibration. Reliable iris
geometry compensates for camera translation, scale, and apparent shape changes;
nearly circular pupils do not receive an orientation check. Position has a wider
time-dependent allowance than size, so ordinary fast eye movement remains possible.
These bounds are tunable engineering defaults and still need live-camera validation.

A sudden half-size or double-size candidate is rejected. Its current ellipse
remains available for diagnostics with confidence zero, no gaze direction, and
`temporal_tracking: {accepted: false, reason: ...}`. It cannot update the eye model,
calibration, or blink-click detection as a missing pupil. The native panel reports
"Sudden pupil change rejected". Existing display grace can briefly hold the last
accepted outline/cursor, but held data is not used as a calibration observation.

Only candidates with a current-frame score of at least 0.60 update the temporal
history. A new geometry can replace it after at least three consistent reliable
observations spanning 80 ms (typically four frames at 30 FPS). Missing or weak
observations interrupt that confirmation; 350 ms without a trusted observation
expires the old history. Blinks never produce a predicted pupil. Resetting the
tracker clears history, and video playback uses frame timestamps rather than
processing speed. The predictor guides acceptance only; accepted pupil geometry
and confidence still come from the current image.

The edge fit feeds the diagnostic pupil outline and tracking/calibration. Its
confidence comes only from the current iris and pupil boundary evidence, capped
at 0.90; a high threshold-contour score cannot override a failed inner-edge fit.
The threshold slider still applies to calibration and display. The score is not
a calibrated probability, and physical camera accuracy needs live validation.

Tracking results retain `raw_pupil_ellipse`, `raw_pupil_confidence`,
`iris_pupil_confidence`, `pupil_shape_support`, and `pupil_shape_source` (`iris-edge`,
`iris-assisted`, or `pupil`). `pupil_edge_points` contains the accepted current-frame
boundary samples. When thresholding is skipped, the raw pupil is null and its score
is zero. The local `/state` response exposes score components under
`detection_evidence`; the camera preview labels the active iris edge fit.
Recalibrate existing saved gaze fits after updating because pupil geometry changes
their inputs.

The eye-sphere estimator runs in both native modes. IR-only calibration requires
it; hybrid mode fits it in parallel for diagnostic direction while using pupil
position and webcam head compensation for screen mapping.

The magenta cross is the darkest patch that seeds pupil detection. The cyan dot
and circle show the estimated eye center and adaptive radius. They are a model
based on pupil motion, not the visible iris boundary or a measured anatomical
outline. Do not reposition the camera to make the circle fit the iris.

The center estimator fits all recent reliable normals with robust outlier rejection,
instead of averaging random line intersections. Nearly circular ellipses, parallel
normals, insufficient motion and inconsistent fits cannot establish a center. Only
fresh successful fits advance eye-model readiness; repeatedly reusing old rays does
not count. Small IR reflection holes are closed without dilating the pupil boundary.
Old calibration profiles are invalidated after this model change.

In IR-only mode the model updates during the moving-dot stage and is fixed while
learning or using screen coordinates. Hybrid mode gathers it independently and
fixes it when its stability checks pass. Eye-model fitting requires samples above the selected threshold, motion in
both axes, at least 30 center estimates, a positive radius, and recent stability.
Those checks establish consistency, not anatomical accuracy. Model yaw and pitch
are camera-space estimates, not measured physical eye angles.

If a dark corner wins detection, drag around the visible eye to set an eye search
area. **Clear eye area** appears only after a custom area is selected and while
calibration is inactive; it restores the full frame. Changing the area discards the
current fit and rearms automatic onboarding. `--flip-horizontal` and
`--flip-vertical` correct an inverted camera mounting.

The Python process retains the local `/state` API on port 8765 so the recorder
can use the same calibration. `--no-calibration-ui` runs just the tracking/API
process (`--no-browser` remains an alias). `--web-calibration` explicitly opens
the legacy browser workflow for diagnostics. Finishing or cancelling calibration leaves EyeCursor in the menu bar. Choose
**Quit** from its menu-bar circle, or press Ctrl+C in the launching terminal,
to stop tracking and the eye-cursor.

To check the detector without camera access:

```bash
.venv/bin/python 3DTracker/monitor_demo.py --video eye_test.mp4 --no-display --max-frames 120
```

To check menu-bar startup with the sample video, run:

```bash
.venv/bin/python 3DTracker/monitor_demo.py --video eye_test.mp4 --loop-video --no-display
```

Video mode cannot calibrate a live user's screen.

### Optional desktop gaze cursor (macOS)

The native flow displays the eye-cursor after the selected display passes calibration;
there is no visibility setting. Use **Quit** to close it. The legacy browser mode still supports
`--debug-cursor`. The circle has a 16 logical-pixel diameter and
55% opacity, follows the calibrated estimate across desktop apps, ignores
clicks, and leaves the normal mouse pointer and keyboard focus alone.

The green screen-gaze arrow and desktop cursor share a conservative screen filter
in `screen_gaze.py`. A three-observation median removes isolated smaller spikes.
Moves larger than 10% in normalized screen distance require three consistent
camera observations spanning at least 50 ms, with agreement within 4.5% of screen
size. Repeated status polls never count as additional evidence. Confirmed moves
follow an 80 ms low-pass response; native rendering adds continuous 60 Hz easing
with a 70 ms critically damped response. These response constants are not total
latency: visible movement intentionally takes a few tenths of a second to settle.
Screen feedback cannot continue moving away from a new target on old momentum.
It does not extrapolate to a guessed future fixation.

Calibration, recorded gaze, and click targets retain the original coordinates.
The `/state` fields `gaze` and `desktop_gaze` contain the shared filtered feedback;
`raw_gaze` and `raw_desktop_gaze` preserve the unsmoothed estimates. The recorder
uses `raw_gaze`. While a jump is pending, feedback holds its accepted position for
up to 0.25 seconds, then hides if estimates remain inconsistent. A click is withheld
while confirmation is pending or the filtered position is more than 24 logical
pixels from the raw click destination. Holding and smoothing never add calibration
or fixation samples. Longer tracking loss clears the easing state so reacquiring
the eye does not sweep the dot across the screen from an old position. Live-camera
accuracy and comfort still require validation; smoothing cannot fix a wrong calibration. The
menu-bar icon has a strong black outline, a white eyeball, a black pupil, and a
white cursor. These colors stay fixed in light and dark menu bars.

The circle stays hidden during onboarding and until all display checks pass.
It disappears after sustained low confidence, stale frames, off-area estimates, or loss of
connection. Recalibrating clears the previous mapping. On Retina displays,
16 logical pixels correspond to 32 physical pixels at 2x scaling.

### IR diode control

The ineffective experimental diode toggle has been removed from both menus.
The connected USB camera (`0c45:6366`) advertises no AVFoundation torch or flash
control, and the toggle did not switch its IR LEDs during the user's test.
No verified alternative USB LED command has been identified for this board.
Further control requires the exact board's vendor protocol or a verified hardware
LED switching circuit. Separate left/right LED control is currently unavailable.

### Experimental double-blink left click

Turn on **Double-blink to click (experimental)** in the eye-cursor menu.
It is off by default. macOS Accessibility permission for EyeCursor is required
to deliver a mouse click; the app explains where to enable it if permission is
missing. The application is **EyeCursor**, at
`.venv/EyeCursor.app` inside this project. It is a native app bundle, but the `.venv`
folder is hidden in Finder. The permission dialog provides **Open Accessibility
Settings**, **Show EyeCursor in Finder**, and the exact app path. In the Accessibility
`+` file picker, press Shift-Command-G and paste that path to select it. Enable
EyeCursor, return to its menu, and turn on double-blink clicking again.
“Pupil-loss” below describes the detection method, not an application to install.
Calibration and cursor display do not need that permission.

A gesture is armed only after one second of fixation within a 24 logical-pixel
radius. It requires two short pupil-loss intervals (80–350 ms each), with an
80–600 ms open interval between them, followed by 150 ms of gaze at the same
location. It produces one left click at that fixation, then enforces a cooldown.
Moving gaze, low confidence with a visible pupil, prolonged loss, or interrupted
frames cancels the sequence. Clicking is disabled during calibration, while the
cursor is hidden, in sample-video mode, and while its menu is open. Intentional
clicks may move the normal mouse pointer to the gaze location.

This is a pupil-loss heuristic, not an eyelid-closure classifier: repeated camera
occlusion can still resemble blinks. Timing and false positives must be tested
with the mounted IR camera before relying on it. Automated tests exercise gesture
events without posting real OS mouse input.

### Wireless eye-camera input

The same monitor demo can accept a live HTTP MJPEG or RTSP stream from a
battery-powered camera transmitter on the same network:

```bash
.venv/bin/python 3DTracker/monitor_demo.py --stream-url http://PI_ADDRESS:PORT/stream
```

Replace the example URL with the transmitter's actual stream URL. Unlike
`--video`, this is a live camera source, so native calibration remains usable.
The Mac receives decoded video frames, not the original USB device. The USB
eye camera still needs a powered USB host on the glasses or in a pocket to
capture and transmit its video. The transmitter, camera format, battery life,
Wi-Fi stability, and end-to-end latency must be checked on the actual hardware.

### Local screen, gaze, and cursor sessions

After calibrating with the eye camera, compile the macOS ScreenCaptureKit helper
and start the separate local recorder in another terminal:

```bash
CLANG_MODULE_CACHE_PATH=.venv/swift-cache SWIFT_MODULE_CACHE_PATH=.venv/swift-cache \
  /usr/bin/swiftc -parse-as-library -module-cache-path .venv/swift-cache \
  3DTracker/screen_recorder.swift -o .venv/bin/eyetracker-screen-recorder
.venv/bin/python 3DTracker/session_recorder.py
```

Open `http://127.0.0.1:8766/`, select the same display used for calibration,
and use **Start recording** and **Stop**. macOS may request Screen Recording
permission the first time; allow it for the launching application and rerun the
recorder if prompted. Each session is kept locally under `recordings/SESSION_ID/`:

- `screen.mp4`: display video, with a requested maximum capture rate of 24 fps
- `frames.jsonl`: capture frame times and cursor position on that display
- `gaze.jsonl`: eye predictions and confidence polled at 24 Hz
- `session.json`: selected display, source, timing, and counts
- `tracking.json`: compact coordinate groups for analysis and replay

`tracking.json` uses a fixed 24 Hz timeline. Each group holds up to 24 gaze
points and 24 cursor points. A point is `[x,y]` in normalized display
coordinates; `null` means no valid point at that instant. Each group's `utc`
is an absolute UTC time and `video_ms` is its position in the MP4 timeline.
The player decodes sample `i` in a group at `video_ms + i * 1000 / 24`.
For example:

```json
{"schema":"eyetracker.tracking.v2","sample_hz":24,"group_size":24,"groups":[{"utc":"2026-10-05T10:00:00.000Z","video_ms":0,"gaze_xy":[[0.42,0.58],null],"cursor_xy":[[0.51,0.44],[0.52,0.44]]}]}
```

The actual MP4 can have variable frame timing. `video_ms` anchors the groups
to playback time, while `frames.jsonl` retains the individual captured frame
times for precise diagnostics. `gaze.jsonl` retains the original eye samples
and their confidence. The compact JSON is the file intended for normal export
and heatmap review; the raw JSONL files provide exact timing if needed.

The session page replays the video with gaze and cursor marks and an optional
heatmap accumulated through the current playback time. It uses local HTTP only
and records no audio. Actual video frame cadence depends on ScreenCaptureKit
and on-screen changes; inspect `frames.jsonl` for measured frame timing. Gaze
positions are estimates from the four-point mapping and may be absent when
confidence is low. Keep the camera and seating position fixed after calibration.

Native cursor lifecycle regression (macOS, no camera access):
`./.venv/bin/python 3DTracker/tests/native_calibration/run.py`

Head-calibration investigation: `/state` includes `head_camera.pairing` (latest
capture-return timestamp offset and counts for the last 300 pairing attempts)
and `onboarding.head_diagnostics` (accepted/rejected samples, duplicate head
samples, fit-error counts, observed motion ranges and validation residuals).
These timestamps do not measure the cameras' hardware exposure synchronization.
A transient sample rejection does not erase the last failed model-fit reason.
On head-stage completion or timeout, `.venv/head-calibration-debug.json` saves
one local numeric attempt, including paired pupil/head features for replay. It
contains no video/images and is replaced by the next report. Unit tests do not
write production diagnostic reports. Pairing limits and fit acceptance thresholds
have not been relaxed for this instrumentation.

### Full-window 3D angle debugger

Choose **Eye camera diagnostics & 3D scene** in the EyeCursor
menu, or press **Command-D**. This opens the resizable window
on the calibration display (the laptop in hybrid mode), with compact 240×180
camera previews on the left and the scene in the center. The right sidebar
starts with **Reset laboratory**, followed by calibration steps and angle
controls. The window supports macOS full screen.
Its translucent monochrome scene shows a fixed
screen and webcam, one relative head outline, and two equally sized eyes placed
symmetrically at the same local height. The left eye is a reference, not a second
IR measurement.

- Drag to orbit and scroll to zoom. The full head and both eyes stay visible.
- **Connected displays** lists monitors from macOS with their names and desktop
  arrangement. Select an external display to adjust its yaw, tilt, roll, horizontal
  offset, and depth.
  These scene poses persist per display until **Reset laboratory**. The laptop
  stays fixed as the calibration reference, with a passive keyboard/trackpad base.
  Display sizes are proportional to logical desktop points, not measured physical
  sizes. The green gaze marker follows the corresponding monitor in the scene.
- Blue rays use each webcam iris direction independently, transformed by the
  head pose. Blue dots show their intersections with the screen plane, including
  outside the screen edges. They never follow the calibration target or force
  the two eyes to converge. These webcam estimates are not calibrated screen gaze.
- When tracking drops out, the 3D preview holds the last displayed head pose
  and eye directions until measurements return. It waits for the first head
  detection instead of showing a default pose. Held geometry is display-only;
  invalid calibrated gaze still disappears and contributes no tracking samples.
- IR status and the compact detection-threshold slider sit below the IR video.
  Completed calibration shows only "Calibration complete". Pupil-fit details
  and changing rejection messages are hidden; FPS and confidence remain visible.
  A fixed status row keeps both videos steady between measurements.
- Drag the vertical divider beside the camera column to resize it. Both videos
  grow proportionally. Collapse/Expand in the scene toggles the right controls
  sidebar while the build version stays fixed at the bottom-right.
- The dashed ray points toward the current calibration target, or the manual
  target sliders. The solid ray uses the adjusted IR estimate. Numerical readouts
  show their angular difference and plane miss alongside the scene.
  An off-screen intersection is reported without clamping.
- Adjust assumed screen size, head distance/position, eye spacing, right-eye
  center in centimetres, and mounting yaw/pitch/roll. Both eyeballs use the same
  assumed 1.2 cm radius without visual enlargement. Head distance defaults to
  30 cm. Webcam yaw preserves the direction of head turns in the scene.
- **Fitted center X/Y (px)** reprojects the detected pupil with an offset center
  using the existing tracker's 640x480, 45-degree heuristic sphere projection.
  This isolates center-fit errors from camera mounting and world placement.
- **Use current head / eye as neutral** captures a temporary reference from a
  paired sample. **Reset laboratory** clears it and all adjustments.
- The laboratory always uses live input. An accepted IR eye model and paired
  webcam pose are required to draw the IR direction. Missing or stale samples
  hide the corresponding estimate.

External monitor poses and laboratory adjustments are saved across app launches. They do
not modify the tracker, collect calibration samples, or change the cursor map.
Depth is inferred from apparent face size, and screen dimensions, field of view,
and camera mounting are assumptions. This is an angle-model
laboratory, not metric triangulation or independent gaze-accuracy validation.

The scene uses a right-handed, screen-attached frame: +X to the wearer's right,
+Y toward the screen top, +Z out toward the wearer; the display plane is Z=0.
The unmirrored [MediaPipe camera frame](https://github.com/google-ai-edge/mediapipe/wiki/MediaPipe-Face-Mesh)
looks along -Z, with +X to image-right and +Y up. Its conversion to the screen
frame is the proper rotation `C = Ry(pi)`, not an arbitrary axis reflection.
The pose extractor's Euler convention is `R_camera = Rz(roll) Ry(yaw) Rx(pitch)`.
The scene uses `R_head = R_mount C R_camera C^-1`; relative rotations, where
needed, are products `R_current R_reference^-1`, not subtracted Euler angles.
Capturing neutral does not straighten an actually rotated head.

For normalized eye midpoint `(u,v)` and estimated optical depth `d`, pinhole
backprojection is `P_camera = ((u-.5)d/fx, (.5-v)d/fy, -d)`, with
`fy=.5/tan(verticalFOV/2)` and `fx=fy/imageAspect`. Then
`P_screen = cameraOrigin + R_mount C P_camera`. The eye midpoint is not the
skull center: the head and two eye origins are placed around that measured
midpoint using the assumed local offsets/IPD. A reference ray is
`D = normalize(B-A)` and its plane intersection is `A + (-A.z/D.z)D` when
forward-facing. Captured A and target B are distinct from the current live A'.

For a webcam rigidly attached to the laptop lid, tilting the lid in the room
rotates camera and display together, so the screen-attached transform does not
need the hinge angle. The lens's mounting pitch relative to the screen is a
separate explicit parameter. The current model does not estimate lens intrinsics,
distortion, anatomical eye centers, or absolute depth from verified measurements.
These scene formulas clarify coordinates; they do not convert the empirical
IR/head-to-screen fit into a physically calibrated gaze tracker.

The scene uses smooth silhouettes for head and eye outlines, with all labels kept
in the sidebar. Pupil detection also checks for broad reflections that reverse
contrast at the pupil boundary. When both ordinary and reversed edges support a
complete ellipse, diagnostics report **Pupil: reflection edge fit**. This fit uses
the visible boundary rather than the narrower dark patch inside it; it retains
an elliptical shape and still requires a dark core, a measured enclosing iris,
and distributed current-frame edge support. Blinks and unsupported glare remain
rejected. The previous iris guides only the next frame's search, never its output.
For local image debugging, `/diagnostics/raw.png` provides an unannotated frame
while the eye camera is fresh, without continuously encoding an additional feed.


### Standalone system-cursor calibration and numeric audit

In Diagnostics, **Calibrate with system cursor** can replace a running or failed
guided step. With no existing map, keep your head comfortable and steady and look
at the stationary mouse until the checkmark. The first hold also establishes the
head reference. Save at least six distinct positions spanning left/right and
top/bottom. Once the fit is usable, **Finish cursor alignment** saves it for the
current run and shows the EyeCursor. Existing maps can be refined from one or
more explicit cursor fixations. Ordinary mouse use does not train the model.

Numeric evidence is stored locally under `.venv/calibration-sessions/`:

- `<session>.jsonl`: every accepted paired calibration measurement, including its
  original eye/head/target values and capture time.
- `<session>.events.jsonl`: a versioned audit with UTC write time and monotonic
  capture time, starting build identity, camera IDs, displays, threshold settings,
  head and gaze model snapshots, fixation outcomes, and sampled decision inputs.
  Context IDs link each measurement/event to immutable model parameters. Decision
  observations are sampled at 10 Hz; accepted measurement records are uncapped.

The beam entry uses screen-width units and records the predicted geometric ray
only when a fitted geometric model exists. Empirical cursor calibration has no
measured physical eye origin: those ray fields are null, with the raw head pose,
IR coordinates, target, and mapping retained instead. Scene-only slider settings
are not the calibration model and are not replayed by this log. Accepted samples
are evidence, not proof that a model passed validation. No video/images are saved
in these files. Restarting or recalibrating creates a new session and keeps old
files. Logs are not automatically loaded into the active calibration.

Inspect an audit without changing any live fit:

```sh
.venv/bin/python 3DTracker/calibration_log.py /path/to/session.events.jsonl
```

This reports logged outcomes and rejection reasons; it does not claim an
independent physical accuracy measurement or replay the old calibration.

### Independent screen accuracy check

The hybrid quick pass now requires a contiguous stable pupil capture at each
corner. A blink, rejected frame, capture gap, jump or excessive pupil spread
restarts that corner's capture; completed corners are retained on a timeout retry.
Stability measures sample quality, not whether the wearer looked at the right dot.

After the five-point fit, five new target positions measure the frozen mapping.
The gaze cursor is hidden during this check. Check samples never train the map.
Diagnostics shows check targets directly on the 3D laptop screen: filled green
markers are measured, hollow rings are pending, and crosses are missing. Orange
dots show median estimates. The calibration controls on the right show mean and
worst target error in macOS screen points. IR eye remains the first camera section. Each target error
is the mean distance of its raw predictions from the target, with screen aspect
ratio accounted for. Jitter is recorded separately as RMS distance from the median.
Off-screen predictions retain their full error, although the laptop display draws them at
its edge. Missing targets are marked missing; an incomplete check is not a pass.

Use **Check accuracy** in the right-side calibration controls to repeat after cursor alignment or head
refinement. Starting either refinement clears the old accuracy report. Stopping
the accuracy check preserves the existing mapping and marks the report incomplete.
The report is an accuracy measurement, not an automatic claim of usable cursor
precision. Session audit logs include completed or interrupted check results.


### Rotation and translation calibration

The webcam scale feature now corrects projected cheek width for head rotation and
camera aspect ratio. A yaw turn or roll at constant distance should not be treated
as moving farther from the screen. This is a weak-perspective face-width estimate,
not a measured absolute depth; near-profile faces are rejected for this purpose.
New logs identify the feature convention as `rotation_corrected_face_scale_v1`.
Do not mix earlier raw-face-width logs into these fits without reprocessing them.

**Calibrate head movement at fixed dot** accepts the current manual cursor map's
saved anchors as well as guided calibration anchors. While looking at the same
fixed dot, gently turn first, then slide sideways with the face pointing forward.
The subsequent fresh-data check repeats both hints. Training and checking report
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
