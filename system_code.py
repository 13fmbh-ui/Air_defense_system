import math
import time
import cv2
import numpy as np
import serial

PORT = "COM5"
BAUD = 9600
CAM_INDEX = 0

try:
    arduino = serial.Serial(port=PORT, baudrate=BAUD, timeout=0.1)
    time.sleep(2)
    print("Arduino connected successfully!")
except Exception as e:
    print(f"Error connecting to Arduino: {e}")
    arduino = None

cap = cv2.VideoCapture(CAM_INDEX, cv2.CAP_DSHOW)
cam_width, cam_height = 640, 480
CX, CY = cam_width // 2, cam_height // 2

cap.set(cv2.CAP_PROP_FRAME_WIDTH, cam_width)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cam_height)

Kp = 0.05
Ki = 0.001
Kd = 0.8

MAX_STEP = 2.0
DEAD_ZONE = 25
LOCK_ZONE = 20
I_CLAMP = 50.0

x_angle = 90
y_angle = 45

integral_x = 0.0
prev_error_x = 0.0
integral_y = 0.0
prev_error_y = 0.0

# ── HUD Palette (BGR) ─────────────────────────────
C_GREEN = (100, 220, 140)  # primary accent
C_DIM = (25, 70, 35)  # grid / rings
C_RED = (50, 50, 210)  # lock / fire
C_AMBER = (20, 160, 220)  # warning / tracking
C_BLACK = (5, 12, 20)  # panel fill
C_PANEL = (10, 30, 18)  # slightly lighter panel
C_WHITE = (200, 230, 210)  # readout text
# ──────────────────────────────────────────────────

FONT = cv2.FONT_HERSHEY_SIMPLEX
FONT_M = cv2.FONT_HERSHEY_DUPLEX


def draw_bracket(frame, cx, cy, size, color, thickness=1):
    """Draw 4-corner L-shaped targeting bracket around (cx, cy)."""
    arm = size // 3
    tl = (cx - size, cy - size)
    tr = (cx + size, cy - size)
    bl = (cx - size, cy + size)
    br = (cx + size, cy + size)
    for corner, dx, dy in [
        (tl, arm, 0),
        (tl, 0, arm),
        (tr, -arm, 0),
        (tr, 0, arm),
        (bl, arm, 0),
        (bl, 0, -arm),
        (br, -arm, 0),
        (br, 0, -arm),
    ]:
        cv2.line(frame, corner, (corner[0] + dx, corner[1] + dy), color, thickness)


def draw_crosshair(frame, cx, cy, color, size=18):
    """Draw a fine crosshair at (cx, cy)."""
    cv2.line(frame, (cx - size, cy), (cx + size, cy), color, 1)
    cv2.line(frame, (cx, cy - size), (cx, cy + size), color, 1)
    cv2.circle(frame, (cx, cy), 3, color, -1)


def draw_panel_bg(frame, x, y, w, h, color=C_PANEL, alpha=0.55):
    """Semi-transparent filled rectangle for HUD panels."""
    overlay = frame.copy()
    cv2.rectangle(overlay, (x, y), (x + w, y + h), color, -1)
    cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)
    cv2.rectangle(frame, (x, y), (x + w, y + h), C_DIM, 1)


def draw_bar(frame, x, y, w, h, pct, color):
    """Filled progress bar (0.0–1.0)."""
    cv2.rectangle(frame, (x, y), (x + w, y + h), C_DIM, -1)
    fill_w = int(w * max(0.0, min(1.0, pct)))
    if fill_w > 0:
        cv2.rectangle(frame, (x, y), (x + fill_w, y + h), color, -1)
    cv2.rectangle(frame, (x, y), (x + w, y + h), C_DIM, 1)


def put_text(frame, text, pos, font=FONT, scale=0.38, color=C_WHITE, thickness=1):
    cv2.putText(frame, text, pos, font, scale, color, thickness, cv2.LINE_AA)


def put_label(frame, text, pos, color=None):
    """Tiny uppercase label."""
    put_text(frame, text, pos, scale=0.32, color=color or (70, 140, 90))


def draw_grid(frame):
    """Dim background grid + range rings."""
    step = 40
    for x in range(0, cam_width, step):
        cv2.line(frame, (x, 0), (x, cam_height), C_DIM, 1)
    for y in range(0, cam_height, step):
        cv2.line(frame, (0, y), (cam_width, y), C_DIM, 1)
    for r in [60, 120, 180]:
        cv2.circle(frame, (CX, CY), r, C_DIM, 1)
    cv2.line(frame, (CX, 0), (CX, cam_height), (35, 90, 50), 1)
    cv2.line(frame, (0, CY), (cam_width, CY), (35, 90, 50), 1)


def draw_scan_sweep(frame, angle):
    """Rotating radar sweep line from center."""
    end_x = int(CX + 200 * math.cos(angle))
    end_y = int(CY + 200 * math.sin(angle))
    overlay = frame.copy()
    cv2.line(overlay, (CX, CY), (end_x, end_y), (60, 180, 100), 1)
    cv2.addWeighted(overlay, 0.25, frame, 0.75, 0, frame)


def draw_top_bar(frame, locked, tracking):
    """Top status bar."""
    draw_panel_bg(frame, 0, 0, cam_width, 22, C_BLACK, 0.75)
    put_text(
        frame,
        "AD-7  AIR DEFENSE TERMINAL",
        (8, 15),
        font=FONT_M,
        scale=0.38,
        color=C_GREEN,
    )
    ts = time.strftime("%H:%M:%SZ", time.gmtime())
    put_text(frame, ts, (cam_width - 80, 15), scale=0.35, color=(70, 140, 90))
    if locked:
        label, color = "[ TARGET LOCKED ]", C_RED
    elif tracking:
        label, color = "[ TRACKING ]", C_AMBER
    else:
        label, color = "[ SCANNING ]", (70, 140, 90)
    tw, _ = cv2.getTextSize(label, FONT, 0.35, 1)[0], None
    put_text(frame, label, (cam_width // 2 - 55, 15), scale=0.35, color=color)


def draw_axis_panel(frame, x_ang, y_ang, err_mag, locked):
    """Bottom-left: azimuth / elevation / error readouts."""
    px, py, pw, ph = 6, cam_height - 72, 210, 66
    draw_panel_bg(frame, px, py, pw, ph)
    put_label(frame, "AZIMUTH (X)", (px + 6, py + 11))
    put_label(frame, "ELEVATION (Y)", (px + 76, py + 11))
    put_label(frame, "ERROR", (px + 156, py + 11))
    xc = C_RED if locked else C_GREEN
    put_text(
        frame,
        f"{x_ang:03d}",
        (px + 6, py + 32),
        font=FONT_M,
        scale=0.7,
        color=xc,
        thickness=1,
    )
    put_text(
        frame,
        f"{y_ang:03d}",
        (px + 76, py + 32),
        font=FONT_M,
        scale=0.7,
        color=xc,
        thickness=1,
    )
    ec = C_RED if err_mag > 80 else C_AMBER if err_mag > 40 else C_GREEN
    put_text(
        frame,
        f"{err_mag}px",
        (px + 152, py + 32),
        font=FONT_M,
        scale=0.55,
        color=ec,
        thickness=1,
    )
    put_label(frame, "deg", (px + 52, py + 32))
    put_label(frame, "deg", (px + 120, py + 32))
    put_label(frame, "SECTOR 7", (px + 6, py + 56))
    put_label(frame, f"KP {Kp:.3f}  KI {Ki:.3f}  KD {Kd:.3f}", (px + 56, py + 56))


def draw_pid_panel(frame, p_val, i_val, d_val):
    """Bottom-right: PID contribution bars."""
    pw, ph = 160, 66
    px = cam_width - pw - 6
    py = cam_height - ph - 6
    draw_panel_bg(frame, px, py, pw, ph)
    put_label(frame, "PID MONITOR", (px + 6, py + 11))
    bar_w, bar_h = 90, 5
    bx = px + 36
    for idx, (tag, val) in enumerate([("P", p_val), ("I", i_val), ("D", d_val)]):
        by = py + 20 + idx * 16
        pct = min(1.0, abs(val) / 5.0)
        bc = C_RED if pct > 0.7 else C_AMBER if pct > 0.4 else C_GREEN
        put_label(frame, tag, (px + 6, by + 6))
        draw_bar(frame, bx, by, bar_w, bar_h, pct, bc)
        put_label(frame, f"{val:+.2f}", (bx + bar_w + 4, by + 6))


def draw_detection_panel(frame, area, contour_count, confidence):
    """Top-right corner: detection stats."""
    pw, ph = 148, 54
    px = cam_width - pw - 6
    py = 28
    draw_panel_bg(frame, px, py, pw, ph)
    put_label(frame, "DETECTION", (px + 6, py + 11))
    put_label(frame, "AREA", (px + 6, py + 25))
    put_label(frame, "CONTOURS", (px + 6, py + 38))
    put_label(frame, "CONF", (px + 6, py + 51))
    put_text(frame, f"{area}px2", (px + 58, py + 25), scale=0.34, color=C_WHITE)
    put_text(frame, str(contour_count), (px + 58, py + 38), scale=0.34, color=C_WHITE)
    conf_c = C_GREEN if confidence > 70 else C_AMBER if confidence > 40 else C_RED
    put_text(frame, f"{confidence}%", (px + 58, py + 51), scale=0.34, color=conf_c)


def draw_fire_flash(frame):
    """Full-frame red tint flash when firing."""
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (cam_width, cam_height), (0, 0, 180), -1)
    cv2.addWeighted(overlay, 0.12, frame, 0.88, 0, frame)
    put_text(
        frame,
        "FIRE",
        (CX - 30, CY - 30),
        font=FONT_M,
        scale=1.2,
        color=C_RED,
        thickness=2,
    )


print("System Active — AD-7 Full PID Tracking")

if not cap.isOpened():
    print("Error: Camera not found.")
    exit()

sweep_angle = 0.0

try:
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        sweep_angle = (sweep_angle + 0.04) % (2 * math.pi)

        draw_grid(frame)
        draw_scan_sweep(frame, sweep_angle)

        blurred = cv2.GaussianBlur(frame, (11, 11), 0)
        hsv = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)

        lower_red1 = np.array([0, 120, 70])
        upper_red1 = np.array([10, 255, 255])
        lower_red2 = np.array([170, 120, 70])
        upper_red2 = np.array([180, 255, 255])

        mask = cv2.inRange(hsv, lower_red1, upper_red1) + cv2.inRange(
            hsv, lower_red2, upper_red2
        )
        mask = cv2.erode(mask, None, iterations=2)
        mask = cv2.dilate(mask, None, iterations=2)

        contours, _ = cv2.findContours(
            mask.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        fire = 0
        target_locked = False
        tracking = False
        area = 0
        confidence = 0
        p_out = i_out = d_out = 0.0
        err_mag = 0

        if contours:
            largest = max(contours, key=cv2.contourArea)
            area = int(cv2.contourArea(largest))

            if area > 500:
                tracking = True
                x, y, w, h = cv2.boundingRect(largest)
                M = cv2.moments(largest)

                if M["m00"] != 0:
                    cx = int(M["m10"] / M["m00"])
                    cy = int(M["m01"] / M["m00"])

                    error_x = cx - CX
                    error_y = cy - CY
                    err_mag = int(math.sqrt(error_x**2 + error_y**2))
                    confidence = min(99, int(100 - err_mag / 5))

                    if abs(error_x) > DEAD_ZONE:
                        integral_x = max(-I_CLAMP, min(I_CLAMP, integral_x + error_x))
                        deriv_x = error_x - prev_error_x
                        p_out = Kp * error_x
                        i_out = Ki * integral_x
                        d_out = Kd * deriv_x
                        step_x = max(-MAX_STEP, min(MAX_STEP, p_out + i_out + d_out))
                        x_angle -= step_x
                    else:
                        integral_x = 0.0
                    prev_error_x = error_x

                    if abs(error_y) > DEAD_ZONE:
                        integral_y = max(-I_CLAMP, min(I_CLAMP, integral_y + error_y))
                        deriv_y = error_y - prev_error_y
                        py_out = Kp * error_y
                        iy_out = Ki * integral_y
                        dy_out = Kd * deriv_y
                        step_y = max(-MAX_STEP, min(MAX_STEP, py_out + iy_out + dy_out))
                        y_angle -= step_y
                    else:
                        integral_y = 0.0
                    prev_error_y = error_y

                    x_angle = max(0, min(180, int(x_angle)))
                    y_angle = max(45, min(180, int(y_angle)))

                    if abs(error_x) < LOCK_ZONE and abs(error_y) < LOCK_ZONE:
                        fire = 1
                        target_locked = True

                    color = C_RED if target_locked else C_GREEN
                    draw_bracket(frame, cx, cy, 24, color, thickness=2)
                    draw_crosshair(frame, cx, cy, color)

                    draw_panel_bg(frame, cx + 28, cy - 12, 72, 16, C_BLACK, 0.7)
                    put_text(
                        frame, f"{cx},{cy}", (cx + 32, cy + 2), scale=0.32, color=color
                    )

        else:
            integral_x *= 0.95
            integral_y *= 0.95

        draw_top_bar(frame, target_locked, tracking)
        draw_axis_panel(
            frame, x_angle, y_angle, err_mag if tracking else 0, target_locked
        )
        draw_pid_panel(frame, p_out, i_out, d_out)
        draw_detection_panel(frame, area, len(contours), confidence)

        if fire:
            draw_fire_flash(frame)

        if arduino and arduino.is_open:
            arduino.write(f"{x_angle},{y_angle},{fire}\n".encode())

        cv2.imshow("AD-7 Air Defense Terminal", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

finally:
    print("Shutting down AD-7...")
    cap.release()
    if arduino:
        arduino.close()
    cv2.destroyAllWindows()
