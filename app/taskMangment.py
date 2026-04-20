from app.models import User, Task
from app import db
from flask_login import current_user


def create_task(title, description, date, time):
    new_task = Task(
        title=title,
        description=description,
        date=date,
        time=time,
        user_id=current_user.id
    )
    db.session.add(new_task)
    db.session.commit()
    return new_task


def get_tasksList_for_user():
    return Task.query.filter_by(user_id=current_user.id).all()


def update_task(task_id, title=None, description=None, completion_status=None):
    task_to_update = Task.query.get(task_id)
    if task_to_update:
        # Security check: make sure this task belongs to the current user
        if task_to_update.user_id != current_user.id:
            return None
        if title is not None:
            task_to_update.title = title
        if description is not None:
            task_to_update.description = description
        if completion_status is not None:
            # Convert string "true"/"false" from form to boolean
            if isinstance(completion_status, str):
                task_to_update.completion_status = completion_status.lower() == 'true'
            else:
                task_to_update.completion_status = completion_status
        db.session.commit()
        return task_to_update
    return None


def delete_task(task_id):
    task_to_delete = Task.query.get(task_id)
    if task_to_delete:
        # Security check: make sure this task belongs to the current user
        if task_to_delete.user_id != current_user.id:
            return False
        db.session.delete(task_to_delete)
        db.session.commit()
        return True
    return False