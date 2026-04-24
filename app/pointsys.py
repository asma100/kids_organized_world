"""
pointsys.py
───────────
Recalculates a user's points based on ALL completed tasks:
  - One-time tasks  → Task.completion_status == True
  - Recurring tasks → TaskOccurrence.completed == True (each occurrence counts)

Call total_task_points(user_id) any time tasks are toggled — from the
web toggle route AND from the OMR scanner after processing a sheet.
"""

from app.models import User, Task, TaskOccurrence
from app import db


def total_task_points(user_id):
    """
    Recount and save a user's points from scratch.

    Points are awarded as:
      +1 per completed one-time task
      +1 per completed recurring task occurrence
    """
    user = User.query.get(user_id)
    if not user:
        return 0

    # One-time tasks completed directly
    onetime_done = Task.query.filter_by(
        user_id=user_id,
        recurrence_type='none',
        completion_status=True
    ).count()

    # Recurring task occurrences that are marked complete
    # Join TaskOccurrence → Task to filter by user_id
    recurring_done = (
        db.session.query(TaskOccurrence)
        .join(Task, Task.task_id == TaskOccurrence.task_id)
        .filter(
            Task.user_id == user_id,
            Task.recurrence_type != 'none',
            TaskOccurrence.completed == True
        )
        .count()
    )

    user.points = onetime_done + recurring_done
    db.session.commit()
    return user.points