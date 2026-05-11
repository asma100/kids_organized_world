"""
omr_pdf.py
──────────
Generates a printable OMR task sheet as a PDF.

Each page contains:
  ┌─────────────────────────────────────────┐
  │ ● TL marker          QR code │ TR marker│
  │                               (sheet_id)│
  │  Title + date                           │
  │  ☐  Task title ........................ │
  │  ☐  Task title ........................ │
  │  ...                                    │
  │ ● BL marker                  ● BR marker│
  └─────────────────────────────────────────┘

The 4 filled circles at page corners are the alignment markers used by the
OMR scanner to warp/deskew the scanned image back to template coordinates.

Install requirements (run once):
    pip install reportlab qrcode[pil] Pillow

Usage:
    from app.omr_pdf import generate_task_sheet
    pdf_bytes, sheet = generate_task_sheet(task_items, viewed_date, current_user)
    # pdf_bytes → send as file download
    # sheet     → TaskSheet ORM object saved to DB (contains checkbox positions)
"""

import io
import uuid
from datetime import date as date_type

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas

# ── Constants ─────────────────────────────────────────────────────────────────

PAGE_W, PAGE_H = A4                    # 595.27 x 841.89 pts
MARGIN          = 20 * mm              # page margin
MARKER_R        = 8 * mm              # corner marker circle radius
CHECKBOX_SIZE   = 7 * mm              # printed checkbox square side
ROW_HEIGHT      = 12 * mm             # vertical spacing between task rows
QR_SIZE         = 28 * mm             # QR code size
HEADER_H        = 40 * mm             # space reserved for header
FOOTER_H        = 20 * mm             # space reserved for footer (corner markers)

# Pixel DPI used when the scanned image will be processed.
# The scanner must rescale to this before sampling checkbox positions.
SCAN_DPI        = 150
PT_TO_PX        = SCAN_DPI / 72.0     # reportlab uses points (1/72 inch)

DARK_FILL       = colors.black
LIGHT_FILL      = colors.white
MARKER_COLOR    = colors.black


def _pt_to_px(pt_value):
    """Convert reportlab points to pixels at SCAN_DPI."""
    return int(round(pt_value * PT_TO_PX))


def _draw_corner_markers(c, page_w, page_h, margin, r):
    """Draw 4 solid filled circles at page corners (inside margin)."""
    positions = [
        (margin,           page_h - margin),    # top-left
        (page_w - margin,  page_h - margin),    # top-right
        (margin,           margin),              # bottom-left
        (page_w - margin,  margin),              # bottom-right
    ]
    c.setFillColor(MARKER_COLOR)
    c.setStrokeColor(MARKER_COLOR)
    for (x, y) in positions:
        c.circle(x, y, r, fill=1, stroke=0)


def _draw_qr(c, sheet_uuid, x, y, size):
    """
    Render a QR code encoding sheet_uuid at position (x, y) with given size.
    Requires: pip install qrcode[pil] Pillow
    """
    try:
        import qrcode
        from PIL import Image as PILImage
        import tempfile, os

        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=10,
            border=1,
        )
        qr.add_data(f"KOW:{sheet_uuid}")
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        # Save to temp file and draw into PDF
        tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        img.save(tmp.name)
        tmp.close()
        c.drawImage(tmp.name, x, y, width=size, height=size)
        os.unlink(tmp.name)
    except ImportError:
        # Fallback: draw a labelled box if qrcode is not installed
        c.setStrokeColor(DARK_FILL)
        c.setFillColor(LIGHT_FILL)
        c.rect(x, y, size, size, fill=1, stroke=1)
        c.setFillColor(DARK_FILL)
        c.setFont("Helvetica-Bold", 6)
        c.drawCentredString(x + size / 2, y + size / 2 + 3, "QR")
        c.setFont("Helvetica", 5)
        # Draw truncated UUID so at least a human can type it
        short = sheet_uuid[:8]
        c.drawCentredString(x + size / 2, y + size / 2 - 6, short)


def _draw_checkbox(c, x, y, size):
    """Draw a single open square checkbox."""
    c.setStrokeColor(DARK_FILL)
    c.setFillColor(LIGHT_FILL)
    c.setLineWidth(1.5)
    c.rect(x, y, size, size, fill=1, stroke=1)


def generate_task_sheet(task_items, sheet_date, user, db_session=None):
    """
    Generate a PDF OMR task sheet and persist the sheet + checkbox records.

    Parameters
    ----------
    task_items : list of dicts  — same format as get_tasks_for_date()
                  each has keys: 'task', 'completed', 'occurrence_id'
    sheet_date : datetime.date
    user       : User ORM object (current_user)
    db_session : SQLAlchemy session (pass db.session from your Flask app)

    Returns
    -------
    pdf_bytes  : bytes — the raw PDF content, ready for send_file()
    sheet      : TaskSheet ORM object (already committed to DB)
    """
    from app import db
    from app.models import TaskSheet, TaskCheckbox

    # ── 1. Create the TaskSheet record ──────────────────────────────────────
    sheet_uuid = str(uuid.uuid4())
    sheet = TaskSheet(
        sheet_uuid=sheet_uuid,
        user_id=user.id,
        sheet_date=sheet_date,
    )
    db.session.add(sheet)
    db.session.flush()   # gets sheet.id without full commit

    # ── 2. Layout calculation ────────────────────────────────────────────────
    content_top    = PAGE_H - MARGIN - MARKER_R * 2 - HEADER_H
    content_bottom = MARGIN + MARKER_R * 2 + FOOTER_H
    content_height = content_top - content_bottom
    rows_per_page  = max(1, int(content_height / ROW_HEIGHT))

    tasks         = [item['task'] for item in task_items]
    total_pages   = max(1, -(-len(tasks) // rows_per_page))  # ceiling division

    # ── 3. Render PDF ────────────────────────────────────────────────────────
    buf = io.BytesIO()
    c   = rl_canvas.Canvas(buf, pagesize=A4)

    checkbox_records = []   # collect (task_id, page, cx_pt, cy_pt) for DB

    for page_num in range(1, total_pages + 1):
        page_tasks = tasks[(page_num - 1) * rows_per_page: page_num * rows_per_page]

        # ── Corner markers ────────────────────────────────────────────────
        _draw_corner_markers(c, PAGE_W, PAGE_H, MARGIN, MARKER_R)

        # ── QR code (top-right, inside TR marker) ─────────────────────────
        qr_x = PAGE_W - MARGIN - QR_SIZE - MARKER_R
        qr_y = PAGE_H - MARGIN - QR_SIZE - MARKER_R
        _draw_qr(c, sheet_uuid, qr_x, qr_y, QR_SIZE)

        # ── Header ────────────────────────────────────────────────────────
        c.setFont("Helvetica-Bold", 18)
        c.setFillColor(DARK_FILL)
        header_x = MARGIN + MARKER_R
        header_y = PAGE_H - MARGIN - MARKER_R - 14 * mm
        c.drawString(header_x, header_y, "⭐ Kids Organized World")

        c.setFont("Helvetica", 11)
        c.drawString(header_x, header_y - 8 * mm,
                     f"Tasks for: {sheet_date.strftime('%A, %d %B %Y')}   "
                     f"Page {page_num}/{total_pages}")

        c.setFont("Helvetica", 8)
        c.setFillColor(colors.grey)
        c.drawString(header_x, header_y - 14 * mm,
                     f"Sheet ID: {sheet_uuid[:18]}...  "
                     f"User: {user.username}")
        c.setFillColor(DARK_FILL)

        # Separator line
        sep_y = PAGE_H - MARGIN - MARKER_R * 2 - HEADER_H + 4 * mm
        c.setLineWidth(1)
        c.setStrokeColor(colors.lightgrey)
        c.line(MARGIN + MARKER_R, sep_y, PAGE_W - MARGIN - MARKER_R, sep_y)
        c.setStrokeColor(DARK_FILL)

        # ── Task rows ─────────────────────────────────────────────────────
        for row_idx, task in enumerate(page_tasks):
            row_y = content_top - row_idx * ROW_HEIGHT

            # Checkbox square
            cb_x = MARGIN + MARKER_R + 2 * mm
            cb_y = row_y - CHECKBOX_SIZE          # bottom-left of square
            _draw_checkbox(c, cb_x, cb_y, CHECKBOX_SIZE)

            # Task label
            label_x = cb_x + CHECKBOX_SIZE + 4 * mm
            label_y = row_y - CHECKBOX_SIZE + 1.5 * mm
            c.setFont("Helvetica-Bold", 11)
            c.drawString(label_x, label_y, task.title)

            # Time + recurrence hint (right-aligned)
            from app.taskManagement import recurrence_label
            hint = f"{task.time.strftime('%H:%M')}  {recurrence_label(task)}"
            c.setFont("Helvetica", 8)
            c.setFillColor(colors.grey)
            c.drawRightString(PAGE_W - MARGIN - MARKER_R - 2 * mm, label_y, hint)
            c.setFillColor(DARK_FILL)

            # Dotted line after the label
            dot_start_x = label_x + c.stringWidth(task.title, "Helvetica-Bold", 11) + 3 * mm
            dot_end_x   = PAGE_W - MARGIN - MARKER_R - c.stringWidth(hint, "Helvetica", 8) - 5 * mm
            if dot_end_x > dot_start_x + 5 * mm:
                c.setDash(1, 3)
                c.setLineWidth(0.5)
                c.setStrokeColor(colors.lightgrey)
                c.line(dot_start_x, label_y + 1.5 * mm, dot_end_x, label_y + 1.5 * mm)
                c.setDash()
                c.setStrokeColor(DARK_FILL)
                c.setLineWidth(1)

            # Record checkbox centre in POINTS (will convert to px for DB)
            # Centre of checkbox = (cb_x + size/2, cb_y + size/2)
            cx_pt = cb_x + CHECKBOX_SIZE / 2
            cy_pt = cb_y + CHECKBOX_SIZE / 2
            checkbox_records.append((task.task_id, page_num, cx_pt, cy_pt))

        # ── Footer ────────────────────────────────────────────────────────
        c.setFont("Helvetica", 7)
        c.setFillColor(colors.grey)
        c.drawCentredString(PAGE_W / 2,
                            MARGIN + MARKER_R - 4 * mm,
                            "Print → Fill checkboxes with a pen → Scan and upload at kow.app/scan")
        c.setFillColor(DARK_FILL)

        c.showPage()

    c.save()
    pdf_bytes = buf.getvalue()

    # ── 4. Persist checkbox positions ────────────────────────────────────────
    # Reportlab y=0 is bottom of page; we store it directly.
    # The scanner will receive PAGE_H and SCAN_DPI to convert correctly.
    for task_id, page_num, cx_pt, cy_pt in checkbox_records:
        cb = TaskCheckbox(
            sheet_id=sheet.id,
            task_id=task_id,
            page_number=page_num,
            cx=_pt_to_px(cx_pt),
            cy=_pt_to_px(PAGE_H - cy_pt),  # flip Y: scanner y=0 is top
            radius=_pt_to_px(CHECKBOX_SIZE / 2),
        )
        db.session.add(cb)

    db.session.commit()
    return pdf_bytes, sheet


# ── Template image dimensions (used by omr_scanner.py) ───────────────────────
TEMPLATE_WIDTH_PX  = _pt_to_px(PAGE_W)
TEMPLATE_HEIGHT_PX = _pt_to_px(PAGE_H)

# Corner marker centres in PIXELS (top-left origin, same as OpenCV)
def get_template_marker_centres():
    """Returns the 4 corner marker centres in pixel space (TL, TR, BL, BR)."""
    r = MARGIN + MARKER_R   # distance from page edge to circle centre (points)
    return {
        'TL': (_pt_to_px(r),          _pt_to_px(MARKER_R)),
        'TR': (_pt_to_px(PAGE_W - r), _pt_to_px(MARKER_R)),
        'BL': (_pt_to_px(r),          _pt_to_px(PAGE_H - MARKER_R)),
        'BR': (_pt_to_px(PAGE_W - r), _pt_to_px(PAGE_H - MARKER_R)),
    }