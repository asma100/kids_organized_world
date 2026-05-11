"""
task_image.py
─────────────
Handles saving and deleting task images.

Install once:
    pip install Pillow

Images are stored in:
    app/static/task_images/<user_id>/<uuid>.<ext>

They are resized to a max of 300×300 px (thumbnail) to keep storage small
and so they render neatly next to task titles in the UI and PDF.
"""

import os
import uuid
from PIL import Image

_HERE        = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(_HERE, 'static', 'task_images')
MAX_SIZE      = (300, 300)       # max thumbnail dimensions
ALLOWED_EXTS  = {'png', 'jpg', 'jpeg', 'gif', 'webp'}


def _user_folder(user_id: int) -> str:
    folder = os.path.join(UPLOAD_FOLDER, str(user_id))
    os.makedirs(folder, exist_ok=True)
    return folder


def allowed_image(filename: str) -> bool:
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTS


def save_task_image(file_storage, user_id: int) -> str:
    """
    Receive a Werkzeug FileStorage object, resize it, save to disk.
    Returns the filename (relative to static/task_images/<user_id>/)
    which is what you store in Task.image_filename.

    Usage in your route:
        from app.task_image import save_task_image, allowed_image
        if form.image.data and allowed_image(form.image.data.filename):
            task.image_filename = save_task_image(form.image.data, current_user.id)
    """
    if not file_storage or file_storage.filename == '':
        return None

    ext      = file_storage.filename.rsplit('.', 1)[1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    folder   = _user_folder(user_id)
    path     = os.path.join(folder, filename)

    # Open, convert to RGBA for transparency support, resize, save as PNG
    img = Image.open(file_storage.stream)
    img.thumbnail(MAX_SIZE, Image.LANCZOS)

    # Always save as PNG for consistency
    png_filename = filename.rsplit('.', 1)[0] + '.png'
    png_path     = os.path.join(folder, png_filename)
    img.save(png_path, 'PNG')

    return png_filename


def delete_task_image(image_filename: str, user_id: int):
    """Delete a task image file from disk. Safe to call with None."""
    if not image_filename:
        return
    path = os.path.join(_user_folder(user_id), image_filename)
    if os.path.exists(path):
        os.remove(path)


def get_image_path(image_filename: str, user_id: int) -> str:
    """
    Return the full filesystem path for a task image.
    Used by omr_pdf.py to embed images in the PDF.
    """
    if not image_filename:
        return None
    path = os.path.join(_user_folder(user_id), image_filename)
    return path if os.path.exists(path) else None


def get_image_url(image_filename: str, user_id: int) -> str:
    """
    Return the Flask static URL for a task image.
    Use this in templates: {{ get_image_url(task.image_filename, task.user_id) }}
    Or just build the url in the template:
        url_for('static', filename='task_images/' + task.user_id|string + '/' + task.image_filename)
    """
    if not image_filename:
        return None
    return f"task_images/{user_id}/{image_filename}"
