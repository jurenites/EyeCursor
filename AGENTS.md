# EyeCursor delivery and versioning

These instructions apply to every chat working in this project.

- Version numbers start at v0.1 and increase the second integer without a fixed
  limit: v0.2, v0.3, ..., v0.10. Do not treat the version as a decimal number.
- After completing project changes, build with:
  `.venv/bin/python -c 'import sys; sys.path.insert(0,"3DTracker"); from monitor_demo import build_native_helper; print(build_native_helper("native_calibration"))'`
- The build automatically increments `version.json` when source, tests, assets,
  or project instructions change. Unchanged builds keep the same version. Do not
  hand-edit or reset the version or its source fingerprint. The build lock
  coordinates simultaneous chats; if files change during a build, retry it.
- Run relevant checks before the final build. If further edits are needed, build
  again. Preserve changes from other chats.
- Update the existing `/Applications/EyeCursor.app` from the verified build when
  delivering app changes, following filesystem permissions. Verify the installed
  version and executable match. Do not interrupt a running calibration to restart
  the app unless the user asks.
- In the final reply for every project change, read and report the latest
  `version.json` version. State whether the Applications copy was updated and
  whether reopening is needed. Never claim the running app was updated merely
  because a newer app was installed.
- The visible version must identify the launched build. Keep its label pinned
  outside scrolling content at the diagnostics window's bottom-right, and include
  the same version in the menu-bar dropdown.

# Dropdown width guardrails

- Keep the menu-bar dropdown compact and sized to its current concise option
  labels plus native menu padding. Never maximize, stretch, or give it a large
  fixed/minimum width, and never size it to the screen or diagnostics window.
- Long status, error, progress, device, or explanatory text must not widen the
  dropdown. Truncate display text with an ellipsis and preserve the full text in
  a tooltip or diagnostics. Keep action labels short; put instructions elsewhere.
- Preserve `fitMenuStatusToActions()` and its call after menu title updates in
  `3DTracker/native_calibration.swift`. Check every visible menu item, including
  disabled items and new actions, since any one title can expand an `NSMenu`.
- Truncate dynamic text before assigning `NSMenuItem.title`; never briefly assign
  the full message and shorten it afterward. AppKit can retain that intermediate
  width while the menu is open. Regression checks must observe title mutations
  and actual native menu width, not just the final displayed string.
- Before delivering a menu change, run the existing native lifecycle checks and
  cover any new source of long text in their width assertions. Inspect the opened
  menu with normal and long/error text when runtime verification is available.
  Do not claim visual verification from a build or installation alone.
- Treat unexpected dropdown widening as a regression. Do not relax truncation,
  lengthen action labels with explanatory prose, or increase the menu width to
  accommodate a new feature unless the user explicitly requests a wider menu.
