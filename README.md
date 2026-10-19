# EyeCursor

EyeCursor is our native macOS gaze-cursor application, built on top of the
open-source [EyeTracker library by JEOresearch](https://github.com/JEOresearch/EyeTracker).
It combines a glasses-mounted IR camera with the laptop webcam for head-aware
calibration and a smooth eye-cursor. It also provides an IR-only mode, menu-bar
controls, and local recording/replay tools. See [setup and usage](3DTracker/readme.md#native-macos-calibration).

Native USB mode now has independent left/right camera assignments in
**Diagnostics → Camera setup**. The left eye defaults to a 180° rotation; the
right eye defaults to 0°. Rotation is applied before detection and preview.
Assignments and orientation are saved locally in `.venv/eye-cameras.json`.
Both assigned cameras run pupil detection independently, with separate temporal
histories, confidence, frame rates and annotated previews. The fixed left/right
previews sit close together above the camera and tracking controls; no tracking
tabs are needed. Identical camera models have numbered picker options and full
USB identifiers in tooltips. An open picker is not rebuilt by status polling.

The existing screen calibration and 3D view still use the previously configured
calibration eye (left by default), identified below Camera setup. This is dual-eye
detection, not a binocular screen calibration: the two camera rays are not
averaged. Changing that camera or its rotation resets its calibration; changing
the other camera resets only its detector. Disconnecting either eye does not
substitute the other camera, and the remaining eye continues detecting.

If changing USB ports changes a camera's macOS ID, assign it again in Camera
setup. Explicit `--camera`/`--camera-id`, video and wireless inputs retain their
existing single-camera workflow.

The original tracker code, attribution, and [license](LICENSE) are retained.

The app icon's editable source is [`assets/app-icon/eye-cursor.svg`](assets/app-icon/eye-cursor.svg).
After editing it, run `.venv/bin/python assets/app-icon/build.py` on macOS to rebuild
the transparent PNG and ICNS. The launcher copies the ICNS into `EyeCursor.app`
on each launch.
The black-and-white menu-bar icon is `assets/app-icon/eye-cursor-menubar.svg`.
After setup, double-click `.venv/EyeCursor.app` to start the tracker and open
diagnostics. Choose **Quit** from its menu to stop it.

The launched build's version is shown at the bottom-right of diagnostics and in
the menu-bar dropdown. Versions start at **v0.1** and increase automatically for
changed builds, including v0.10 after v0.9. An unchanged rebuild keeps its number.
`version.json` records the latest successfully built version; `AGENTS.md` contains
the shared delivery instructions for all project chats. Reopen the app after an
update to run the new version. A running app keeps displaying its original version.

## Upstream EyeTracker
A lightweight, robust 3D eye tracker in Python

This repository is an open-source 3D eye tracking algorithm written in Python. Currently, it is an updated version of the pupil tracker from https://github.com/YutaItoh/3D-Eye-Tracker/blob/master/main/pupilFitter.h that has been optimized, simplified, and improved upon. 

To use the script, run "python .\OrloskyPupilDetector.py" from your shell. If the hardcoded file path in the select_video() function does not find a video at the specified path, it will open a browse window that allows you to select a video. The process_video() function handles the majority of the processing and can be easily modified to work with a camera capture or image. It returns a rotated_rect that represents the pupil ellipse. A lite version is also included that is more efficient, but less robust. Be sure to have an adequate light source for the lite version. 

A test video (eye_test.mp4) is included in the root directory for testing. Algorithm details are explained here: https://www.youtube.com/watch?v=bL92JUBG8xw

When running the script on this test video, your results should look like this: https://youtu.be/B06cUMplDHw.  

If you need an eye camera with custome LEDs, I have instructions for building your own IR camera for under $100 here: https://www.youtube.com/watch?v=8lZqCMRMtC8
Alternatively, there is a small $17 IR camera that works well with some modification: https://amzn.to/41x8p2W

To help support this software and other open-source projects, please consider subscribing to my YouTube channel: https://www.youtube.com/@jeoresearch, or joining for $1 per month: https://www.youtube.com/@jeoresearch/join. 

Other useful tools/supplies 
- GC0308 Camera (~$20): https://amzn.to/41x8p2W (price may vary)
- LEDs for Spinel ($8): https://amzn.to/41rEwAS
- USB Extension cable x2 ($8): https://amzn.to/4knyf1N (for extending GC0308 cable)

As an Amazon Associate, I earn from qualifying purchases at no extra cost to you.  

Requirements:
- A Python environment

Packages
- numpy ****There is a known issue with numpy 2.0.0. Downgrading to 1.26.0 or another version can solve this issue.
- opencv

Assumptions
- Works best with 640x480 videos. Images will be cropped to size equally horizontally/vertically if aspect ratio is not 4:3.
- The image must be that of the entire eye. Dark regions in the corners of the image (e.g. VR display lens borders) should be cropped. 
