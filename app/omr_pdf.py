"""
omr_pdf.py  (v4 — Arabic fix)
──────────────────────────────
Install once:
    pip install arabic-reshaper python-bidi reportlab qrcode[pil] Pillow


Font file — download and save to  app/static/fonts/Amiri-Regular.ttf
    https://github.com/aliftype/amiri/releases  → Amiri-Regular.ttf


How Arabic rendering works in ReportLab
────────────────────────────────────────
ReportLab draws every string left-to-right in the order the bytes appear.
It has NO built-in BiDi or shaping engine. So we must:


  Step 1 — arabic_reshaper.reshape(text)
           Converts isolated Unicode code points into their correct
           contextual shaped forms (initial / medial / final / isolated).
           Without this you get disconnected letters: ا ل د ر ا س ة
           With this you get: الدراسة  (letters joined as they should be)


  Step 2 — DO NOT call get_display() / bidi.
           get_display() reverses the string for left-to-right terminals.
           ReportLab's drawRightString() already anchors from the right,
           which is all we need. Calling both reverses the string twice.


  Step 3 — drawRightString(right_anchor, y, shaped_text)
           Draws the shaped text ending at right_anchor.
           Because Arabic is RTL, anchoring from the right is natural.


Row layout for Arabic tasks
────────────────────────────
  [ checkbox ] ←── dotted line ───→ [ Arabic title ] [ hint ]
  left edge                          right_title_x    right_edge


The hint (time + recurrence) sits at the far right.
The Arabic title sits just to the left of the hint, right-aligned.
The dotted line fills the gap between checkbox and title.
"""


import io
import os
import uuid


from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


# ── Layout constants ──────────────────────────────────────────────────────────
PAGE_W, PAGE_H = A4                   # 595.28 × 841.89 pts
MARGIN         = 20 * mm
MARKER_R       = 8  * mm
CHECKBOX_SIZE  = 7  * mm
ROW_HEIGHT     = 14 * mm
QR_SIZE        = 28 * mm
HEADER_H       = 42 * mm
FOOTER_H       = 18 * mm
SCAN_DPI       = 150
PT_TO_PX       = SCAN_DPI / 72.0
DARK_FILL      = colors.black
LIGHT_FILL     = colors.white


LATIN_FONT      = 'Helvetica'
LATIN_FONT_BOLD = 'Helvetica-Bold'
ARABIC_FONT_NAME = 'Amiri'


_HERE = os.path.dirname(os.path.abspath(__file__))
ARABIC_FONT_PATH = os.path.join(_HERE, 'static', 'fonts', 'Amiri-Regular.ttf')




# ── Font registration ─────────────────────────────────────────────────────────


def _register_arabic_font():
    if ARABIC_FONT_NAME in pdfmetrics.getRegisteredFontNames():
        return True
    if not os.path.exists(ARABIC_FONT_PATH):
        print(
            f"[omr_pdf] WARNING: Arabic font not found at:\n"
            f"  {ARABIC_FONT_PATH}\n"
            f"  Download Amiri-Regular.ttf from:\n"
            f"  https://github.com/aliftype/amiri/releases\n"
            f"  and place it at the path above."
        )
        return False
    try:
        pdfmetrics.registerFont(TTFont(ARABIC_FONT_NAME, ARABIC_FONT_PATH))
        return True
    except Exception as e:
        print(f"[omr_pdf] Could not register Arabic font: {e}")
        return False




_ARABIC_FONT_OK = _register_arabic_font()




# ── Arabic helpers ────────────────────────────────────────────────────────────


def _is_arabic(text: str) -> bool:
    """True if the string contains any Arabic Unicode character."""
    for ch in text:
        cp = ord(ch)
        if (0x0600 <= cp <= 0x06FF or
                0x0750 <= cp <= 0x077F or
                0xFB50 <= cp <= 0xFDFF or
                0xFE70 <= cp <= 0xFEFF):
            return True
    return False




def _shape_arabic(text: str) -> str:
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display


        reshaped = arabic_reshaper.reshape(text)
        bidi_text = get_display(reshaped)
        return bidi_text


    except ImportError:
        print("[omr_pdf] arabic reshaper/bidi not installed")
        return text




def _arabic_font() -> str:
    return ARABIC_FONT_NAME if _ARABIC_FONT_OK else LATIN_FONT




def _str_width(c, text: str, font: str, size: int) -> float:
    """String width in points for the given font."""
    return c.stringWidth(text, font, size)




# ── Unit / coordinate helpers ─────────────────────────────────────────────────


def _pt_to_px(pt_value):
    return int(round(pt_value * PT_TO_PX))




def _marker_centres_pt():
    return {
        'TL': (MARGIN,          PAGE_H - MARGIN),
        'TR': (PAGE_W - MARGIN, PAGE_H - MARGIN),
        'BL': (MARGIN,          MARGIN),
        'BR': (PAGE_W - MARGIN, MARGIN),
    }




def get_template_marker_centres():
    """Marker centres in pixel space, y=0 at top (OpenCV convention)."""
    result = {}
    for name, (x_pt, y_pt) in _marker_centres_pt().items():
        result[name] = (
            _pt_to_px(x_pt),
            TEMPLATE_HEIGHT_PX - _pt_to_px(y_pt),
        )
    return result




TEMPLATE_WIDTH_PX  = _pt_to_px(PAGE_W)
TEMPLATE_HEIGHT_PX = _pt_to_px(PAGE_H)




# ── Drawing primitives ────────────────────────────────────────────────────────


def _draw_corner_markers(c):
    c.setFillColor(DARK_FILL)
    c.setStrokeColor(DARK_FILL)
    for _, (x, y) in _marker_centres_pt().items():
        c.circle(x, y, MARKER_R, fill=1, stroke=0)




def _draw_qr(c, sheet_uuid):
    tr_x, tr_y = _marker_centres_pt()['TR']
    qr_x = tr_x - MARKER_R - QR_SIZE - 4 * mm
    qr_y = tr_y - QR_SIZE / 2


    try:
        import qrcode as _qrcode
        import tempfile, os as _os
        qr = _qrcode.QRCode(
            version=None,
            error_correction=_qrcode.constants.ERROR_CORRECT_H,
            box_size=10, border=1,
        )
        qr.add_data(f"KOW:{sheet_uuid}")
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        img.save(tmp.name); tmp.close()
        c.drawImage(tmp.name, qr_x, qr_y, width=QR_SIZE, height=QR_SIZE)
        _os.unlink(tmp.name)
    except ImportError:
        c.setFillColor(LIGHT_FILL); c.setStrokeColor(DARK_FILL)
        c.rect(qr_x, qr_y, QR_SIZE, QR_SIZE, fill=1, stroke=1)
        c.setFillColor(DARK_FILL)
        c.setFont(LATIN_FONT_BOLD, 7)
        c.drawCentredString(qr_x + QR_SIZE / 2, qr_y + QR_SIZE / 2,
                            f"QR:{sheet_uuid[:8]}")




def _draw_checkbox(c, x, y, size):
    """Open square checkbox. (x, y) = bottom-left corner."""
    c.setStrokeColor(DARK_FILL)
    c.setFillColor(LIGHT_FILL)
    c.setLineWidth(2)
    c.rect(x, y, size, size, fill=1, stroke=1)
    c.setLineWidth(1)




# ── Row rendering ─────────────────────────────────────────────────────────────


def _draw_task_row(c, task, label_x, label_y, right_edge):
    """
    Draw the task title + time hint + dotted leader for one row.


    Layout (LTR task):
      label_x  [Title text] ··· [hint]  right_edge


    Layout (RTL Arabic task):
      label_x  ··· [Arabic title] [hint]  right_edge
                   ← title ends here
                   title_right = right_edge - hint_w - gap
    """
    from app.taskManagement import recurrence_label


    # ── 1. Measure and draw hint (always Latin, far right) ────────────────
    hint      = f"{task.time.strftime('%H:%M')}  {recurrence_label(task)}"
    hint_size = 8
    c.setFont(LATIN_FONT, hint_size)
    hint_w    = c.stringWidth(hint, LATIN_FONT, hint_size)
    hint_x    = right_edge - hint_w          # left edge of hint text


    c.setFillColor(colors.grey)
    c.setFont(LATIN_FONT, hint_size)
    c.drawString(hint_x, label_y, hint)
    c.setFillColor(DARK_FILL)


    GAP = 3 * mm   # gap between hint and title, and between title and dots


    # ── 2. Draw task title ────────────────────────────────────────────────
    title_size = 11


    if _is_arabic(task.title) and _ARABIC_FONT_OK:
        # Shape the text (join letters) but do NOT apply bidi reversal
        shaped = _shape_arabic(task.title)
        font   = _arabic_font()
        c.setFont(font, title_size)
        title_w = c.stringWidth(shaped, font, title_size)


        # Right edge of title = left edge of hint minus a gap
        title_right = hint_x - GAP
        # Draw right-to-left anchored at title_right
        c.setFillColor(DARK_FILL)
        c.drawRightString(title_right, label_y, shaped)


        # Dotted line: from after checkbox to left edge of title
        title_left  = title_right - title_w
        dot_x0      = label_x
        dot_x1      = title_left - GAP


    else:
        # Latin / fallback
        c.setFont(LATIN_FONT_BOLD, title_size)
        title_w = c.stringWidth(task.title, LATIN_FONT_BOLD, title_size)
        c.setFillColor(DARK_FILL)
        c.drawString(label_x, label_y, task.title)


        dot_x0 = label_x + title_w + GAP
        dot_x1 = hint_x - GAP


    # ── 3. Dotted leader line ─────────────────────────────────────────────
    if dot_x1 > dot_x0 + 4 * mm:
        c.setDash(1, 3)
        c.setLineWidth(0.4)
        c.setStrokeColor(colors.lightgrey)
        c.line(dot_x0, label_y + 1.5 * mm, dot_x1, label_y + 1.5 * mm)
        c.setDash()
        c.setLineWidth(1)
        c.setStrokeColor(DARK_FILL)




# ── Main generator ────────────────────────────────────────────────────────────


def generate_task_sheet(task_items, sheet_date, user):
    """
    Generate a printable OMR PDF and persist TaskSheet + TaskCheckbox rows.
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


    content_top    = PAGE_H - MARGIN - MARKER_R - HEADER_H
    content_bottom = MARGIN + MARKER_R + FOOTER_H
    rows_per_page  = max(1, int((content_top - content_bottom) / ROW_HEIGHT))


    tasks       = [item['task'] for item in task_items]
    total_pages = max(1, -(-len(tasks) // rows_per_page))


    buf = io.BytesIO()
    c   = rl_canvas.Canvas(buf, pagesize=A4)
    checkbox_records = []


    for page_num in range(1, total_pages + 1):
        page_tasks = tasks[(page_num-1)*rows_per_page : page_num*rows_per_page]


        _draw_corner_markers(c)
        _draw_qr(c, sheet_uuid)


        # ── Header ────────────────────────────────────────────────────────
        tl_x, tl_y = _marker_centres_pt()['TL']
        header_x   = tl_x + MARKER_R + 4 * mm
        header_y   = tl_y - 14 * mm
        right_edge = PAGE_W - MARGIN - MARKER_R - 2 * mm


        c.setFillColor(DARK_FILL)
        c.setFont(LATIN_FONT_BOLD, 16)
        c.drawString(header_x, header_y, "Kids Organized World")


        c.setFont(LATIN_FONT, 10)
        c.drawString(header_x, header_y - 7*mm,
                     f"Tasks: {sheet_date.strftime('%A, %d %B %Y')}   "
                     f"Page {page_num}/{total_pages}")


        c.setFont(LATIN_FONT, 7)
        c.setFillColor(colors.grey)
        c.drawString(header_x, header_y - 13*mm,
                     f"Sheet: {sheet_uuid[:18]}...   User: {user.username}")
        c.setFillColor(DARK_FILL)


        # Separator
        sep_y = content_top + 3 * mm
        c.setLineWidth(0.8); c.setStrokeColor(colors.lightgrey)
        c.line(header_x, sep_y, right_edge, sep_y)
        c.setStrokeColor(DARK_FILL); c.setLineWidth(1)


        # ── Task rows ─────────────────────────────────────────────────────
        for row_idx, task in enumerate(page_tasks):
            row_y    = content_top - row_idx * ROW_HEIGHT
            cb_cx_pt = header_x + CHECKBOX_SIZE / 2
            cb_cy_pt = row_y - ROW_HEIGHT / 2
            cb_left  = cb_cx_pt - CHECKBOX_SIZE / 2
            cb_bot   = cb_cy_pt - CHECKBOX_SIZE / 2


            _draw_checkbox(c, cb_left, cb_bot, CHECKBOX_SIZE)


            # label_y: vertically centred in the row, accounting for font baseline
            label_x = cb_left + CHECKBOX_SIZE + 4 * mm
            label_y = cb_cy_pt - 4


            _draw_task_row(c, task, label_x, label_y, right_edge)


            checkbox_records.append((task.task_id, page_num, cb_cx_pt, cb_cy_pt))


        # ── Footer ────────────────────────────────────────────────────────
        c.setFont(LATIN_FONT, 7)
        c.setFillColor(colors.grey)
        c.drawCentredString(
            PAGE_W / 2, MARGIN / 2,
            "Fill boxes with a dark pen -> photograph -> upload at /scan"
        )
        c.setFillColor(DARK_FILL)
        c.showPage()


    c.save()
    pdf_bytes = buf.getvalue()


    # ── Persist checkbox positions ─────────────────────────────────────────────
    for task_id, page_num, cx_pt, cy_pt in checkbox_records:
        db.session.add(TaskCheckbox(
            sheet_id    = sheet.id,
            task_id     = task_id,
            page_number = page_num,
            cx          = _pt_to_px(cx_pt),
            cy          = TEMPLATE_HEIGHT_PX - _pt_to_px(cy_pt),
            radius      = _pt_to_px(CHECKBOX_SIZE / 2 * 1.4),
        ))


    db.session.commit()
    return pdf_bytes, sheet

