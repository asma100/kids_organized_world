"""
omr_scanner.py  (v3)
────────────────────
Key fixes over v2:
  • Samples in HSV + grayscale so any dark OR colorful fill is detected
    (pen marks, Photoshop fill, highlighter, crayon, etc.)
  • DARK_FRACTION_REQUIRED lowered to 0.15 — lighter marks now count
  • debug_scan_image() now returns a JPEG overlay image showing every
    checkbox region with a GREEN (detected) or RED (empty) circle
    so you can see exactly what the scanner is looking at
  • Checkbox sampling radius expanded by 20% to catch slight alignment drift
"""

import io
import numpy as np
from dataclasses import dataclass, field
from datetime import date as date_type, datetime
from typing import Optional


# ── Tunable constants ─────────────────────────────────────────────────────────

# A checkbox is considered FILLED when at least this fraction of pixels
# inside the sampling circle are "marked" (dark or saturated color).
# 0.15 = 15% — works for light pencil, colored fill, pen ticks
DARK_FRACTION_REQUIRED = 0.200

# Grayscale brightness threshold: pixels BELOW this are "dark"
GRAY_DARK_THRESHOLD = 210

# HSV saturation threshold: pixels ABOVE this are "colorful" (counts as filled)
# Catches Photoshop bucket-fill, highlighter, crayon even if they're bright
COLOR_SAT_THRESHOLD = 40

# Multiply the stored checkbox radius by this when sampling
# (catches slight warping drift without false positives)
RADIUS_SCALE = 1.5


@dataclass
class ProcessResult:
    success: bool = False
    sheet_uuid: str = ""
    sheet_date: Optional[date_type] = None
    tasks_updated: list = field(default_factory=list)
    tasks_skipped: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    debug_info: list = field(default_factory=list)


# ── Public entry point ────────────────────────────────────────────────────────

def process_scanned_sheet(image_bytes: bytes, current_user) -> ProcessResult:
    result = ProcessResult()

    try:
        import cv2
    except ImportError:
        result.errors.append("opencv-python-headless is not installed.")
        return result

    nparr = np.frombuffer(image_bytes, np.uint8)
    img   = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        result.errors.append("Could not decode image.")
        return result

    result.debug_info.append(f"Image: {img.shape[1]}×{img.shape[0]}px")

    # Decode QR
    sheet_uuid, qr_debug = _decode_qr_robust(img)
    result.debug_info.extend(qr_debug)

    if not sheet_uuid:
        result.errors.append("❌ QR code not found. Visit /scan/debug to diagnose.")
        return result

    result.sheet_uuid = sheet_uuid

    # Load sheet
    from app.models import TaskSheet, TaskCheckbox, Task
    from app import db

    sheet = TaskSheet.query.filter_by(
        sheet_uuid=sheet_uuid, user_id=current_user.id
    ).first()
    if not sheet:
        result.errors.append(f"Sheet {sheet_uuid[:8]}… not found for this account.")
        return result

    result.sheet_date = sheet.sheet_date
    checkboxes = TaskCheckbox.query.filter_by(sheet_id=sheet.id).all()
    if not checkboxes:
        result.errors.append("No checkboxes recorded for this sheet.")
        return result

    # Warp
    from app.omr_pdf import (TEMPLATE_WIDTH_PX, TEMPLATE_HEIGHT_PX,
                              get_template_marker_centres)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    warped_color, warped_gray, warp_debug = _detect_and_warp(
        img, TEMPLATE_WIDTH_PX, TEMPLATE_HEIGHT_PX,
        get_template_marker_centres()
    )
    result.debug_info.extend(warp_debug)

    if warped_color is None:
        result.debug_info.append("Corner warp failed — using rescaled image.")
        warped_color = cv2.resize(img,   (TEMPLATE_WIDTH_PX, TEMPLATE_HEIGHT_PX))
        warped_gray  = cv2.resize(gray,  (TEMPLATE_WIDTH_PX, TEMPLATE_HEIGHT_PX))

    # Sample checkboxes
    from app.taskManagement import toggle_task_for_date

    for cb in checkboxes:
        task = Task.query.get(cb.task_id)
        if not task:
            continue

        radius    = int(cb.radius * RADIUS_SCALE)
        is_filled, fraction = _sample_checkbox(warped_color, warped_gray,
                                               cb.cx, cb.cy, radius)
        current_done = _get_current_state(task, sheet.sheet_date)

        result.debug_info.append(
            f"  '{task.title}': filled={is_filled} "
            f"(dark/color fraction={fraction:.2f}, threshold={DARK_FRACTION_REQUIRED})"
        )

        if is_filled and not current_done:
            toggle_task_for_date(cb.task_id, sheet.sheet_date)
            result.tasks_updated.append(f"✅ {task.title}")
        elif not is_filled and current_done:
            toggle_task_for_date(cb.task_id, sheet.sheet_date)
            result.tasks_updated.append(f"↩ {task.title} (un-checked)")
        else:
            result.tasks_skipped.append(task.title)

    sheet.processed    = True
    sheet.processed_at = datetime.utcnow()
    db.session.commit()

    # Recalculate points now that task states have changed
    from app.pointsys import total_task_points
    total_task_points(current_user.id)

    result.success = True
    return result


# ── Checkbox sampling (grayscale + color) ─────────────────────────────────────

def _sample_checkbox(img_bgr, gray, cx, cy, radius):
    """
    Returns (is_filled: bool, fraction: float).

    A pixel counts as "marked" if EITHER:
      • its grayscale value < GRAY_DARK_THRESHOLD  (dark pen, pencil, black fill)
      • its HSV saturation  > COLOR_SAT_THRESHOLD  (color fill, highlighter)

    This means ANY mark — dark or bright colored — triggers detection.
    """
    h, w = gray.shape
    x1, x2 = max(0, cx - radius), min(w, cx + radius + 1)
    y1, y2 = max(0, cy - radius), min(h, cy + radius + 1)

    if x2 <= x1 or y2 <= y1:
        return False, 0.0

    roi_gray  = gray[y1:y2, x1:x2]
    roi_color = img_bgr[y1:y2, x1:x2]
    roi_hsv   = _bgr_to_hsv(roi_color)

    # Circular mask
    ys, xs   = np.mgrid[y1:y2, x1:x2]
    dist     = np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2)
    rh, rw   = roi_gray.shape
    mask     = (dist[:rh, :rw]) <= radius

    total_px = int(mask.sum())
    if total_px == 0:
        return False, 0.0

    # Dark pixels (grayscale)
    dark_mask  = (roi_gray < GRAY_DARK_THRESHOLD) & mask

    # Colorful pixels (saturation channel of HSV)
    sat        = roi_hsv[:, :, 1]
    color_mask = (sat > COLOR_SAT_THRESHOLD) & mask

    # Union: dark OR colorful
    marked    = dark_mask | color_mask
    fraction  = float(marked.sum()) / total_px

    return fraction >= DARK_FRACTION_REQUIRED, fraction


def _bgr_to_hsv(roi_bgr):
    try:
        import cv2
        return cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
    except Exception:
        # Fallback: rough HSV without OpenCV
        r = roi_bgr[:, :, 2].astype(float) / 255
        g = roi_bgr[:, :, 1].astype(float) / 255
        b = roi_bgr[:, :, 0].astype(float) / 255
        maxc = np.maximum(np.maximum(r, g), b)
        minc = np.minimum(np.minimum(r, g), b)
        sat  = np.where(maxc != 0, (maxc - minc) / maxc, 0)
        return np.dstack([maxc, sat, maxc])  # approximate


# ── Debug: produce annotated JPEG showing where boxes are sampled ─────────────

def debug_scan_image(image_bytes: bytes, current_user=None) -> dict:
    """
    Returns:
      {
        image_size, qr_found, qr_uuid, qr_debug, warp_debug,
        checkbox_results: [ {title, cx, cy, fraction, filled}, … ],
        annotated_jpeg: bytes | None   ← JPEG with colored circles drawn on it
      }
    """
    import cv2

    nparr = np.frombuffer(image_bytes, np.uint8)
    img   = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return {"error": "Could not decode image"}

    h, w  = img.shape[:2]
    gray  = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    uuid_val, qr_debug = _decode_qr_robust(img)

    from app.omr_pdf import (TEMPLATE_WIDTH_PX, TEMPLATE_HEIGHT_PX,
                              get_template_marker_centres)

    warped_color, warped_gray, warp_debug = _detect_and_warp(
        img, TEMPLATE_WIDTH_PX, TEMPLATE_HEIGHT_PX,
        get_template_marker_centres()
    )
    if warped_color is None:
        warped_color = cv2.resize(img,  (TEMPLATE_WIDTH_PX, TEMPLATE_HEIGHT_PX))
        warped_gray  = cv2.resize(gray, (TEMPLATE_WIDTH_PX, TEMPLATE_HEIGHT_PX))

    # Draw annotation on the warped image
    annotated    = warped_color.copy()
    cb_results   = []

    if uuid_val and current_user:
        from app.models import TaskSheet, TaskCheckbox, Task
        sheet = TaskSheet.query.filter_by(
            sheet_uuid=uuid_val, user_id=current_user.id
        ).first()

        if sheet:
            checkboxes = TaskCheckbox.query.filter_by(sheet_id=sheet.id).all()
            for cb in checkboxes:
                task   = Task.query.get(cb.task_id)
                radius = int(cb.radius * RADIUS_SCALE)
                filled, fraction = _sample_checkbox(
                    warped_color, warped_gray, cb.cx, cb.cy, radius
                )
                # Green = detected filled, Red = detected empty
                color = (0, 200, 0) if filled else (0, 0, 220)
                cv2.circle(annotated, (cb.cx, cb.cy), radius, color, 3)
                cv2.circle(annotated, (cb.cx, cb.cy), 3,      color, -1)

                label = f"{fraction:.2f}"
                cv2.putText(annotated, label,
                            (cb.cx + radius + 4, cb.cy + 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1,
                            cv2.LINE_AA)

                cb_results.append({
                    "title":    task.title if task else f"task_{cb.task_id}",
                    "cx":       cb.cx,
                    "cy":       cb.cy,
                    "fraction": round(fraction, 3),
                    "filled":   filled,
                })

    # Encode annotated image as JPEG bytes
    _, jpeg_buf = cv2.imencode('.jpg', annotated,
                               [cv2.IMWRITE_JPEG_QUALITY, 85])
    annotated_jpeg = jpeg_buf.tobytes() if jpeg_buf is not None else None

    return {
        "image_size":      f"{w}×{h}",
        "qr_found":        uuid_val is not None,
        "qr_uuid":         uuid_val[:8] + "…" if uuid_val else None,
        "qr_debug":        qr_debug,
        "warp_debug":      warp_debug,
        "checkbox_results": cb_results,
        "annotated_jpeg":  annotated_jpeg,
    }


# ── QR decoding ───────────────────────────────────────────────────────────────

def _decode_qr_robust(img_bgr):
    import cv2
    debug = []
    gray  = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    h, w  = gray.shape

    candidates = [
        ("raw gray",                        gray),
        ("upscaled ×2",                     cv2.resize(gray, (w*2, h*2), interpolation=cv2.INTER_CUBIC)),
        ("upscaled ×3",                     cv2.resize(gray, (w*3, h*3), interpolation=cv2.INTER_CUBIC)),
        ("sharpened",                        cv2.filter2D(gray, -1, np.array([[0,-1,0],[-1,5,-1],[0,-1,0]]))),
        ("adaptive threshold",              cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY,51,10)),
        ("CLAHE",                           cv2.createCLAHE(clipLimit=3.0,tileGridSize=(8,8)).apply(gray)),
    ]

    # sharpened + upscaled
    sharp = cv2.filter2D(gray, -1, np.array([[0,-1,0],[-1,5,-1],[0,-1,0]]))
    candidates.append(("sharpened + upscaled ×2",
                        cv2.resize(sharp, (w*2, h*2), interpolation=cv2.INTER_CUBIC)))

    detector = cv2.QRCodeDetector()
    for name, cand in candidates:
        try:
            data, _, _ = detector.detectAndDecode(cand)
            if data and data.startswith("KOW:"):
                debug.append(f"✓ QR found with: {name}")
                return data[4:], debug
        except Exception:
            pass

    # Color upscales
    for scale, name in [(2,"color ×2"),(3,"color ×3")]:
        try:
            up   = cv2.resize(img_bgr, (w*scale, h*scale), interpolation=cv2.INTER_CUBIC)
            data, _, _ = detector.detectAndDecode(up)
            if data and data.startswith("KOW:"):
                debug.append(f"✓ QR found with: {name}")
                return data[4:], debug
        except Exception:
            pass

    # pyzbar fallback
    try:
        from pyzbar import pyzbar
        for name, cand in candidates:
            for bc in pyzbar.decode(cand):
                text = bc.data.decode('utf-8', errors='ignore')
                if text.startswith("KOW:"):
                    debug.append(f"✓ QR found via pyzbar with: {name}")
                    return text[4:], debug
    except ImportError:
        debug.append("pyzbar not installed (optional)")
    except Exception as e:
        debug.append(f"pyzbar error: {e}")

    debug.append("✗ QR not found in any preprocessing.")
    return None, debug


# ── Corner detection & warp ───────────────────────────────────────────────────

def _detect_and_warp(img_color, template_w, template_h, template_markers):
    import cv2

    gray  = cv2.cvtColor(img_color, cv2.COLOR_BGR2GRAY)
    debug = []
    found = []

    for thresh_val in [40, 60, 80, 100, 120]:
        _, binary = cv2.threshold(gray, thresh_val, 255, cv2.THRESH_BINARY_INV)
        pts = _find_marker_circles(binary, gray.shape[1])
        if len(pts) >= 4:
            found = pts
            debug.append(f"✓ Corner markers found at threshold {thresh_val}")
            break

    if len(found) < 4:
        debug.append(f"✗ Only {len(found)} corner marker(s) found (need 4).")
        return None, None, debug

    tl, tr, bl, br = _sort_corners([(p[0], p[1]) for p in found[:4]])
    src = np.float32([tl, tr, bl, br])
    dst = np.float32([[0,0],[template_w,0],[0,template_h],[template_w,template_h]])
    M   = cv2.getPerspectiveTransform(src, dst)
    warped_color = cv2.warpPerspective(img_color, M, (template_w, template_h))
    warped_gray  = cv2.cvtColor(warped_color, cv2.COLOR_BGR2GRAY)
    debug.append("✓ Perspective warp applied.")
    return warped_color, warped_gray, debug


def _find_marker_circles(binary, img_width):
    import cv2
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    min_a = (img_width * 0.007) ** 2
    max_a = (img_width * 0.12)  ** 2
    found = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if not (min_a < area < max_a):
            continue
        peri = cv2.arcLength(cnt, True)
        if peri == 0:
            continue
        if 4 * np.pi * area / peri**2 < 0.50:
            continue
        M = cv2.moments(cnt)
        if M['m00'] == 0:
            continue
        found.append((int(M['m10']/M['m00']), int(M['m01']/M['m00']), area))
    found.sort(key=lambda x: -x[2])
    return found[:4]


def _sort_corners(pts):
    pts    = sorted(pts, key=lambda p: p[1])
    top    = sorted(pts[:2], key=lambda p: p[0])
    bottom = sorted(pts[2:], key=lambda p: p[0])
    return top[0], top[1], bottom[0], bottom[1]


def _get_current_state(task, target_date) -> bool:
    from app.models import TaskOccurrence
    if task.is_recurring():
        occ = TaskOccurrence.query.filter_by(
            task_id=task.task_id, occurrence_date=target_date
        ).first()
        return occ.completed if occ else False
    return task.completion_status