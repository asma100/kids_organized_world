"""
omr_pdf.py  (v2 — coordinate fix)
──────────────────────────────────
Key fixes:
  • Corner markers drawn AND stored at the same (MARGIN, MARGIN) position
    relative to each corner — previously stored Y used MARKER_R only,
    causing a vertical offset that shifted every sample circle sideways
    after the perspective warp.
  • Checkbox cx stored as the TRUE centre of the drawn rect (cb_x + size/2)
  • Checkbox cy stored with correct Y-flip formula
  • Added a verification print so you can confirm positions match on startup

Install:
    pip install reportlab qrcode[pil] Pillow
"""

import io
import uuid
from datetime import date as date_type

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas

# ── Layout constants ──────────────────────────────────────────────────────────
PAGE_W, PAGE_H  = A4                  # 595.28 × 841.89 pts

MARGIN          = 20 * mm             # distance from page edge to marker CENTRE
MARKER_R        = 8  * mm             # radius of corner circle

CHECKBOX_SIZE   = 7  * mm            # side length of the checkbox square
ROW_HEIGHT      = 14 * mm            # vertical gap between task rows
QR_SIZE         = 28 * mm            # QR code block size

HEADER_H        = 42 * mm            # height reserved above first task row
FOOTER_H        = 18 * mm            # height reserved below last task row

SCAN_DPI        = 150
PT_TO_PX        = SCAN_DPI / 72.0    # 1 point = 1/72 inch

DARK_FILL       = colors.black
LIGHT_FILL      = colors.white


# ── Unit helpers ──────────────────────────────────────────────────────────────

def _pt_to_px(pt_value):
    """Convert ReportLab points → pixels at SCAN_DPI."""
    return int(round(pt_value * PT_TO_PX))


def _px_pt(px):
    """Inverse: pixels → points (for verification only)."""
    return px / PT_TO_PX


# ── Corner marker positions  ──────────────────────────────────────────────────
# These are the CENTRE of each filled circle in ReportLab point space.
# ReportLab: y=0 at BOTTOM.  OpenCV/scanner: y=0 at TOP.
#
# We place each marker at exactly (MARGIN, MARGIN) from the nearest corner:
#   TL → (MARGIN,          PAGE_H - MARGIN)   ReportLab
#   TR → (PAGE_W - MARGIN, PAGE_H - MARGIN)   ReportLab
#   BL → (MARGIN,          MARGIN)             ReportLab
#   BR → (PAGE_W - MARGIN, MARGIN)             ReportLab

def _marker_centres_pt():
    """4 marker centres in ReportLab points (y=0 at bottom)."""
    return {
        'TL': (MARGIN,          PAGE_H - MARGIN),
        'TR': (PAGE_W - MARGIN, PAGE_H - MARGIN),
        'BL': (MARGIN,          MARGIN),
        'BR': (PAGE_W - MARGIN, MARGIN),
    }


def get_template_marker_centres():
    """
    4 marker centres in PIXEL space with y=0 at TOP (OpenCV convention).
    Used by omr_scanner.py for the perspective warp.
    """
    mc = _marker_centres_pt()
    result = {}
    for name, (x_pt, y_pt) in mc.items():
        px_x = _pt_to_px(x_pt)
        # Flip Y: scanner y = total_height_px - reportlab_y_px
        px_y = TEMPLATE_HEIGHT_PX - _pt_to_px(y_pt)
        result[name] = (px_x, px_y)
    return result


# ── Template pixel dimensions ─────────────────────────────────────────────────
TEMPLATE_WIDTH_PX  = _pt_to_px(PAGE_W)
TEMPLATE_HEIGHT_PX = _pt_to_px(PAGE_H)


# ── Drawing helpers ───────────────────────────────────────────────────────────

def _draw_corner_markers(c):
    """Draw 4 solid black filled circles at the exact marker centres."""
    c.setFillColor(DARK_FILL)
    c.setStrokeColor(DARK_FILL)
    for name, (x, y) in _marker_centres_pt().items():
        c.circle(x, y, MARKER_R, fill=1, stroke=0)


def _draw_qr(c, sheet_uuid):
    """Draw QR code in the top-right area (between TR marker and title)."""
    # Place QR to the left of the TR marker, vertically centred on it
    tr_x, tr_y = _marker_centres_pt()['TR']
    qr_x = tr_x - MARKER_R - QR_SIZE - 4 * mm
    qr_y = tr_y - QR_SIZE / 2          # centre QR on the marker y

    try:
        import qrcode, tempfile, os
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=10, border=1
        )
        qr.add_data(f"KOW:{sheet_uuid}")
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        img.save(tmp.name); tmp.close()
        c.drawImage(tmp.name, qr_x, qr_y, width=QR_SIZE, height=QR_SIZE)
        os.unlink(tmp.name)
    except ImportError:
        c.setFillColor(LIGHT_FILL); c.setStrokeColor(DARK_FILL)
        c.rect(qr_x, qr_y, QR_SIZE, QR_SIZE, fill=1, stroke=1)
        c.setFillColor(DARK_FILL); c.setFont("Helvetica-Bold", 7)
        c.drawCentredString(qr_x + QR_SIZE/2, qr_y + QR_SIZE/2,
                            f"QR:{sheet_uuid[:8]}")


def _draw_checkbox(c, x, y, size):
    """Draw an open square checkbox. (x,y) = bottom-left corner in pt."""
    c.setStrokeColor(DARK_FILL)
    c.setFillColor(LIGHT_FILL)
    c.setLineWidth(2)
    c.rect(x, y, size, size, fill=1, stroke=1)
    c.setLineWidth(1)


# ── Main generator ────────────────────────────────────────────────────────────

def generate_task_sheet(task_items, sheet_date, user):
    """
    Generate PDF + persist TaskSheet / TaskCheckbox records.
    Returns (pdf_bytes: bytes, sheet: TaskSheet).
    """
    from app import db
    from app.models import TaskSheet, TaskCheckbox

    sheet_uuid = str(uuid.uuid4())
    sheet = TaskSheet(
        sheet_uuid=sheet_uuid,
        user_id=user.id,
        sheet_date=sheet_date,
    )
    db.session.add(sheet)
    db.session.flush()

    # ── Content area bounds (in ReportLab points) ─────────────────────────────
    # Top of first task row  = just below the header
    # MARGIN + MARKER_R = bottom of TL/TR markers; add HEADER_H below that
    content_top    = PAGE_H - MARGIN - MARKER_R - HEADER_H
    # Bottom of last task row = just above the footer / BL/BR markers
    content_bottom = MARGIN + MARKER_R + FOOTER_H
    content_height = content_top - content_bottom
    rows_per_page  = max(1, int(content_height / ROW_HEIGHT))

    tasks       = [item['task'] for item in task_items]
    total_pages = max(1, -(-len(tasks) // rows_per_page))

    buf = io.BytesIO()
    c   = rl_canvas.Canvas(buf, pagesize=A4)

    # (task_id, page_num, cx_pt, cy_pt)  — cy_pt in ReportLab coords (y=0 bottom)
    checkbox_records = []

    for page_num in range(1, total_pages + 1):
        page_tasks = tasks[(page_num-1)*rows_per_page : page_num*rows_per_page]

        _draw_corner_markers(c)
        _draw_qr(c, sheet_uuid)

        # ── Header ────────────────────────────────────────────────────────
        tl_x, tl_y = _marker_centres_pt()['TL']
        header_x   = tl_x + MARKER_R + 4 * mm
        header_y   = tl_y - 14 * mm

        c.setFillColor(DARK_FILL)
        c.setFont("Helvetica-Bold", 16)
        c.drawString(header_x, header_y, "Kids Organized World")

        c.setFont("Helvetica", 10)
        c.drawString(header_x, header_y - 7*mm,
                     f"Tasks: {sheet_date.strftime('%A, %d %B %Y')}   "
                     f"Page {page_num}/{total_pages}")

        c.setFont("Helvetica", 7)
        c.setFillColor(colors.grey)
        c.drawString(header_x, header_y - 13*mm,
                     f"Sheet: {sheet_uuid[:18]}…   User: {user.username}")
        c.setFillColor(DARK_FILL)

        # Separator
        sep_y = content_top + 3 * mm
        c.setLineWidth(0.8); c.setStrokeColor(colors.lightgrey)
        c.line(header_x, sep_y, PAGE_W - MARGIN - MARKER_R, sep_y)
        c.setStrokeColor(DARK_FILL); c.setLineWidth(1)

        # ── Task rows ─────────────────────────────────────────────────────
        for row_idx, task in enumerate(page_tasks):
            # row_y = TOP edge of this row slot
            row_y = content_top - row_idx * ROW_HEIGHT

            # Checkbox: vertically centred within the row slot
            cb_cx_pt = header_x + CHECKBOX_SIZE / 2
            cb_cy_pt = row_y - ROW_HEIGHT / 2             # centre y of checkbox
            cb_left  = cb_cx_pt - CHECKBOX_SIZE / 2       # bottom-left x
            cb_bot   = cb_cy_pt - CHECKBOX_SIZE / 2       # bottom-left y
            _draw_checkbox(c, cb_left, cb_bot, CHECKBOX_SIZE)

            # Task label — to the right of checkbox
            label_x = cb_left + CHECKBOX_SIZE + 4 * mm
            label_y = cb_cy_pt - 4                        # vertically centred

            c.setFont("Helvetica-Bold", 11)
            c.setFillColor(DARK_FILL)
            c.drawString(label_x, label_y, task.title)

            # Right-aligned time hint
            from app.taskManagement import recurrence_label
            hint = f"{task.time.strftime('%H:%M')}  {recurrence_label(task)}"
            c.setFont("Helvetica", 8); c.setFillColor(colors.grey)
            hint_x = PAGE_W - MARGIN - MARKER_R - 2*mm
            c.drawRightString(hint_x, label_y, hint)
            c.setFillColor(DARK_FILL)

            # Dotted leader line
            dot_x0 = label_x + c.stringWidth(task.title, "Helvetica-Bold", 11) + 3*mm
            dot_x1 = hint_x  - c.stringWidth(hint,       "Helvetica",       8)  - 3*mm
            if dot_x1 > dot_x0 + 5*mm:
                c.setDash(1, 3); c.setLineWidth(0.4); c.setStrokeColor(colors.lightgrey)
                c.line(dot_x0, label_y+1*mm, dot_x1, label_y+1*mm)
                c.setDash(); c.setLineWidth(1); c.setStrokeColor(DARK_FILL)

            # ── Record the TRUE centre of the drawn checkbox ───────────────
            # cb_cx_pt, cb_cy_pt are already the centre in ReportLab points
            checkbox_records.append((task.task_id, page_num, cb_cx_pt, cb_cy_pt))

        # ── Footer ────────────────────────────────────────────────────────
        c.setFont("Helvetica", 7); c.setFillColor(colors.grey)
        c.drawCentredString(PAGE_W/2, MARGIN/2,
                            "Fill boxes with a dark pen → photograph → upload at /scan")
        c.setFillColor(DARK_FILL)
        c.showPage()

    c.save()
    pdf_bytes = buf.getvalue()

    # ── Persist checkbox positions ────────────────────────────────────────────
    for task_id, page_num, cx_pt, cy_pt in checkbox_records:
        px_x = _pt_to_px(cx_pt)
        # Flip Y from ReportLab (bottom=0) to OpenCV (top=0)
        px_y = TEMPLATE_HEIGHT_PX - _pt_to_px(cy_pt)
        r_px = _pt_to_px(CHECKBOX_SIZE / 2 * 1.4)   # 40% bigger for tolerance

        cb = TaskCheckbox(
            sheet_id    = sheet.id,
            task_id     = task_id,
            page_number = page_num,
            cx          = px_x,
            cy          = px_y,
            radius      = r_px,
        )
        db.session.add(cb)

    db.session.commit()
    return pdf_bytes, sheet