from datetime import datetime, date as date_type
from app import db, login_manager
from flask_login import UserMixin
import uuid

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


class User(db.Model, UserMixin):
    __tablename__ = 'user'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(20), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    image_file = db.Column(db.String(20), nullable=False, default='default.jpg')
    password = db.Column(db.String(60), nullable=False)
    role = db.Column(db.String(10), nullable=False, default='child')  # 'parent' or 'child'
    parent_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    points = db.Column(db.Integer, nullable=False, default=0)
    crosses = db.Column(db.Integer, nullable=False, default=0)

    tasks = db.relationship('Task', backref='user', lazy=True)

    def __repr__(self):
        return f"User('{self.username}', role='{self.role}')"


class Task(db.Model):
    __tablename__ = 'task'

    task_id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False, default="-")

    # The start date of the task (for recurring tasks, this is the first occurrence)
    date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    time = db.Column(db.Time, nullable=False)

    # For non-recurring tasks only — tracked directly on the task
    completion_status = db.Column(db.Boolean, nullable=False, default=False)

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    # ── Recurrence ────────────────────────────────────────────────────────────
    # recurrence_type values:
    #   'none'    — one-time task (default)
    #   'daily'   — repeats every day
    #   'hourly'  — repeats every N hours (see recurrence_hours)
    #   'weekly'  — repeats on specific days of the week (see recurrence_days)
    #   'monthly' — repeats on the same day of the month
    #   'yearly'  — repeats on the same date each year
    recurrence_type = db.Column(db.String(20), nullable=False, default='none')

    # For 'hourly': repeat every this many hours (e.g. 4 → every 4 hours)
    recurrence_hours = db.Column(db.Integer, nullable=True)

    # For 'weekly': comma-separated weekday numbers 0=Mon … 6=Sun
    # e.g. "0,2,4" means Mon, Wed, Fri
    recurrence_days = db.Column(db.String(20), nullable=True)

    # Optional end date — recurrence stops after this date (NULL = forever)
    recurrence_end = db.Column(db.DateTime, nullable=True)

    # Individual completion records for recurring tasks
    occurrences = db.relationship('TaskOccurrence', backref='task', lazy=True,
                                  cascade='all, delete-orphan')

    def is_recurring(self):
        return self.recurrence_type != 'none'

    def recurrence_days_list(self):
        """Returns list of int weekday numbers, e.g. [0, 2, 4]"""
        if self.recurrence_days:
            return [int(d) for d in self.recurrence_days.split(',') if d.strip()]
        return []

    def occurs_on(self, check_date):
        """
        Returns True if this task should appear on check_date.
        check_date is a datetime.date object.
        """
        task_start = self.date.date() if hasattr(self.date, 'date') else self.date

        # Task hasn't started yet
        if check_date < task_start:
            return False

        # Past recurrence end date
        if self.recurrence_end:
            end = self.recurrence_end.date() if hasattr(self.recurrence_end, 'date') else self.recurrence_end
            if check_date > end:
                return False

        if self.recurrence_type == 'none':
            return check_date == task_start

        elif self.recurrence_type == 'daily':
            return True

        elif self.recurrence_type == 'hourly':
            # Hourly tasks appear every day from start date onwards
            return True

        elif self.recurrence_type == 'weekly':
            return check_date.weekday() in self.recurrence_days_list()

        elif self.recurrence_type == 'monthly':
            return check_date.day == task_start.day

        elif self.recurrence_type == 'yearly':
            return (check_date.month == task_start.month and
                    check_date.day == task_start.day)

        return False

    def __repr__(self):
        return f"Task('{self.title}', recurrence='{self.recurrence_type}')"


class TaskOccurrence(db.Model):
    """
    Tracks completion of a specific instance of a recurring task on a specific date.
    For non-recurring tasks, completion_status on Task itself is used.
    """
    __tablename__ = 'task_occurrence'

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('task.task_id'), nullable=False)
    # The date this occurrence is for (date only, not datetime)
    occurrence_date = db.Column(db.Date, nullable=False)
    completed = db.Column(db.Boolean, nullable=False, default=False)

    __table_args__ = (
        db.UniqueConstraint('task_id', 'occurrence_date', name='uq_task_occurrence'),
    )

    def __repr__(self):
        return f"TaskOccurrence(task={self.task_id}, date={self.occurrence_date}, done={self.completed})"


# ── Good Actions ──────────────────────────────────────────────────────────────

class GoodAction(db.Model):
    __tablename__ = 'good_action'

    id = db.Column(db.Integer, primary_key=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(255), default="")
    points_value = db.Column(db.Integer, nullable=False, default=1)


class Reward(db.Model):
    __tablename__ = 'reward'

    id = db.Column(db.Integer, primary_key=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(255), default="")
    points_threshold = db.Column(db.Integer, nullable=False)

    unlocked_by = db.relationship('RewardUnlock', backref='reward', lazy=True)

    def unlocked_for(self, child_id):
        return any(u.child_id == child_id for u in self.unlocked_by)

    def unlock(self, child_id):
        unlock = RewardUnlock(reward_id=self.id, child_id=child_id)
        db.session.add(unlock)


class RewardUnlock(db.Model):
    __tablename__ = 'reward_unlock'

    id = db.Column(db.Integer, primary_key=True)
    reward_id = db.Column(db.Integer, db.ForeignKey('reward.id'), nullable=False)
    child_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    unlocked_at = db.Column(db.DateTime, default=datetime.utcnow)


# ── Bad Actions ───────────────────────────────────────────────────────────────

class BadAction(db.Model):
    __tablename__ = 'bad_action'

    id = db.Column(db.Integer, primary_key=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(255), default="")
    crosses_value = db.Column(db.Integer, nullable=False, default=1)


class Punishment(db.Model):
    __tablename__ = 'punishment'

    id = db.Column(db.Integer, primary_key=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(255), default="")
    crosses_threshold = db.Column(db.Integer, nullable=False)


# ── Money Organizer ───────────────────────────────────────────────────────────

class MoneyAccount(db.Model):
    __tablename__ = 'money_account'

    id = db.Column(db.Integer, primary_key=True)
    child_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False)

    total_balance = db.Column(db.Float, nullable=False, default=0.0)
    saving_balance = db.Column(db.Float, nullable=False, default=0.0)
    spending_balance = db.Column(db.Float, nullable=False, default=0.0)
    donating_balance = db.Column(db.Float, nullable=False, default=0.0)

    saving_pct = db.Column(db.Integer, nullable=False, default=50)
    spending_pct = db.Column(db.Integer, nullable=False, default=40)
    donating_pct = db.Column(db.Integer, nullable=False, default=10)

    goals = db.relationship('SavingsGoal', backref='account', lazy=True)


class MoneyTransaction(db.Model):
    __tablename__ = 'money_transaction'

    id = db.Column(db.Integer, primary_key=True)
    child_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    transaction_type = db.Column(db.String(20), nullable=False)
    note = db.Column(db.String(255), default="")
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class SavingsGoal(db.Model):
    __tablename__ = 'savings_goal'

    id = db.Column(db.Integer, primary_key=True)
    child_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey('money_account.id'), nullable=True)
    name = db.Column(db.String(100), nullable=False)
    target_amount = db.Column(db.Float, nullable=False)
    reward_description = db.Column(db.String(255), default="")
    achieved = db.Column(db.Boolean, nullable=False, default=False)


    # ── OMR Sheet Models ───────────────────────────────────────────────────────

 
class TaskSheet(db.Model):
    """
    One printed+scanned OMR sheet.
    Covers one user × one date.
    The sheet_uuid is encoded in the page QR code so the scanner
    knows which tasks to update when the sheet is uploaded.
    """
    __tablename__ = 'task_sheet'
 
    id         = db.Column(db.Integer, primary_key=True)
    sheet_uuid = db.Column(db.String(36), unique=True, nullable=False,
                           default=lambda: str(uuid.uuid4()))
    user_id    = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    sheet_date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
 
    # Set to True once the sheet image has been scanned and processed
    processed    = db.Column(db.Boolean, nullable=False, default=False)
    processed_at = db.Column(db.DateTime, nullable=True)
 
    checkboxes = db.relationship('TaskCheckbox', backref='sheet',
                                 lazy=True, cascade='all, delete-orphan')
 
    def __repr__(self):
        return f"TaskSheet(uuid={self.sheet_uuid[:8]}, date={self.sheet_date})"
 
 
class TaskCheckbox(db.Model):
    """
    Maps one printed checkbox on a TaskSheet to one Task.
 
    cx / cy are stored in PIXEL coordinates at SCAN_DPI (150 dpi by default),
    with y=0 at the TOP of the page (OpenCV convention).
    The OMR scanner warps the uploaded scan to match the original template
    dimensions before sampling at these coordinates.
    """
    __tablename__ = 'task_checkbox'
 
    id          = db.Column(db.Integer, primary_key=True)
    sheet_id    = db.Column(db.Integer, db.ForeignKey('task_sheet.id'), nullable=False)
    task_id     = db.Column(db.Integer, db.ForeignKey('task.task_id'), nullable=False)
    page_number = db.Column(db.Integer, nullable=False, default=1)
 
    # Centre of the checkbox square in template pixel space
    cx     = db.Column(db.Integer, nullable=False)
    cy     = db.Column(db.Integer, nullable=False)
    # Sampling radius — pixels inside this circle are inspected for pen marks
    radius = db.Column(db.Integer, nullable=False, default=18)
 
    def __repr__(self):
        return (f"TaskCheckbox(sheet={self.sheet_id}, "
                f"task={self.task_id}, pos=({self.cx},{self.cy}))")