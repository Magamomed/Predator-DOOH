#!/usr/bin/env python3
# predator.py - PRODUCTION 24/7 VERSION with failsafe mechanisms

import cv2, mediapipe as mp, numpy as np, time, random, os, math, subprocess, sys, threading
import traceback, gc, logging
from collections import deque
from datetime import datetime

# ================== LOGGING SETUP ==================
LOG_DIR = os.environ.get("PREDATOR_LOG_DIR", "/var/log/predator")
try:
    os.makedirs(LOG_DIR, exist_ok=True)
except PermissionError:
    # fallback to local logs inside home dir
    home_log = os.path.expanduser("~/predator/logs")
    try:
        os.makedirs(home_log, exist_ok=True)
        LOG_DIR = home_log
    except Exception:
        # окончательный fallback — текущая директория
        LOG_DIR = "."
#os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(f"{LOG_DIR}/app.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ================== КОНФИГУРАЦИЯ ==================
MAX_TARGETS = 4
LOCK_REQUIRED_STABLE_SEC = 5.0
LOCK_LOST_GRACE_SEC = 0.8
SMOOTH_K = 0.85
FORCE_UNMIRROR_USB = True
BG_COLD_COLORMAP = cv2.COLORMAP_OCEAN
WARM_BASE_COLORMAP = cv2.COLORMAP_HOT
ALPHA_WARM_IN_MASK = 1.00
BG_DARKEN_ALPHA = 0.75
BG_DARKEN_BETA = -35
USE_SEGMENTATION = True
SEG_THRESH = 0.35
SEG_DOWNSCALE = 0.2
TRI_COLOR_TRACKING = (0, 255, 0)
TRI_COLOR_LOCKED = (60, 255, 60)
TRI_GLOW_RADIUS = 12
TRI_OUT_THICK = 1
TRI_DASH_LEN_PX = 8
TRI_GAP_LEN_PX = 6
TRI_BUILD_TIME = 0.60
TRI_SPAWN_TIME = 0.90
TRI_SPAWN_EASING = "ease_out_cubic"
LASER_COLOR = (0, 255, 0)
LASER_RADIUS = 4
LASER_CONVERGE_TIME = 1.00
LASER_GLOW_ALPHA = 0.45
LOCK_FLASH_TIME = 0.10
HUD_FONT = cv2.FONT_HERSHEY_SIMPLEX
SCAN_SPEED = 0.35

SOUND_FILE = "/home/predator/predator/predator.mp3"
BEEP_ENABLED = True
DETECT_SOUND_FILE = os.environ.get("DETECT_SHOT_PATH", "/home/predator/predator/short-lasenr.mp3")

USB_CAMERA_INDEX = 0
FRAME_W, FRAME_H = 504, 792
WIN_TITLE = "TanosHUD"
TARGET_RESOLUTION = (504, 792)
RESOLUTION_WAIT_TIMEOUT = 30
RESOLUTION_CHECK_INTERVAL = 0.5

DETECTION_SKIP_FRAMES = 2
SEG_SKIP_FRAMES = 3

# Промо настройки
PROMO_PATH = os.environ.get("PROMO_PATH", "/home/predator/predator/promo.png")
PROMO_STRETCH_MODE = os.environ.get("PROMO_MODE", "fill_width")
PROMO_WIDTH_FRACTION = float(os.environ.get("PROMO_WIDTH_FRAC", "0.90"))
PROMO_FIXED_WIDTH_PX = int(float(os.environ.get("PROMO_WIDTH_PX", "450")))
PROMO_MAX_HEIGHT_FRACTION = float(os.environ.get("PROMO_MAX_H_FRAC", "0.90"))
PROMO_OPACITY = float(os.environ.get("PROMO_OPACITY", "1.0"))
PROMO_BOTTOM_MARGIN = int(float(os.environ.get("PROMO_BOTTOM", "5")))
PROMO_SIDE_MARGIN = int(float(os.environ.get("PROMO_SIDE", "5")))

# Production settings
GC_INTERVAL = 300  # Garbage collection каждые 5 минут
MEMORY_CHECK_INTERVAL = 60  # Проверка памяти каждую минуту
MAX_CACHE_SIZE = 10  # Максимум кэшированных изображений
FPS_WINDOW_SIZE = 30  # Окно для расчёта FPS
CAMERA_RECONNECT_DELAY = 5  # Задержка перед переподключением камеры
MAX_CAMERA_ERRORS = 10  # Максимум ошибок камеры подряд

# ================== MEDIAPIPE ==================
mp_face = mp.solutions.face_detection
mp_self = mp.solutions.selfie_segmentation

# ================== УТИЛИТЫ С ЗАЩИТОЙ ==================
def run_cmd_silent(cmd: str, timeout=2.0):
    try:
        subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, 
                      stderr=subprocess.DEVNULL, timeout=timeout)
    except Exception as e:
        logger.debug(f"Command failed: {cmd[:50]}... - {e}")

def get_current_screen_resolution():
    try:
        result = subprocess.run("xrandr | grep '\\*' | awk '{print $1}'", 
                              shell=True, capture_output=True, text=True, timeout=2.0)
        if result.stdout.strip():
            res_str = result.stdout.strip().split('\n')[0]
            w, h = map(int, res_str.split('x'))
            return (w, h)
    except Exception as e:
        logger.debug(f"Resolution check failed: {e}")
    return None

def wait_for_target_resolution(target_res, timeout=30, check_interval=0.5):
    start_time = time.time()
    while (time.time() - start_time) < timeout:
        try:
            current = get_current_screen_resolution()
            if current == target_res:
                time.sleep(1.0)
                return True
        except:
            pass
        time.sleep(check_interval)
    return False

def find_win_id_by_title(title: str) -> str:
    try:
        r = subprocess.run(f"xdotool search --name '^{title}$'", 
                          shell=True, capture_output=True, text=True, timeout=2.0)
        ids = [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
        return ids[-1] if ids else ""
    except:
        return ""

def force_kiosk_now(title: str):
    try:
        wid = find_win_id_by_title(title)
        if wid:
            run_cmd_silent(f"xprop -id {wid} -f _MOTIF_WM_HINTS 32c -set _MOTIF_WM_HINTS '2, 0, 0, 0, 0'")
            run_cmd_silent(f"wmctrl -i -r {wid} -b add,fullscreen,above,sticky,skip_taskbar,skip_pager")
            run_cmd_silent(f"wmctrl -r '{title}' -b add,fullscreen,above,sticky,skip_taskbar,skip_pager")
            run_cmd_silent(f"wmctrl -i -r {wid} -e 0,0,0,-1,-1")
        else:
            run_cmd_silent(f"wmctrl -r '{title}' -b add,fullscreen,above,sticky,skip_taskbar,skip_pager")
    except Exception as e:
        logger.debug(f"Kiosk mode update failed: {e}")

def force_kiosk_loop(title: str, seconds=6.0, period=0.10):
    t0 = time.time()
    while (time.time() - t0) < seconds:
        force_kiosk_now(title)
        time.sleep(period)

# ================== ЗВУК С ЗАЩИТОЙ ==================
pygame_mixer = None
sound_playing = False
_shot_snd = None
_locked_snd = None

def _mk_env(arr_f32, sr, attack=0.005, release=0.06):
    try:
        a = max(1, int(sr * attack))
        r = max(1, int(sr * release))
        env = np.ones_like(arr_f32, dtype=np.float32)
        env[:a] = np.linspace(0, 1, a, dtype=np.float32)
        env[-r:] = np.linspace(1, 0, r, dtype=np.float32)
        return (arr_f32 * env).astype(np.float32)
    except:
        return arr_f32

def _to_int16_stereo(arr_f32_mono):
    try:
        arr = np.clip(arr_f32_mono, -1.0, 1.0)
        stereo = np.column_stack((arr, arr))
        return (stereo * 32767.0).astype(np.int16)
    except:
        return np.zeros((100, 2), dtype=np.int16)

def init_sound():
    global pygame_mixer, _shot_snd, _locked_snd
    try:
        import pygame, pygame.sndarray
        pygame.mixer.init(frequency=44100, size=-16, channels=2)
        pygame_mixer = pygame.mixer
        
        if os.path.isfile(SOUND_FILE):
            try:
                pygame_mixer.music.load(SOUND_FILE)
                logger.info(f"Loaded background music: {SOUND_FILE}")
            except Exception as e:
                logger.warning(f"Failed to load music: {e}")
        
        if DETECT_SOUND_FILE and os.path.isfile(DETECT_SOUND_FILE):
            try:
                _shot_snd = pygame_mixer.Sound(DETECT_SOUND_FILE)
                logger.info(f"Loaded shot sound: {DETECT_SOUND_FILE}")
            except Exception as e:
                logger.warning(f"Failed to load shot sound: {e}")
        
        if _shot_snd is None:
            sr = 44100
            dur = 0.12
            t = np.linspace(0, dur, int(sr*dur), False).astype(np.float32)
            boom = 0.85*np.sin(2*np.pi*130.0*t).astype(np.float32)
            boom = _mk_env(boom, sr, 0.002, 0.09)
            noise = (np.random.randn(t.size).astype(np.float32)*0.35)
            noise = _mk_env(noise, sr, 0.001, 0.08)
            cdur = 0.018
            tc = np.linspace(0, cdur, int(sr*cdur), False).astype(np.float32)
            click = 0.6*np.sin(2*np.pi*2000.0*tc).astype(np.float32)
            click = _mk_env(click, sr, 0.0, 0.012)
            shot = np.zeros_like(t, dtype=np.float32)
            shot[:click.size] += click
            shot += boom + noise
            for _ in range(3):
                shot = (0.6*shot + 0.4*np.roll(shot, 1)).astype(np.float32)
            _shot_snd = pygame.sndarray.make_sound(_to_int16_stereo(shot*0.9))
        
        sr = 44100
        dur2 = 0.20
        tt = np.linspace(0, dur2, int(sr*dur2), False).astype(np.float32)
        f0, f1 = 700.0, 1200.0
        phase = 2*np.pi*(f0*tt + (f1-f0)/(2*dur2)*tt*tt)
        chirp = np.sin(phase).astype(np.float32)
        chirp = _mk_env(chirp, sr, 0.010, 0.050)
        for _ in range(3):
            chirp = (0.6*chirp + 0.4*np.roll(chirp, 1)).astype(np.float32)
        _locked_snd = pygame.sndarray.make_sound(_to_int16_stereo(chirp*0.7))
        
        logger.info("Sound system initialized")
    except Exception as e:
        logger.error(f"Sound initialization failed: {e}")
        pygame_mixer = None
        _shot_snd = None
        _locked_snd = None

def start_loop():
    global sound_playing
    if pygame_mixer and os.path.isfile(SOUND_FILE) and not sound_playing:
        try:
            pygame_mixer.music.play(-1)
            sound_playing = True
        except Exception as e:
            logger.debug(f"Failed to start music loop: {e}")

def stop_loop():
    global sound_playing
    if pygame_mixer and sound_playing:
        try:
            pygame_mixer.music.stop()
            sound_playing = False
        except Exception as e:
            logger.debug(f"Failed to stop music: {e}")

def shot_detect():
    try:
        if _shot_snd:
            _shot_snd.play()
            return
    except Exception as e:
        logger.debug(f"Shot sound failed: {e}")
    run_cmd_silent("paplay /usr/share/sounds/freedesktop/stereo/bell.oga || printf '\\a'")

def play_locked():
    try:
        if _locked_snd:
            _locked_snd.play()
            return
    except Exception as e:
        logger.debug(f"Lock sound failed: {e}")
    run_cmd_silent("paplay /usr/share/sounds/freedesktop/stereo/complete.oga || printf '\\a'")

# ================== МАТЕМАТИКА ==================
def smooth_val(prev, cur, k=SMOOTH_K):
    try:
        return cur if prev is None else int(k*prev + (1-k)*cur)
    except:
        return cur

def smooth_bbox(prev_bbox, cur_bbox, k=SMOOTH_K):
    try:
        if prev_bbox is None:
            return cur_bbox
        return tuple(smooth_val(p, c, k) for p, c in zip(prev_bbox, cur_bbox))
    except:
        return cur_bbox

def iou(a, b):
    try:
        ax, ay, aw, ah = a
        bx, by, bw, bh = b
        x1 = max(ax, bx)
        y1 = max(ay, by)
        x2 = min(ax+aw, bx+bw)
        y2 = min(ay+ah, bx+bh)
        inter = max(0, x2-x1) * max(0, y2-y1)
        uni = aw*ah + bw*bh - inter
        return inter/uni if uni > 0 else 0.0
    except:
        return 0.0

def largest_n_faces_filtered(dets, W, H, n=MAX_TARGETS):
    faces = []
    try:
        for d in dets:
            box = d.location_data.relative_bounding_box
            x = int(box.xmin * W)
            y = int(box.ymin * H)
            w = int(box.width * W)
            h = int(box.height * H)
            aspect = h / (w + 1e-6)
            area = (w*h)/(W*H)
            if not (0.8 < aspect < 2.0):
                continue
            if not (0.005 <= area <= 0.30):
                continue
            pad = 0.5
            x = int(x - w*pad/2)
            y = int(y - h*pad/2)
            w = int(w*(1+pad))
            h = int(h*(1+pad))
            x = max(0, x)
            y = max(0, y)
            w = min(W-x, w)
            h = min(H-y, h)
            faces.append((x, y, w, h, area))
        faces.sort(key=lambda t: t[4], reverse=True)
        return [(x, y, w, h) for x, y, w, h, _ in faces[:n]]
    except Exception as e:
        logger.debug(f"Face filtering error: {e}")
        return []

def triangle_from_bbox(bbox):
    try:
        x, y, w, h = bbox
        cx = x + w//2
        return np.array([[cx, y], [x+w, y+h], [x, y+h]], dtype=np.int32)
    except:
        return np.array([[0, 0], [10, 10], [0, 10]], dtype=np.int32)

def tri_centroid(pts):
    try:
        return np.mean(pts.astype(np.float32), axis=0)
    except:
        return np.array([0.0, 0.0])

def ease(progress, kind="linear"):
    try:
        p = max(0.0, min(1.0, float(progress)))
        return 1 - (1 - p)**3 if kind == "ease_out_cubic" else p
    except:
        return 0.0

def lerp(a, b, t):
    try:
        return a + (b-a)*t
    except:
        return a

def transform_triangle_to_center(pts, center, scale=1.0, rot_deg=0.0):
    try:
        pts = pts.astype(np.float32)
        c = tri_centroid(pts)
        t = pts - c
        t *= scale
        a = math.radians(rot_deg)
        R = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
        t = (t @ R.T)
        return (t + center).astype(np.int32)
    except:
        return pts

def draw_dashed_line(img, p0, p1, color, thickness, dash_len, gap_len):
    try:
        p0, p1 = np.array(p0, np.float32), np.array(p1, np.float32)
        vec = p1 - p0
        dist = np.linalg.norm(vec)
        if dist < 1e-3:
            return
        dirv = vec / dist
        step = max(1.0, dash_len + gap_len)
        n = int(dist // step) + 1
        for i in range(n):
            start_d = i*step
            end_d = min(start_d + dash_len, dist)
            if start_d >= dist:
                break
            a = p0 + dirv*start_d
            b = p0 + dirv*end_d
            cv2.line(img, (int(a[0]), int(a[1])), (int(b[0]), int(b[1])), 
                    color, thickness, cv2.LINE_AA)
    except Exception as e:
        logger.debug(f"Dashed line error: {e}")

def draw_dashed_polygon(img, pts, color, thickness, dash_len, gap_len):
    try:
        pts = np.asarray(pts, np.int32)
        cnt = len(pts)
        if cnt < 2:
            return
        for i in range(cnt):
            j = (i+1) % cnt
            draw_dashed_line(img, pts[i], pts[j], color, thickness, dash_len, gap_len)
    except Exception as e:
        logger.debug(f"Dashed polygon error: {e}")

def draw_glow_triangle(img, pts, color, glow_radius, glow_alpha, thickness, flash, dash_len, gap_len):
    try:
        pad = int(glow_radius*0.5)
        c = pts.astype(np.float32).mean(axis=0)
        dir_vec = pts.astype(np.float32)-c
        norm = np.linalg.norm(dir_vec, axis=1, keepdims=True) + 1e-6
        outward = (dir_vec / norm)*pad
        exp_pts = np.clip(pts.astype(np.float32)+outward, 0, 1e9).astype(np.int32)
        ov2 = img.copy()
        draw_dashed_polygon(ov2, exp_pts, color, max(1, thickness), dash_len, gap_len)
        img[:] = cv2.addWeighted(ov2, glow_alpha*0.35, img, 1-glow_alpha*0.35, 0)
        if flash:
            draw_dashed_polygon(img, pts, (255, 255, 255), max(1, thickness*2), dash_len, gap_len)
        draw_dashed_polygon(img, pts, color, max(1, thickness), dash_len, gap_len)
    except Exception as e:
        logger.debug(f"Glow triangle error: {e}")

def draw_building_triangle_lines(img, pts, color, thickness, progress, dash_len, gap_len):
    try:
        pts = pts.astype(np.float32)
        edges = [(0, 1), (1, 2), (2, 0)]
        l = max(0.0, min(1.0, progress))
        for a, b in edges:
            p0, p1 = pts[a], pts[b]
            mid = (p0+p1)/2.0
            vec = (p1-p0)/2.0
            a_pt = (mid - vec*l).astype(int)
            b_pt = (mid + vec*l).astype(int)
            draw_dashed_line(img, a_pt, b_pt, color, max(1, thickness), dash_len, gap_len)
    except Exception as e:
        logger.debug(f"Building triangle error: {e}")

def draw_laser_dot(img, pt, base_r, color, glow_alpha):
    try:
        x, y = int(pt[0]), int(pt[1])
        cv2.circle(img, (x, y), max(1, base_r), color, -1, cv2.LINE_AA)
        r = max(1, base_r + 2)
        ov = img.copy()
        cv2.circle(ov, (x, y), r, color, -1, cv2.LINE_AA)
        img[:] = cv2.addWeighted(ov, glow_alpha*0.4, img, 1-glow_alpha*0.4, 0)
    except Exception as e:
        logger.debug(f"Laser dot error: {e}")

# ================== HUD ==================
def _blend_rgba(dst, x, y, src_rgba, opacity=1.0):
    try:
        h, w = src_rgba.shape[:2]
        if x >= dst.shape[1] or y >= dst.shape[0]:
            return
        x2 = min(dst.shape[1], x + w)
        y2 = min(dst.shape[0], y + h)
        if x2 <= x or y2 <= y:
            return
        w = x2 - x
        h = y2 - y
        roi = dst[y:y+h, x:x+w]
        src = src_rgba[0:h, 0:w, :3]
        if src_rgba.shape[2] == 4:
            a = (src_rgba[0:h, 0:w, 3].astype(np.float32) / 255.0) * float(max(0.0, min(1.0, opacity)))
        else:
            a = np.full((h, w), float(max(0.0, min(1.0, opacity))), dtype=np.float32)
        a = a[..., None]
        roi[:] = (src.astype(np.float32) * a + roi.astype(np.float32) * (1.0 - a)).astype(np.uint8)
    except Exception as e:
        logger.debug(f"RGBA blend error: {e}")

class PromoRenderer:
    def __init__(self, img):
        self.src = img
        self.cache = {}
        self.max_cache_size = MAX_CACHE_SIZE
    
    def get_scaled(self, W, H):
        try:
            if self.src is None:
                return None
            
            # Очистка кэша если слишком большой
            if len(self.cache) > self.max_cache_size:
                oldest = list(self.cache.keys())[0]
                del self.cache[oldest]
            
            mode = PROMO_STRETCH_MODE
            frac = PROMO_WIDTH_FRACTION
            px = PROMO_FIXED_WIDTH_PX
            maxh = PROMO_MAX_HEIGHT_FRACTION
            
            key = (W, H, mode, frac, px, maxh)
            if key in self.cache:
                return self.cache[key]
            
            src = self.src
            src_h, src_w = src.shape[:2]
            max_h = int(H * max(0.05, min(0.95, maxh)))
            
            if mode == "fixed_px":
                target_w = int(px)
                scale = target_w / src_w
                target_h = int(src_h * scale)
            else:
                target_w = int(W * max(0.05, min(0.99, frac)))
                if mode == "fill_width":
                    target_h = int(max_h)
                else:
                    scale = target_w / src_w
                    target_h = int(src_h * scale)
            
            if target_h > max_h:
                if mode == "fill_width":
                    target_h = max_h
                else:
                    scale = max_h / target_h
                    target_w = int(target_w * scale)
                    target_h = int(max_h)
            
            resized = cv2.resize(src, (max(1, target_w), max(1, target_h)), interpolation=cv2.INTER_AREA)
            
            if resized.shape[2] == 3:
                alpha = np.full((resized.shape[0], resized.shape[1], 1), 255, dtype=np.uint8)
                resized = np.concatenate([resized, alpha], axis=2)
            
            self.cache[key] = resized
            return resized
        except Exception as e:
            logger.debug(f"PromoRenderer error: {e}")
            return None

def add_predator_hud(img, w, h, s, scan_phase, promo_renderer):
    try:
        # Рамки + маркеры
        cv2.rectangle(img, (0, 0), (w-1, h-1), (0, 255, 255), max(1, int(1*s)))
        step = int(20*s)
        for yy in range(step, h, step):
            cv2.line(img, (int(4*s), yy), (int(12*s), yy), (0, 255, 255), max(1, int(1*s)))
            cv2.line(img, (w-int(4*s), yy), (w-int(12*s), yy), (0, 255, 255), max(1, int(1*s)))
        
        # Скан-полоска
        band_h = max(4, int(7*s))
        y0 = int((scan_phase % 1.0) * (h + band_h)) - band_h
        y1 = min(h, y0 + band_h)
        if 0 <= y0 < h:
            overlay = img.copy()
            cv2.rectangle(overlay, (0, y0), (w, y1), (0, 255, 255), -1)
            img[:] = cv2.addWeighted(overlay, 0.10, img, 0.90, 0)
        
        # Статус
        dots = int((time.time()*2) % 4)
        mode_text = "MODE: HUNTER   SCAN ACTIVE" + "."*dots
        cv2.putText(img, mode_text, (int(5*s), int(18*s)), HUD_FONT, 0.5*s, 
                   (200, 200, 200), max(1, int(1*s)), cv2.LINE_AA)
        
        # Промо-баннер
        promo_img = promo_renderer.get_scaled(w, h) if promo_renderer else None
        if promo_img is not None:
            new_h, new_w = promo_img.shape[0], promo_img.shape[1]
            x = max(PROMO_SIDE_MARGIN, (w - new_w) // 2)
            y = h - PROMO_BOTTOM_MARGIN - new_h
            if y < 0:
                y = 0
            _blend_rgba(img, x, y, promo_img, opacity=PROMO_OPACITY)
    except Exception as e:
        logger.debug(f"HUD rendering error: {e}")

# ================== ЦЕЛЬ ==================
class Target:
    def __init__(self, tid, bbox):
        self.id = tid
        self.bbox = bbox
        self.state = "TRACKING"
        self.created_at = time.time()
        self.lock_started_at = time.time()
        self.last_seen_at = time.time()
        self.beeped_created = False
        self.beeped_locked = False
        edge = random.choice(["left", "right", "top", "bottom"])
        w, h = FRAME_W, FRAME_H
        if edge == "left":
            self.spawn_origin = np.array([-int(0.15*w), random.randint(0, h)])
        elif edge == "right":
            self.spawn_origin = np.array([w+int(0.15*w), random.randint(0, h)])
        elif edge == "top":
            self.spawn_origin = np.array([random.randint(0, w), -int(0.15*h)])
        else:
            self.spawn_origin = np.array([random.randint(0, w), h+int(0.15*h)])
        self.spawn_started_at = self.created_at
        self.laser_started_at = None
        self.flash_until = self.created_at + 0.6
        self.laser_init_pts = None
    
    def update(self, bbox):
        try:
            self.bbox = smooth_bbox(self.bbox, bbox)
            self.last_seen_at = time.time()
        except Exception as e:
            logger.debug(f"Target update error: {e}")
    
    def step_state(self):
        try:
            if self.state == "TRACKING" and (time.time() - self.lock_started_at) >= LOCK_REQUIRED_STABLE_SEC:
                self.state = "LOCKED"
                self.flash_until = time.time() + LOCK_FLASH_TIME
                self.laser_started_at = time.time()
                if not self.beeped_locked and BEEP_ENABLED:
                    play_locked()
                    self.beeped_locked = True
        except Exception as e:
            logger.debug(f"Target state error: {e}")
    
    def lost_too_long(self):
        try:
            return (time.time() - self.last_seen_at) > LOCK_LOST_GRACE_SEC
        except:
            return True

# ================== CAMERA MANAGER ==================
class CameraManager:
    def __init__(self, index=0, width=FRAME_W, height=FRAME_H):
        self.index = index
        self.width = width
        self.height = height
        self.cap = None
        self.error_count = 0
        self.last_reconnect = 0
        self.connect()
    
    def connect(self):
        try:
            if self.cap:
                self.cap.release()
            
            logger.info(f"Connecting to camera {self.index}...")
            self.cap = cv2.VideoCapture(self.index)
            
            if not self.cap.isOpened():
                time.sleep(2)
                self.cap = cv2.VideoCapture(self.index)
            
            if not self.cap.isOpened():
                logger.error("Camera failed to open")
                return False
            
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            self.cap.set(cv2.CAP_PROP_FPS, 30)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
            
            # Проверяем что можем читать
            ret, frame = self.cap.read()
            if not ret or frame is None:
                logger.error("Camera opened but cannot read frames")
                return False
            
            self.error_count = 0
            logger.info(f"Camera connected: {self.width}x{self.height}")
            return True
            
        except Exception as e:
            logger.error(f"Camera connection error: {e}")
            return False
    
    def read(self):
        try:
            if not self.cap or not self.cap.isOpened():
                if time.time() - self.last_reconnect > CAMERA_RECONNECT_DELAY:
                    self.last_reconnect = time.time()
                    self.connect()
                return False, None
            
            ret, frame = self.cap.read()
            
            if not ret or frame is None:
                self.error_count += 1
                if self.error_count > MAX_CAMERA_ERRORS:
                    logger.warning(f"Camera errors: {self.error_count}, reconnecting...")
                    if time.time() - self.last_reconnect > CAMERA_RECONNECT_DELAY:
                        self.last_reconnect = time.time()
                        self.connect()
                return False, None
            
            self.error_count = 0
            return True, frame
            
        except Exception as e:
            logger.debug(f"Camera read error: {e}")
            self.error_count += 1
            return False, None
    
    def release(self):
        try:
            if self.cap:
                self.cap.release()
                logger.info("Camera released")
        except Exception as e:
            logger.error(f"Camera release error: {e}")

# ================== FPS MONITOR ==================
class FPSMonitor:
    def __init__(self, window_size=30):
        self.times = deque(maxlen=window_size)
        self.last_log = time.time()
        self.log_interval = 10.0
    
    def tick(self):
        self.times.append(time.time())
        
        if time.time() - self.last_log > self.log_interval:
            fps = self.get_fps()
            logger.info(f"FPS: {fps:.1f}")
            self.last_log = time.time()
    
    def get_fps(self):
        if len(self.times) < 2:
            return 0.0
        elapsed = self.times[-1] - self.times[0]
        return len(self.times) / elapsed if elapsed > 0 else 0.0

# ================== MEMORY MONITOR ==================
class MemoryMonitor:
    def __init__(self, check_interval=60):
        self.check_interval = check_interval
        self.last_check = time.time()
        self.last_gc = time.time()
    
    def check(self):
        now = time.time()
        
        # Garbage collection
        if now - self.last_gc > GC_INTERVAL:
            collected = gc.collect()
            logger.info(f"GC: collected {collected} objects")
            self.last_gc = now
        
        # Memory logging
        if now - self.last_check > self.check_interval:
            try:
                import psutil
                process = psutil.Process()
                mem_mb = process.memory_info().rss / 1024 / 1024
                logger.info(f"Memory usage: {mem_mb:.1f} MB")
            except:
                pass
            self.last_check = now

# ================== MAIN ==================
def main():
    logger.info("=" * 60)
    logger.info("Starting Predator HUD (Production 24/7)")
    logger.info(f"Version: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)
    
    # Ждем нужного разрешения
    logger.info("Waiting for target resolution...")
    if wait_for_target_resolution(TARGET_RESOLUTION, RESOLUTION_WAIT_TIMEOUT, RESOLUTION_CHECK_INTERVAL):
        logger.info("✓ Target resolution confirmed")
    else:
        logger.warning("⚠ Resolution check timeout, continuing anyway")
    
    # Настройка окружения
    os.environ.setdefault("SDL_VIDEODRIVER", "x11")
    os.environ.setdefault("SDL_VIDEO_X11_NET_WM_BYPASS_COMPOSITOR", "1")
    
    use_pygame = False
    SCREEN_W = SCREEN_H = None
    screen = None
    
    # Инициализация дисплея
    try:
        import pygame
        pygame.init()
        flags = pygame.FULLSCREEN | pygame.NOFRAME | pygame.SCALED
        screen = pygame.display.set_mode((0, 0), flags)
        pygame.display.set_caption(WIN_TITLE)
        pygame.mouse.set_visible(False)
        info = pygame.display.Info()
        SCREEN_W, SCREEN_H = info.current_w, info.current_h
        screen.fill((0, 0, 0))
        pygame.display.flip()
        time.sleep(0.15)
        threading.Thread(target=force_kiosk_loop, args=(WIN_TITLE, 6.0, 0.10), daemon=True).start()
        use_pygame = True
        logger.info(f"✓ Pygame display initialized: {SCREEN_W}x{SCREEN_H}")
    except Exception as e:
        logger.warning(f"Pygame failed: {e}, falling back to OpenCV")
        try:
            cv2.namedWindow(WIN_TITLE, cv2.WINDOW_NORMAL)
            cv2.setWindowProperty(WIN_TITLE, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
            SCREEN_W, SCREEN_H = FRAME_W, FRAME_H
            threading.Thread(target=force_kiosk_loop, args=(WIN_TITLE, 6.0, 0.10), daemon=True).start()
            logger.info("✓ OpenCV display initialized")
        except Exception as e2:
            logger.error(f"Display initialization failed: {e2}")
            return 1
    
    # Инициализация звука
    init_sound()
    
    # Инициализация камеры
    camera = CameraManager(USB_CAMERA_INDEX, FRAME_W, FRAME_H)
    if not camera.cap or not camera.cap.isOpened():
        logger.error("Failed to initialize camera")
        return 1
    
    # Инициализация ML моделей
    try:
        face_det = mp_face.FaceDetection(model_selection=1, min_detection_confidence=0.75)
        logger.info("✓ Face detection initialized")
    except Exception as e:
        logger.error(f"Face detection init failed: {e}")
        return 1
    
    seg = None
    if USE_SEGMENTATION:
        try:
            seg = mp_self.SelfieSegmentation(model_selection=1)
            logger.info("✓ Segmentation initialized")
        except Exception as e:
            logger.warning(f"Segmentation init failed: {e}")
    
    # Загрузка промо-баннера
    promo_raw = None
    promo_renderer = None
    try:
        if PROMO_PATH and os.path.exists(PROMO_PATH):
            promo_raw = cv2.imread(PROMO_PATH, cv2.IMREAD_UNCHANGED)
            if promo_raw is not None:
                promo_renderer = PromoRenderer(promo_raw)
                logger.info(f"✓ Promo banner loaded: {PROMO_PATH}")
        else:
            for p in ["promo.png", "promo.jpg", "photo_2025-11-04_14-36-13.png"]:
                if os.path.exists(p):
                    promo_raw = cv2.imread(p, cv2.IMREAD_UNCHANGED)
                    if promo_raw is not None:
                        promo_renderer = PromoRenderer(promo_raw)
                        logger.info(f"✓ Promo banner loaded: {p}")
                        break
    except Exception as e:
        logger.warning(f"Promo banner load failed: {e}")
    
    # Инициализация мониторов
    fps_monitor = FPSMonitor(FPS_WINDOW_SIZE)
    memory_monitor = MemoryMonitor(MEMORY_CHECK_INTERVAL)
    
    # Инициализация LUT для цветовой обработки
    gray_lut = np.arange(256, dtype=np.uint8)
    cold_lut = cv2.applyColorMap(255 - gray_lut.reshape(1, 256), BG_COLD_COLORMAP).reshape(256, 3)
    warm_lut = cv2.applyColorMap(gray_lut.reshape(1, 256), WARM_BASE_COLORMAP).reshape(256, 3)
    warm_lut = np.clip(warm_lut.astype(np.float32) * [0.65, 1.0, 1.28] + [0, 0, 22], 0, 255).astype(np.uint8)
    
    # Основной цикл
    targets = []
    next_tid = 0
    t0 = time.time()
    running = True
    frame_count = 0
    last_faces = []
    last_seg_mask = None
    
    logger.info("✓ Entering main loop")
    
    try:
        while running:
            # Чтение кадра
            ret, frame = camera.read()
            if not ret or frame is None:
                time.sleep(0.05)
                continue
            
            if FORCE_UNMIRROR_USB:
                frame = cv2.flip(frame, 1)
            
            H, W = frame.shape[:2]
            frame_count += 1
            
            # Детекция лиц (с пропуском кадров)
            if frame_count % (DETECTION_SKIP_FRAMES + 1) == 0:
                try:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    res = face_det.process(rgb)
                    dets = res.detections if res and res.detections else []
                    last_faces = largest_n_faces_filtered(dets, W, H)
                except Exception as e:
                    logger.debug(f"Face detection error: {e}")
                    last_faces = []
            
            faces = last_faces
            unmatched = faces.copy()
            
            # Обновление существующих целей
            for t in targets[:]:
                try:
                    best = max((f for f in unmatched), key=lambda f: iou(t.bbox, f), default=None)
                    if best and iou(t.bbox, best) > 0.3:
                        t.update(best)
                        unmatched.remove(best)
                    t.step_state()
                    if t.lost_too_long():
                        targets.remove(t)
                except Exception as e:
                    logger.debug(f"Target update error: {e}")
            
            # Добавление новых целей
            for fb in unmatched:
                try:
                    if len(targets) >= MAX_TARGETS:
                        break
                    targets.append(Target(next_tid, fb))
                    next_tid += 1
                except Exception as e:
                    logger.debug(f"Target creation error: {e}")
            
            # Управление звуком
            try:
                any_tracking = any(t.state == "TRACKING" for t in targets)
                any_locked = any(t.state == "LOCKED" for t in targets)
                if any_tracking or any_locked:
                    start_loop()
                else:
                    stop_loop()
            except Exception as e:
                logger.debug(f"Sound control error: {e}")
            
            # Сегментация (с пропуском кадров)
            if USE_SEGMENTATION and seg and frame_count % (SEG_SKIP_FRAMES + 1) == 0:
                try:
                    if 'rgb' not in locals():
                        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    small = cv2.resize(rgb, (int(W*SEG_DOWNSCALE), int(H*SEG_DOWNSCALE)))
                    res = seg.process(small)
                    mask = (res.segmentation_mask > SEG_THRESH).astype(np.uint8) * 255
                    last_seg_mask = cv2.resize(mask, (W, H), cv2.INTER_NEAREST)
                except Exception as e:
                    logger.debug(f"Segmentation error: {e}")
            
            seg_mask = last_seg_mask if last_seg_mask is not None else np.zeros((H, W), dtype=np.uint8)
            
            # Обработка изображения
            try:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                clahe = cv2.createCLAHE(2.0, (4, 4))
                gray_eq = clahe.apply(gray)
                
                cold = cold_lut[gray_eq]
                cold = cv2.convertScaleAbs(cold, alpha=BG_DARKEN_ALPHA, beta=BG_DARKEN_BETA)
                warm = warm_lut[gray_eq]
                
                mask_f = cv2.GaussianBlur(seg_mask, (7, 7), 0).astype(np.float32)/255
                mask_f = mask_f[:, :, None]
                composed = np.clip(cold.astype(np.float32)*(1-mask_f) + 
                                 warm.astype(np.float32)*mask_f*ALPHA_WARM_IN_MASK, 0, 255).astype(np.uint8)
            except Exception as e:
                logger.error(f"Image processing error: {e}")
                composed = frame.copy()
            
            # Добавление HUD
            ui = max(0.6, min(1.3, min(W, H)/576))
            scan_phase = (time.time() - t0) * SCAN_SPEED
            add_predator_hud(composed, W, H, ui, scan_phase, promo_renderer)
            
            # Рисование целей
            dash_len = max(4, int(8*ui))
            gap_len = max(3, int(6*ui))
            now = time.time()
            
            for t in targets:
                try:
                    x, y, w0, h0 = t.bbox
                    tri = triangle_from_bbox(t.bbox)
                    center = tri_centroid(tri)
                    
                    spawn_p = ease((now - t.spawn_started_at) / TRI_SPAWN_TIME, TRI_SPAWN_EASING)
                    cur_center = (1-spawn_p)*t.spawn_origin + spawn_p*center
                    scale = lerp(0.4, 1.0, spawn_p)
                    rot = (1-spawn_p)*8*math.sin(now*6)
                    jitter = int((1-spawn_p)*3)
                    
                    transformed = transform_triangle_to_center(tri, cur_center, scale, rot)
                    if jitter:
                        transformed = (transformed.astype(np.float32) + 
                                     np.random.randn(3, 2)*jitter).astype(np.int32)
                    
                    build_p = 1.0 if t.state == "LOCKED" else max(0.0, min(1.0, 
                                                                  (now - t.created_at)/TRI_BUILD_TIME))
                    
                    if spawn_p < 1.0:
                        draw_building_triangle_lines(composed, transformed, TRI_COLOR_TRACKING, 
                                                   int(TRI_OUT_THICK*ui), spawn_p*0.7 + build_p*0.3, 
                                                   dash_len, gap_len)
                    else:
                        if build_p < 1.0:
                            draw_building_triangle_lines(composed, transformed, TRI_COLOR_TRACKING, 
                                                       int(TRI_OUT_THICK*ui), build_p, dash_len, gap_len)
                        else:
                            pulse = (np.sin(now*6)+1)/2
                            color = TRI_COLOR_LOCKED if t.state == "LOCKED" else TRI_COLOR_TRACKING
                            glow = int(12*ui * (1.2 if t.state == "LOCKED" else 0.9 + 0.6*pulse))
                            draw_glow_triangle(composed, transformed, color, glow,
                                            0.5 if t.state == "LOCKED" else 0.38+0.15*pulse,
                                            int(TRI_OUT_THICK*ui), now < t.flash_until, dash_len, gap_len)
                    
                    if t.state == "LOCKED" and t.laser_started_at:
                        v0, v1, v2 = transformed
                        if t.laser_init_pts is None:
                            o = int(0.2*max(W, H))
                            t.laser_init_pts = np.array([[v0[0]-o, v0[1]-o], 
                                                        [v1[0]+o, v1[1]-o], 
                                                        [v2[0], v2[1]+o]], dtype=np.float32)
                        lp = min(1.0, (now - t.laser_started_at)/LASER_CONVERGE_TIME)
                        for i in range(3):
                            p = t.laser_init_pts[i]*(1-lp) + np.array([v0, v1, v2][i])*lp
                            draw_laser_dot(composed, p, int(LASER_RADIUS*ui), 
                                         color=LASER_COLOR, glow_alpha=LASER_GLOW_ALPHA)
                    
                    cx, cy = int(center[0]), int(center[1] - h0*0.05)
                    cv2.line(composed, (cx-4, cy), (cx+4, cy), (255, 255, 255), 1)
                    cv2.line(composed, (cx, cy-4), (cx, cy+4), (255, 255, 255), 1)
                    
                    temp = round((np.mean(gray[y:y+h0, x:x+w0]) / 255)*35 - 5 + 
                               random.uniform(-1, 1), 1)
                    cv2.putText(composed, f"{temp}C", (x + w0//2 - 10, y - 5), 
                              HUD_FONT, 0.5*ui, (0, 255, 255), 1, cv2.LINE_AA)
                    
                    label = "TARGET LOCKED" if t.state == "LOCKED" else "TARGETING..."
                    (tw, th), _ = cv2.getTextSize(label, HUD_FONT, 0.5*ui, max(1, int(1*ui)))
                    lx = x + w0//2 - tw//2
                    ly = y - 16 if y > 21 else y + h0 + 22
                    cv2.putText(composed, label, (lx, ly), HUD_FONT, 0.5*ui, 
                              (0, 0, 0), 2, cv2.LINE_AA)
                    cv2.putText(composed, label, (lx, ly), HUD_FONT, 0.5*ui, 
                              (0, 255, 0), 1, cv2.LINE_AA)
                    
                except Exception as e:
                    logger.debug(f"Target rendering error: {e}")
            
            # Отображение кадра
            try:
                if use_pygame and screen:
                    import pygame
                    cw, ch = pygame.display.get_window_size()
                    if (cw, ch) != (SCREEN_W, SCREEN_H):
                        SCREEN_W, SCREEN_H = cw, ch
                    frame_out = cv2.resize(composed, (SCREEN_W, SCREEN_H))
                    rgb_out = cv2.cvtColor(frame_out, cv2.COLOR_BGR2RGB).copy()
                    surf = pygame.image.frombuffer(rgb_out.tobytes(), (SCREEN_W, SCREEN_H), 'RGB')
                    screen.blit(surf, (0, 0))
                    pygame.display.flip()
                    
                    for event in pygame.event.get():
                        if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and 
                                                         event.key == pygame.K_ESCAPE):
                            running = False
                            logger.info("Exit requested via pygame event")
                else:
                    frame_out = cv2.resize(composed, (FRAME_W, FRAME_H))
                    cv2.imshow(WIN_TITLE, frame_out)
                    if cv2.waitKey(1) & 0xFF == 27:
                        running = False
                        logger.info("Exit requested via ESC key")
            except Exception as e:
                logger.error(f"Display error: {e}")
            
            # Мониторинг
            fps_monitor.tick()
            memory_monitor.check()
    
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Main loop error: {e}")
        logger.error(traceback.format_exc())
    finally:
        # Cleanup
        logger.info("Shutting down...")
        stop_loop()
        camera.release()
        
        if use_pygame and 'pygame' in sys.modules:
            try:
                import pygame
                pygame.quit()
            except:
                pass
        else:
            try:
                cv2.destroyAllWindows()
            except:
                pass
        
        logger.info("Shutdown complete")
        return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        logger.critical(f"Fatal error: {e}")
        logger.critical(traceback.format_exc())
        sys.exit(1)