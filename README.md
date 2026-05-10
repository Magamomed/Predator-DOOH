# Predator DOOH

Реалтайм-система в стиле Predator для DOOH-экранов: детекция лиц, трекинг целей, тепловая цветокоррекция, динамический HUD и звуковые эффекты.

## Возможности

- Детектирует лица в видеопотоке с камеры (`MediaPipe Face Detection`)
- Ведет несколько целей с логикой состояний захвата
- Рисует анимированный треугольный HUD и эффект схождения лазеров
- Применяет холодно-теплый "термо" стиль с опциональной сегментацией человека
- Воспроизводит фоновый звук и звук детекции (`pygame`)
- Поддерживает kiosk/fullscreen режим на Linux (`wmctrl`, `xdotool`, `xrandr`)

## Структура проекта

```text
.
|-- winterpredator.py         # основной скрипт
|-- requirements.txt          # Python-зависимости
`-- strekotanie-hischnika.mp3 # пример аудиофайла
```

## Требования

- Python 3.10+
- Linux desktop (рекомендуется для kiosk-режима)
- USB-камера
- Системные утилиты для kiosk-режима:
  - `xrandr`
  - `wmctrl`
  - `xdotool`

Установка системных пакетов (Ubuntu/Debian):

```bash
sudo apt update
sudo apt install -y python3-venv ffmpeg wmctrl xdotool x11-xserver-utils
```

## Быстрый старт

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python winterpredator.py
```

Примечание для Windows:
- Основной рендер и детекция работают, но kiosk-утилиты (`wmctrl`, `xdotool`, `xrandr`) Linux-специфичны.

## Конфигурация (ENV)

Доступные переменные окружения:

- `PREDATOR_LOG_DIR` (по умолчанию: `/var/log/predator`)
- `DETECT_SHOT_PATH` (по умолчанию: `/home/predator/predator/short-lasenr.mp3`)
- `PROMO_PATH` (по умолчанию: `/home/predator/predator/promo.png`)
- `PROMO_MODE` (по умолчанию: `fill_width`)
- `PROMO_WIDTH_FRAC` (по умолчанию: `0.90`)
- `PROMO_WIDTH_PX` (по умолчанию: `450`)
- `PROMO_MAX_H_FRAC` (по умолчанию: `0.90`)
- `PROMO_OPACITY` (по умолчанию: `1.0`)
- `PROMO_BOTTOM` (по умолчанию: `5`)
- `PROMO_SIDE` (по умолчанию: `5`)

Пример:

```bash
export PREDATOR_LOG_DIR="$HOME/predator/logs"
export PROMO_PATH="$HOME/predator/assets/promo.png"
export DETECT_SHOT_PATH="$HOME/predator/assets/shot.mp3"
python winterpredator.py
```

## Звук

- Путь к фоновой музыке сейчас зафиксирован в коде:
  - `/home/predator/predator/predator.mp3`
- Звук выстрела/детекции можно переопределить через `DETECT_SHOT_PATH`.

Если нужно, положите фоновый трек по пути выше или измените `SOUND_FILE` в `winterpredator.py`.

## Логи

Приложение пишет логи в:

- `$PREDATOR_LOG_DIR/app.log` (или в fallback-путь, если нет прав)

## Диагностика проблем

- Черный экран или нет камеры:
  - Проверьте индекс камеры в `winterpredator.py` (`USB_CAMERA_INDEX`)
  - Быстрый тест камеры: `python -c "import cv2;print(cv2.VideoCapture(0).isOpened())"`
- Не работает fullscreen/kiosk:
  - Убедитесь, что установлены `wmctrl`, `xdotool`, `xrandr` и активна X11-сессия
- Нет звука:
  - Проверьте аудиобэкенд и пути к аудиофайлам

