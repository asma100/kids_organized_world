# OMR Feature — Integration Guide

## 1. Install Python dependencies

```bash
pip install reportlab qrcode[pil] Pillow opencv-python-headless numpy pyzbar
```

On Linux (for pyzbar's QR decoding):
```bash
sudo apt-get install libzbar0
```

## 2. Add models to models.py

Open `app/models.py` and at the very bottom paste everything from
`models_omr_addition.py` (the two classes: TaskSheet and TaskCheckbox).
Also ensure `import uuid` is at the top of models.py.

## 3. Run database migration

```bash
flask db migrate -m "add omr task sheet tables"
flask db upgrade
```

## 4. Add new files to your app/ folder

Copy these files into your `app/` directory:
- `omr_pdf.py`
- `omr_scanner.py`

## 5. Update routes.py

Add these three lines to the imports at the top of `routes.py`:
```python
from flask import send_file
from app.omr_pdf import generate_task_sheet
from app.omr_scanner import process_scanned_sheet
```

Then paste the two route functions from `routes_omr_addition.py` into
`routes.py` (after the `toggle_task` route is a good spot).

## 6. Add templates

Copy these two files into your `app/templates/` folder:
- `scan_upload.html`
- `scan_result.html`

## 7. Update taskList.html

Add the Print Sheet and Scan Sheet buttons from
`taskList_print_button_snippet.html` — paste them right after the
existing `+ New Task` button.

Also add a Scan link to the navbar (the snippet file shows where).

## 8. How the full flow works

```
User opens taskList for a date
  → clicks "🖨️ Print Sheet"
    → GET /taskList/print?date=YYYY-MM-DD
    → generate_task_sheet() creates:
        • TaskSheet row (UUID → QR code)
        • TaskCheckbox rows (one per task, with pixel positions)
        • Returns PDF bytes
    → browser downloads the PDF

User prints the PDF, does tasks, fills checkboxes with pen

User takes a photo of the sheet
  → clicks "📷 Scan Sheet" on any page
    → GET /scan  → shows scan_upload.html
  → uploads the photo
    → POST /scan
    → process_scanned_sheet() does:
        1. Decode QR → find TaskSheet in DB
        2. Detect 4 black corner circles in image
        3. Perspective-warp image to match original PDF template
        4. For each TaskCheckbox: sample pixel brightness at (cx, cy)
           → dark enough = checkbox is filled = task done
        5. Call toggle_task_for_date() for changed checkboxes
        6. Mark sheet as processed
    → renders scan_result.html with summary
```

## 9. Tuning the scanner

If checkboxes aren't being detected reliably, adjust these constants
at the top of `omr_scanner.py`:

| Constant | Default | What it does |
|---|---|---|
| `FILL_THRESHOLD` | 128 | Pixel brightness below this = dark |
| `DARK_FRACTION_REQUIRED` | 0.35 | 35% of pixels must be dark to count as filled |

Lower `DARK_FRACTION_REQUIRED` if light pen marks aren't detected.
Raise it if empty boxes are being wrongly flagged as filled.

The scanner falls back to a raw rescaled image if corner markers
can't be found, so it still works if a corner is slightly cut off —
just with less accuracy.
