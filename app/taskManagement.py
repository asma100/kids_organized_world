from datetime import date as date_type, datetime, time as time_type
from app.models import Task, TaskOccurrence
from app import db
from flask_login import current_user


WEEKDAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']


def create_task(title, description, date, time,
                recurrence_type='none',
                recurrence_hours=None,
                recurrence_days=None,
                recurrence_end=None,
                user_id=None):
    """
    Create a task. recurrence_days should be a list of int weekday numbers [0-6]
    for 'weekly' recurrence, or None for other types.
    """
    days_str = None
    if recurrence_type == 'weekly' and recurrence_days:
        if isinstance(recurrence_days, list):
            days_str = ','.join(str(d) for d in sorted(recurrence_days))
        else:
            days_str = str(recurrence_days)

    # Combine date + time into a datetime for the date column
    if isinstance(date, date_type) and not isinstance(date, datetime):
        task_datetime = datetime.combine(date, time if isinstance(time, time_type) else datetime.min.time())
    else:
        task_datetime = date

    owner_id = user_id if user_id is not None else current_user.id

    new_task = Task(
        title=title,
        description=description,
        date=task_datetime,
        time=time,
        recurrence_type=recurrence_type,
        recurrence_hours=recurrence_hours if recurrence_type == 'hourly' else None,
        recurrence_days=days_str,
        recurrence_end=recurrence_end,
        user_id=owner_id
    )
    db.session.add(new_task)
    db.session.commit()
    return new_task


def get_tasks_for_date(target_date, user_id=None):
    """
    Return a list of dicts for all tasks that appear on target_date for
    the current user.

    Each dict:
        task          – Task ORM object
        completed     – bool
        occurrence_id – TaskOccurrence.id (None for one-time tasks)
    """
    owner_id = user_id if user_id is not None else current_user.id
    all_tasks = Task.query.filter_by(user_id=owner_id).all()
    result = []

    for task in all_tasks:
        if not task.occurs_on(target_date):
            continue

        if task.is_recurring():
            occ = TaskOccurrence.query.filter_by(
                task_id=task.task_id,
                occurrence_date=target_date
            ).first()
            completed = occ.completed if occ else False
            occ_id = occ.id if occ else None
        else:
            completed = task.completion_status
            occ_id = None

        result.append({
            'task': task,
            'completed': completed,
            'occurrence_id': occ_id,
        })

    result.sort(key=lambda x: x['task'].time)
    return result


def get_tasksList_for_user(user_id=None):
    """Legacy helper — returns today's task dicts."""
    return get_tasks_for_date(date_type.today(), user_id=user_id)


def toggle_task_for_date(task_id, target_date, user_id=None):
    """
    Toggle completion for a task on a specific date.
    Returns new completed state (bool) or None on error.
    """
    owner_id = user_id if user_id is not None else current_user.id
    task = Task.query.get(task_id)
    if not task or task.user_id != owner_id:
        return None

    if task.is_recurring():
        occ = TaskOccurrence.query.filter_by(
            task_id=task_id,
            occurrence_date=target_date
        ).first()
        if occ is None:
            occ = TaskOccurrence(task_id=task_id,
                                 occurrence_date=target_date,
                                 completed=True)
            db.session.add(occ)
        else:
            occ.completed = not occ.completed
        db.session.commit()
        return occ.completed
    else:
        task.completion_status = not task.completion_status
        db.session.commit()
        return task.completion_status


def update_task(task_id, title=None, description=None, completion_status=None,
                recurrence_type=None, recurrence_hours=None,
                recurrence_days=None, recurrence_end=None,
                user_id=None):
    owner_id = user_id if user_id is not None else current_user.id
    task = Task.query.get(task_id)
    if not task or task.user_id != owner_id:
        return None
    if title is not None:
        task.title = title
    if description is not None:
        task.description = description
    if completion_status is not None:
        task.completion_status = completion_status
    if recurrence_type is not None:
        task.recurrence_type = recurrence_type
    if recurrence_hours is not None:
        task.recurrence_hours = recurrence_hours
    if recurrence_days is not None:
        if isinstance(recurrence_days, list):
            task.recurrence_days = ','.join(str(d) for d in sorted(recurrence_days))
        else:
            task.recurrence_days = recurrence_days
    if recurrence_end is not None:
        task.recurrence_end = recurrence_end
    db.session.commit()
    return task


def delete_task(task_id, user_id=None):
    owner_id = user_id if user_id is not None else current_user.id
    task = Task.query.get(task_id)
    if task and task.user_id == owner_id:
        db.session.delete(task)
        db.session.commit()
        return True
    return False


def recurrence_label(task):
    """Human-readable recurrence string for display in templates."""
    t = task.recurrence_type
    if t == 'none':
        return '📅 One-time'
    if t == 'daily':
        return '🔁 Every day'
    if t == 'hourly':
        return f'🔁 Every {task.recurrence_hours}h'
    if t == 'weekly':
        days = [WEEKDAY_NAMES[d] for d in task.recurrence_days_list()]
        return f'🔁 {", ".join(days)}'
    if t == 'monthly':
        return '🔁 Monthly'
    if t == 'yearly':
        return '🔁 Yearly'
    return t