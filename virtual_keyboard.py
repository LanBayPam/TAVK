"""
AI Virtual Keyboard — Enhanced Edition
=======================================
Fitur baru dibanding versi dasar:
  • Number row  (1 – 0)
  • CAPS LOCK toggle  (teal = aktif)
  • SHIFT + symbol layer  (!@#$…  :,<.>?)
  • Cooldown arc di sekitar ujung jari indeks
  • FPS counter + confidence bar per tangan (HUD)
  • Dwell-click mode  (tahan jari 1 detik → klik otomatis)
  • Two-hand support  (kedua tangan bisa mengetik bersamaan)
  • Tombol SAVE  (menyimpan teks ke output.txt)
  • Gesture klik: jari indeks hover → jari tengah flick ke bawah → klik
  • Tekan D untuk toggle Flick ↔ Dwell mode

Based on: Murtaza's Workshop – AI Virtual Keyboard
YouTube:  https://www.youtube.com/watch?v=jzXZVFqEE2I
"""

import cv2
import mediapipe as mp
import time
from collections import deque
from pathlib import Path

# pynput opsional — kalau tidak terinstall, teks hanya tampil di jendela OpenCV
try:
    from pynput.keyboard import Controller as _KbController, Key as _Key
    _sys_kb  = _KbController()
    _pynput  = True
except ImportError:
    _pynput  = False

# ─── MediaPipe setup ────────────────────────────────────────────────────────
_mp_hands  = mp.solutions.hands
_mp_draw   = mp.solutions.drawing_utils
_mp_styles = mp.solutions.drawing_styles

hand_detector = _mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=2,                  # two-hand support
    min_detection_confidence=0.75,
    min_tracking_confidence=0.75,
)

# ─── Layout constants ───────────────────────────────────────────────────────
KEY_W, KEY_H = 75, 75
GAP     = 8
START_X = 229                         # (1280 - (10*75 + 9*8)) // 2 = 229  → centered
START_Y = 255                         # keyboard di bagian bawah layar
STEP    = KEY_W + GAP                 # 83 px per sel

NUM_ROW    = ["1","2","3","4","5","6","7","8","9","0"]
ALPHA_ROWS = [
    ["Q","W","E","R","T","Y","U","I","O","P"],
    ["A","S","D","F","G","H","J","K","L",";"],
    ["Z","X","C","V","B","N","M",",",".","/"],
]

# Karakter yang muncul saat SHIFT aktif
SHIFT_MAP = {
    "1":"!", "2":"@", "3":"#", "4":"$", "5":"%",
    "6":"^", "7":"&", "8":"*", "9":"(", "0":")",
    ";":":", ",":"<", ".":">", "/":"?",
}

# Threshold interaksi
FLICK_THRESHOLD = 28   # px ke bawah dalam FLICK_WINDOW frame = flick
FLICK_WINDOW    = 5    # jumlah frame untuk deteksi flick (~167ms di 30fps)
CLICK_COOLDOWN  = 0.55 # s   – jeda minimum antar klik
DWELL_TIME      = 1.0  # s   – durasi tahan untuk dwell-click

# ─── Palet warna ─────────────────────────────────────────────────────────────
C = {
    "normal"     : ( 85,  85, 185),
    "hover"      : (210, 130,  45),
    "clicked"    : ( 40, 210,  80),
    "caps_on"    : ( 30, 190, 190),   # teal saat CAPS aktif
    "shift_on"   : (200, 155,  30),   # amber saat SHIFT aktif
    "border"     : (180, 180, 255),
    "bg"         : ( 28,  28,  48),
    "textbox_bg" : ( 18,  18,  32),
    "dwell_ring" : (255, 200,   0),   # emas – progress dwell
    "ready"      : (  0, 230,   0),   # hijau – siap klik
    "cooling"    : (  0, 120, 255),   # biru  – masih cooldown
}


# ─── Button ──────────────────────────────────────────────────────────────────
class Button:
    """Satu tombol di keyboard virtual."""

    def __init__(self, x: int, y: int, label: str,
                 w: int = KEY_W, h: int = KEY_H):
        self.x, self.y = x, y
        self.w, self.h = w, h
        self.label = label

    def hit(self, px: int, py: int) -> bool:
        return self.x < px < self.x + self.w and self.y < py < self.y + self.h


def build_keyboard() -> list:
    """Buat semua Button untuk layout keyboard lengkap."""
    btns = []

    # Baris 0 – angka
    for i, k in enumerate(NUM_ROW):
        btns.append(Button(START_X + i * STEP, START_Y, k))

    # Baris 1-3 – huruf
    for ri, row in enumerate(ALPHA_ROWS):
        for ci, k in enumerate(row):
            btns.append(Button(START_X + ci * STEP,
                               START_Y + (ri + 1) * STEP, k))

    # Baris 4 – tombol khusus
    # Total lebar keyboard = 10*65 + 9*6 = 704 px
    # CAPS(65) + SHIFT(136) + SPC(207) + DEL(136) + SAVE(136) = 680 + 4*6 = 704
    by      = START_Y + 4 * STEP
    kbd_w   = 10 * KEY_W + 9 * GAP    # 704

    caps_w  = KEY_W                    # 65
    shift_w = KEY_W * 2 + GAP         # 136
    spc_w   = KEY_W * 3 + GAP * 2     # 207
    del_w   = KEY_W * 2 + GAP         # 136
    save_w  = kbd_w - caps_w - shift_w - spc_w - del_w - 4 * GAP  # 136

    x = START_X
    btns.append(Button(x, by, "CAPS",  w=caps_w));  x += caps_w  + GAP
    btns.append(Button(x, by, "SHIFT", w=shift_w)); x += shift_w + GAP
    btns.append(Button(x, by, "SPC",   w=spc_w));   x += spc_w   + GAP
    btns.append(Button(x, by, "DEL",   w=del_w));   x += del_w   + GAP
    btns.append(Button(x, by, "SAVE",  w=save_w))

    return btns


# ─── Helpers ─────────────────────────────────────────────────────────────────
def _rounded_rect(img, x, y, w, h, r, color, t=-1):
    """Persegi panjang dengan sudut membulat."""
    cv2.rectangle(img, (x + r, y),     (x + w - r, y + h),     color, t)
    cv2.rectangle(img, (x,     y + r), (x + w,     y + h - r), color, t)
    for cx, cy in [(x+r, y+r), (x+w-r, y+r), (x+r, y+h-r), (x+w-r, y+h-r)]:
        cv2.circle(img, (cx, cy), r, color, t)


def resolve_char(label: str, caps: bool, shift: bool) -> str:
    """Terjemahkan label + modifier → karakter yang akan diketik."""
    if label in "QWERTYUIOPASDFGHJKLZXCVBNM":
        upper = caps ^ shift              # XOR: shift membalik state caps
        return label if upper else label.lower()
    if shift and label in SHIFT_MAP:
        return SHIFT_MAP[label]
    return label                          # angka dan tanda baca tidak berubah


def apply_key(label: str, typed: str, caps: bool, shift: bool):
    """Proses satu tekanan tombol. Return (typed, caps, shift, saved)."""
    saved = False
    if label == "DEL":
        typed = typed[:-1]
        if _pynput:
            _sys_kb.press(_Key.backspace)
            _sys_kb.release(_Key.backspace)
    elif label == "SPC":
        typed += " "
        if _pynput:
            _sys_kb.type(" ")
    elif label == "CAPS":
        caps = not caps
    elif label == "SHIFT":
        shift = not shift
    elif label == "SAVE":
        Path("output.txt").write_text(typed, encoding="utf-8")
        print("  [SAVED] → output.txt")
        saved = True
    else:
        char = resolve_char(label, caps, shift)
        typed += char
        if _pynput:
            _sys_kb.type(char)
        if shift:
            shift = False               # SHIFT one-shot: mati setelah satu huruf
    print(f"  KEY:{label!r:6}  →  {typed!r}")
    return typed, caps, shift, saved


# ─── Drawing ─────────────────────────────────────────────────────────────────
def draw_keyboard(frame, buttons, hover_set, click_set,
                  typed, caps, shift, dwell_mode, dwell_label, dwell_frac):
    """Render keyboard virtual + text box ke frame."""

    kbd_x2 = START_X + 10 * STEP - GAP + 10
    kbd_y2 = START_Y +  5 * STEP - GAP + 10

    # Latar belakang semi-transparan
    overlay = frame.copy()
    cv2.rectangle(overlay, (START_X - 15, START_Y - 15),
                  (kbd_x2, kbd_y2), C["bg"], -1)
    cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)

    for btn in buttons:
        lbl = btn.label

        # Warna tombol
        if lbl in click_set:
            col = C["clicked"]
        elif lbl == "CAPS" and caps:
            col = C["caps_on"]
        elif lbl == "SHIFT" and shift:
            col = C["shift_on"]
        elif lbl in hover_set:
            col = C["hover"]
        else:
            col = C["normal"]

        _rounded_rect(frame, btn.x, btn.y, btn.w, btn.h, 6, col)
        _rounded_rect(frame, btn.x, btn.y, btn.w, btn.h, 6, C["border"], 2)

        # Arc dwell di dalam tombol yang sedang di-hover
        if dwell_mode and lbl == dwell_label and dwell_frac > 0:
            cx = btn.x + btn.w // 2
            cy = btn.y + btn.h // 2
            r  = min(btn.w, btn.h) // 2 - 4
            cv2.ellipse(frame, (cx, cy), (r, r),
                        -90, 0, int(360 * dwell_frac), C["dwell_ring"], 3)

        # Label (tampilkan simbol shift jika SHIFT aktif)
        disp = SHIFT_MAP.get(lbl, lbl) if (shift and lbl in SHIFT_MAP) else lbl
        n = len(disp)
        fs = 0.72 if n == 1 else 0.52 if n <= 3 else 0.44

        (tw, th), _ = cv2.getTextSize(disp, cv2.FONT_HERSHEY_SIMPLEX, fs, 2)
        tx = btn.x + (btn.w - tw) // 2
        ty = btn.y + (btn.h + th) // 2
        cv2.putText(frame, disp, (tx, ty),
                    cv2.FONT_HERSHEY_SIMPLEX, fs, (255, 255, 255), 2)

    # Kotak teks output — ATAS layar (di bawah HUD), bukan di bawah keyboard
    tb_y1, tb_y2 = 75, 137
    cv2.rectangle(frame, (START_X - 15, tb_y1), (kbd_x2, tb_y2),
                  C["textbox_bg"], -1)
    cv2.rectangle(frame, (START_X - 15, tb_y1), (kbd_x2, tb_y2),
                  C["border"], 2)
    disp_txt = (typed[-50:] if len(typed) > 50 else typed) + "|"
    cv2.putText(frame, disp_txt, (START_X, tb_y2 - 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.78, (220, 220, 255), 2)


def draw_finger_ui(frame, itip, mtip, hover, last_click_t, now):
    """Titik jari indeks + tengah + arc cooldown + panah flick."""
    # Arc cooldown mengelilingi ujung jari indeks
    frac    = min((now - last_click_t) / CLICK_COOLDOWN, 1.0)
    arc_col = C["ready"] if frac >= 1.0 else C["cooling"]
    cv2.ellipse(frame, itip, (18, 18), -90, 0, int(360 * frac), arc_col, 2)

    # Titik jari indeks (hijau) dan tengah (biru)
    cv2.circle(frame, itip, 14, (0, 255, 150), cv2.FILLED)
    cv2.circle(frame, itip, 14, (255, 255, 255), 2)
    cv2.circle(frame, mtip, 12, (50, 160, 255), cv2.FILLED)
    cv2.circle(frame, mtip, 12, (255, 255, 255), 2)

    # Panah ke bawah di jari tengah — petunjuk arah gesture flick
    ax, ay = mtip[0], mtip[1] + 20
    cv2.arrowedLine(frame, (ax, ay - 14), (ax, ay + 2),
                    (150, 150, 255), 2, tipLength=0.45)

    # Label tombol yang di-hover (muncul di samping jari indeks)
    if hover:
        cv2.putText(frame, f"[{hover}]", (itip[0] + 18, itip[1] - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.52, arc_col, 1)


def draw_hud(frame, fps, confidences, dwell_mode, caps, shift):
    """HUD bagian atas: FPS, jumlah tangan, mode, status modifier."""
    mode   = "DWELL" if dwell_mode else "FLICK"
    caps_s = "  [CAPS]"  if caps  else ""
    shft_s = "  [SHIFT]" if shift else ""

    kb_s = "  [KB:OS]" if _pynput else "  [KB:OCV]"
    cv2.putText(
        frame,
        f"FPS:{fps:4.1f}   Hands:{len(confidences)}   Mode:{mode}{caps_s}{shft_s}{kb_s}"
        f"   |   D=toggle   ESC/Q=quit",
        (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.54, (180, 210, 255), 1,
    )

    # Confidence bar per tangan
    for i, conf in enumerate(confidences):
        bx  = 20 + i * 180
        by  = 46
        bw  = int(160 * conf)
        cv2.rectangle(frame, (bx, by), (bx + 160, by + 8), (50, 50, 90), -1)
        col = C["ready"] if conf > 0.8 else C["cooling"]
        cv2.rectangle(frame, (bx, by), (bx + bw, by + 8), col, -1)
        cv2.putText(frame, f"H{i+1}: {conf:.0%}",
                    (bx, by + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.42,
                    (180, 210, 255), 1)


# ─── Main loop ───────────────────────────────────────────────────────────────
def main():
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT,  720)

    if not cap.isOpened():
        print("[ERROR] Tidak dapat membuka kamera. Periksa indeks kamera.")
        return

    cv2.namedWindow("AI Virtual Keyboard", cv2.WINDOW_NORMAL)
    cv2.setWindowProperty("AI Virtual Keyboard", cv2.WND_PROP_FULLSCREEN,
                          cv2.WINDOW_FULLSCREEN)

    buttons    = build_keyboard()
    typed      = ""
    caps_lock  = False
    shift_act  = False
    dwell_mode = False

    # State per tangan (maks 2)
    last_click  = [0.0, 0.0]
    click_label = [None, None]
    click_until = [0.0, 0.0]

    # State dwell (hanya tangan pertama)
    dwell_label = None
    dwell_start = 0.0

    # Riwayat Y jari tengah per tangan untuk deteksi flick
    mtip_history = [deque(maxlen=FLICK_WINDOW), deque(maxlen=FLICK_WINDOW)]

    fps_times = []

    kb_mode = "pynput (mengetik ke OS)" if _pynput else "OpenCV only"
    print(f"AI Virtual Keyboard — siap.  Mode keyboard: {kb_mode}")
    print("D = toggle dwell/flick  |  ESC/Q = keluar")

    while True:
        ok, frame = cap.read()
        if not ok:
            continue

        frame = cv2.flip(frame, 1)
        h, w  = frame.shape[:2]
        now   = time.time()

        # FPS rolling average (frame dalam 1 detik terakhir)
        fps_times = [t for t in fps_times if now - t < 1.0]
        fps_times.append(now)
        fps = len(fps_times)

        # Deteksi tangan
        rgb    = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        result = hand_detector.process(rgb)

        hands_data  = []   # [(index_tip, middle_tip), ...]
        confidences = []

        if result.multi_hand_landmarks:
            for idx, hl in enumerate(result.multi_hand_landmarks):
                lm   = hl.landmark
                itip = (int(lm[8].x  * w), int(lm[8].y  * h))
                mtip = (int(lm[12].x * w), int(lm[12].y * h))
                conf = result.multi_handedness[idx].classification[0].score

                hands_data.append((itip, mtip))
                confidences.append(conf)

                _mp_draw.draw_landmarks(
                    frame, hl, _mp_hands.HAND_CONNECTIONS,
                    _mp_styles.get_default_hand_landmarks_style(),
                    _mp_styles.get_default_hand_connections_style(),
                )

        # Reset state saat tidak ada tangan terdeteksi
        if not hands_data:
            dwell_label = None
            dwell_start = 0.0
            for h in mtip_history:
                h.clear()

        # Hapus flash klik yang kadaluarsa
        for i in range(2):
            if now > click_until[i]:
                click_label[i] = None

        hover_set   = set()
        click_set   = {lbl for lbl in click_label if lbl}
        hand_hovers = []

        # ── Proses setiap tangan ───────────────────────────────────────────
        for hi, (itip, mtip) in enumerate(hands_data):
            # Cari tombol yang di-hover
            hov = next((btn.label for btn in buttons if btn.hit(*itip)), None)
            hand_hovers.append(hov)
            if hov:
                hover_set.add(hov)

            # Mode Flick: jari tengah flick ke bawah saat jari indeks hover
            if not dwell_mode and hi < 2:
                # Lacak Y RELATIF (tengah - indeks) bukan Y absolut:
                # kalau tangan bergerak, kedua jari ikut → selisih tetap → tidak trigger
                mtip_history[hi].append(mtip[1] - itip[1])
                hist = mtip_history[hi]
                if hov and len(hist) >= 2:
                    h = list(hist)
                    flick_dy = h[-1] - min(h[:-1])
                    if flick_dy > FLICK_THRESHOLD and (now - last_click[hi]) > CLICK_COOLDOWN:
                        last_click[hi]  = now
                        click_label[hi] = hov
                        click_until[hi] = now + 0.18
                        click_set.add(hov)
                        mtip_history[hi].clear()   # reset agar tidak langsung re-fire
                        typed, caps_lock, shift_act, _ = apply_key(
                            hov, typed, caps_lock, shift_act)

        # ── Mode Dwell (hanya tangan pertama) ─────────────────────────────
        dwell_frac = 0.0
        if dwell_mode and hands_data:
            itip = hands_data[0][0]
            hov  = hand_hovers[0] if hand_hovers else None

            # Reset timer saat pindah ke tombol lain
            if hov != dwell_label:
                dwell_label = hov
                dwell_start = now

            if hov:
                dwell_frac = min((now - dwell_start) / DWELL_TIME, 1.0)
                if dwell_frac >= 1.0 and (now - last_click[0]) > CLICK_COOLDOWN:
                    last_click[0]  = now
                    click_label[0] = hov
                    click_until[0] = now + 0.18
                    click_set.add(hov)
                    dwell_start = now      # reset agar tidak langsung re-fire
                    typed, caps_lock, shift_act, _ = apply_key(
                        hov, typed, caps_lock, shift_act)

        # ── Render ────────────────────────────────────────────────────────
        draw_hud(frame, fps, confidences, dwell_mode, caps_lock, shift_act)

        draw_keyboard(frame, buttons, hover_set, click_set,
                      typed, caps_lock, shift_act,
                      dwell_mode, dwell_label, dwell_frac)

        if hands_data:
            primary_hov = hand_hovers[0] if hand_hovers else None
            draw_finger_ui(frame, hands_data[0][0], hands_data[0][1],
                           primary_hov, last_click[0], now)

        cv2.imshow("AI Virtual Keyboard", frame)

        key = cv2.waitKey(1) & 0xFF
        if key in (27, ord("q"), ord("Q")):
            break
        elif key in (ord("d"), ord("D")):
            dwell_mode  = not dwell_mode
            dwell_label = None
            dwell_start = 0.0
            print(f"  Mode → {'DWELL' if dwell_mode else 'FLICK'}")

    cap.release()
    cv2.destroyAllWindows()
    print(f"\nTeks akhir: {typed!r}")


if __name__ == "__main__":
    main()
