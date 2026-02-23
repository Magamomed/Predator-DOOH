# Predator DOOH

Realtime "Predator-style" visual system for DOOH screens: face detection, target tracking, thermal-like color grading, dynamic HUD overlay, and sound effects.

## What It Does

- Detects faces in live camera stream (`MediaPipe Face Detection`)
- Tracks multiple targets with lock state machine
- Renders animated triangular targeting HUD + laser convergence effect
- Applies cold/warm thermal-like look with optional person segmentation
- Plays ambient and detection sounds (`pygame`)
- Supports kiosk/fullscreen behavior on Linux (`wmctrl`, `xdotool`, `xrandr`)

## Project Structure

```text
.
|-- winterpredator.py         # main app
|-- requirements.txt          # Python dependencies
`-- strekotanie-hischnika.mp3 # sample audio asset
```

## Requirements

- Python 3.10+
- Linux desktop environment (recommended for kiosk mode)
- USB camera
- System tools for kiosk mode:
  - `xrandr`
  - `wmctrl`
  - `xdotool`

Install system packages (Ubuntu/Debian):

```bash
sudo apt update
sudo apt install -y python3-venv ffmpeg wmctrl xdotool x11-xserver-utils
```

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python winterpredator.py
```

Windows note:
- Core rendering/detection works, but kiosk utilities (`wmctrl`, `xdotool`, `xrandr`) are Linux-specific.

## Configuration (ENV)

Available environment variables:

- `PREDATOR_LOG_DIR` (default: `/var/log/predator`)
- `DETECT_SHOT_PATH` (default: `/home/predator/predator/short-lasenr.mp3`)
- `PROMO_PATH` (default: `/home/predator/predator/promo.png`)
- `PROMO_MODE` (default: `fill_width`)
- `PROMO_WIDTH_FRAC` (default: `0.90`)
- `PROMO_WIDTH_PX` (default: `450`)
- `PROMO_MAX_H_FRAC` (default: `0.90`)
- `PROMO_OPACITY` (default: `1.0`)
- `PROMO_BOTTOM` (default: `5`)
- `PROMO_SIDE` (default: `5`)

Example:

```bash
export PREDATOR_LOG_DIR="$HOME/predator/logs"
export PROMO_PATH="$HOME/predator/assets/promo.png"
export DETECT_SHOT_PATH="$HOME/predator/assets/shot.mp3"
python winterpredator.py
```

## Audio Notes

- Background music path is currently hardcoded in code:
  - `/home/predator/predator/predator.mp3`
- Detection sound supports override via `DETECT_SHOT_PATH`.

If needed, place your ambient track at the hardcoded path or update `SOUND_FILE` in `winterpredator.py`.

## Runtime Logs

App writes logs to:

- `$PREDATOR_LOG_DIR/app.log` (or fallback path if no permissions)

## Troubleshooting

- Black screen / no camera:
  - Check camera index in `winterpredator.py` (`USB_CAMERA_INDEX`)
  - Test webcam quickly: `python -c "import cv2;print(cv2.VideoCapture(0).isOpened())"`
- No fullscreen/kiosk behavior:
  - Ensure `wmctrl`, `xdotool`, `xrandr` are installed and X11 session is active
- No sound:
  - Verify audio backend and file paths for ambient/detection sounds

## License

No license file is included yet. Add one before public/commercial distribution.
