# UI Specification

## Product Positioning

This is an operational desktop control panel for a Dobot vision-guided robot system. The UI should prioritize safety, scanability, clear status, and repeatable operation over decorative presentation.

## Page Structure

- Main window: `DobotMainWindow` with a status summary area, tab widget, and status bar.
- Main control tab: robot IP, connect/enable/disable, camera connect/disconnect, run grasp task, collision level, clear error, pause/resume.
- Parameter/settings tab: photo position and runtime configuration controls.
- Motion/grasp-flow tab: point management, module selection, module parameter editing, ordered flow steps.
- Jog control tab: coordinate/joint jog controls and current/target pose displays.
- Hand-eye calibration tab: D435i/D405 calibration matrix view and save/reset/refresh actions.
- Camera test tab: D435i/D405 test controls, image preview, coordinate details, D405 endpoint details, D435i low-FPS recognition.
- Modbus and force-control sections are present through mixins and should remain grouped by task.

## Interaction Flow

1. Enter or confirm robot IP.
2. Connect robot.
3. Enable robot only after connection succeeds and safety state is known.
4. Connect D435i and/or D405 camera.
5. Verify detection in camera test view.
6. Confirm calibration/points and grasp-flow modules.
7. Run grasp task.
8. Use pause/resume or clear error when the system state requires it.
9. Disconnect or close the app, allowing workers and hardware resources to stop cleanly.

## Design System

The current design system lives in `dobot_move/ui_theme.py`:

- `GLOBAL_STYLESHEET` defines most widget styles.
- `build_app_palette()` and `apply_app_palette()` set the app palette.
- `set_button_role()` assigns semantic button roles.
- `apply_status_visual()` maps status text to visual states.
- `FLOW_STEP_STYLE`, `FLOW_STEP_SELECTED_STYLE`, and `FLOW_STEP_EMPTY_STYLE` style flow-step labels.

## Colors

Current dominant palette:

- Window background: `#f0f8ff`
- Surface: `white`
- Primary text: `#1a237e`
- Primary action: `#1565c0`, hover `#0d47a1`
- Connect/success action: `#e8f5e9`, text `#1b5e20`, border `#66bb6a`
- Warning action: `#fff7ed`, text `#9a3412`, border `#fb923c`
- Danger action: `#fee2e2`, text `#991b1b`, border `#f87171`
- Secondary action: `#f8fafc`, text `#334155`, border `#cbd5e1`

TODO: Reduce the one-note blue dominance over time while preserving operational clarity.

## Typography

- Global font: `Segoe UI`, `Arial`, sans-serif.
- Global size: `10pt`.
- Status and numeric coordinate labels may use monospace where dense values need alignment.
- Avoid oversized headings inside operational panels.

## Spacing

- Main layout margins are currently `10px`.
- Group and button layout spacing is generally `10px`.
- Table item padding is `4px`.
- Buttons use `8px 16px` padding.

## Radius

- Inputs and status labels: `4px`.
- Flow labels: `5px`.
- Buttons: `6px`.
- Group boxes, tabs, and message boxes: `8px`.

## Buttons

- Use semantic roles instead of ad hoc styles:
  - `primary`: run grasp task and main execution commands.
  - `connect`: connect, enable, continue.
  - `warning`: pause, disable.
  - `danger`: clear error or destructive/safety-critical actions.
  - `secondary`: support actions such as refresh, get pose, disconnect.
- Disabled buttons must remain visibly disabled.
- Motion and hardware actions should be disabled when robot/camera state does not permit them.

## Inputs

- Robot IP input should stay compact and validate before connection attempts.
- Numeric pose inputs should use `QDoubleSpinBox` with explicit ranges and units in nearby labels where possible.
- Combo boxes should use meaningful, stable option order for collision level, camera type, coordinate system, and module type.

## Tables

- Point tables should keep point name fixed-width and coordinate columns stretchable.
- Use alternating rows for scanability.
- Preserve enough row height for coordinate readability.
- Avoid direct editing that bypasses validation or point resolution rules.

## Cards

This is a PyQt desktop app, so use `QGroupBox` as the main section container. Avoid nested card-like group boxes unless the UI needs a clear safety or data boundary.

## Dialogs

- Use dialogs for confirmation, warnings, calibration reset, and unrecoverable errors.
- Safety-critical confirmations should include the target device/action and consequences.
- Do not hide hardware failures behind generic success/failure messages.

## Status, Toast, and Log

- Status labels use `apply_status_visual()`.
- The status bar should show short current activity messages.
- Long-running flows should emit logs through worker signals.
- Error logs should include enough hardware context to diagnose robot/camera/network state.
- TODO: Normalize status text matching so visual state does not depend on mojibake-corrupted Chinese strings.

## Suggested UI Directories

The project contains UI and would benefit from future organization, but existing files should not be moved without an explicit refactor request:

- `ui/`
- `components/`
- `pages/`
- `styles/`
- `resources/`

For this Python/PyQt project, a less disruptive first step is to create `dobot_move/ui/` with widgets, panels, and style helpers after extracting more code from `gui_app.py`.
