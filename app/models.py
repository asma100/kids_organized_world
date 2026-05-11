from datetime import datetime, date as date_type, timedelta
from flask import current_app
from itsdangerous import URLSafeTimedSerializer as Serializer
from app import db, login_manager
from flask_login import UserMixin
import uuid


def _nth_weekday_of_month(year: int, month: int, weekday: int, ordinal: int):
    """Return a date for the nth weekday in a month.

    weekday: 0=Mon..6=Sun
    ordinal: 1..4 for 1st..4th, -1 for last
    """
    if ordinal == 0 or ordinal < -1 or ordinal > 4:
        return None
    if weekday < 0 or weekday > 6:
        return None

    def _last_day_of_month(y: int, m: int) -> date_type:
        if m == 12:
            next_month_first = date_type(y + 1, 1, 1)
        else:
            next_month_first = date_type(y, m + 1, 1)
        return next_month_first - timedelta(days=1)

    if ordinal == -1:
        d = _last_day_of_month(year, month)
        while d.weekday() != weekday:
            d -= timedelta(days=1)
        return d

    first_of_month = date_type(year, month, 1)
    offset = (weekday - first_of_month.weekday() + 7) % 7
    first_matching = first_of_month + timedelta(days=offset)
    candidate = first_matching + timedelta(days=7 * (ordinal - 1))
    if candidate.month != month:
        return None
    return candidate

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


class User(db.Model, UserMixin):
    __tablename__ = 'user'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    image_file = db.Column(db.String(20), nullable=False, default='default.jpg')
    password = db.Column(db.String(60), nullable=False)
    role = db.Column(db.String(10), nullable=False, default='child')  # 'parent' or 'child'
    parent_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    points = db.Column(db.Integer, nullable=False, default=0)
    crosses = db.Column(db.Integer, nullable=False, default=0)

    tasks = db.relationship('Task', backref='user', lazy=True)

    __table_args__ = (
        db.UniqueConstraint('username', 'parent_id', name='unique_username_per_parent'),
    )

    @staticmethod
    def _auth_serializer():
        return Serializer(current_app.config['SECRET_KEY'], salt='auth-token')

    def get_auth_token(self, expires_sec=86400):
        return self._auth_serializer().dumps({'user_id': self.id})

    @staticmethod
    def verify_auth_token(token, max_age=86400):
        serializer = Serializer(current_app.config['SECRET_KEY'], salt='auth-token')
        try:
            data = serializer.loads(token, max_age=max_age)
        except Exception:
            return None
        return User.query.get(data.get('user_id'))

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
    #   'interval_days' — repeats every N days (see recurrence_interval_days)
    #   'weekly'  — repeats on specific days of the week (see recurrence_days)
    #   'monthly' — repeats on the same day of the month
    #   'monthly_weekday' — repeats monthly on e.g. 1st Monday (see recurrence_monthly_ordinal/weekday)
    #   'yearly'  — repeats on the same date each year
    recurrence_type = db.Column(db.String(20), nullable=False, default='none')

    # For 'hourly': repeat every this many hours (e.g. 4 → every 4 hours)
    recurrence_hours = db.Column(db.Integer, nullable=True)

    # For 'interval_days': repeat every this many days (e.g. 3 → every 3 days)
    recurrence_interval_days = db.Column(db.Integer, nullable=True)

    # For 'weekly': comma-separated weekday numbers 0=Mon … 6=Sun
    # e.g. "0,2,4" means Mon, Wed, Fri
    recurrence_days = db.Column(db.String(20), nullable=True)

    # For 'monthly_weekday': nth weekday of month, e.g. 1st Monday
    # ordinal: 1..4 for 1st..4th, -1 for last
    recurrence_monthly_ordinal = db.Column(db.Integer, nullable=True)
    # weekday: 0=Mon..6=Sun
    recurrence_monthly_weekday = db.Column(db.Integer, nullable=True)

    # Optional end date — recurrence stops after this date (NULL = forever)
    recurrence_end = db.Column(db.DateTime, nullable=True)
    image_filename = db.Column(db.String(255), nullable=True)
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

        elif self.recurrence_type == 'interval_days':
            interval = self.recurrence_interval_days or 0
            if interval < 1:
                return False
            return ((check_date - task_start).days % interval) == 0

        elif self.recurrence_type == 'weekly':
            return check_date.weekday() in self.recurrence_days_list()

        elif self.recurrence_type == 'monthly':
            return check_date.day == task_start.day

        elif self.recurrence_type == 'monthly_weekday':
            ordinal = self.recurrence_monthly_ordinal
            weekday = self.recurrence_monthly_weekday
            if ordinal is None or weekday is None:
                return False
            target = _nth_weekday_of_month(check_date.year, check_date.month, int(weekday), int(ordinal))
            return target is not None and check_date == target

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

    # Points needed to unlock this reward
    points_threshold = db.Column(db.Integer, nullable=False)
    # Points spent when the reward is used
    points_cost = db.Column(db.Integer, nullable=False, default=0)

    used_by = db.relationship('RewardUnlock', backref='reward', lazy=True,
                              cascade='all, delete-orphan')

    def unlocked_for(self, child_id):
        return any(u.child_id == child_id for u in self.used_by)

    def used_by_child(self, child_id):
        return any(u.child_id == child_id and u.used for u in self.used_by)

    def unlock(self, child_id):
        if not self.unlocked_for(child_id):
            unlock = RewardUnlock(reward_id=self.id, child_id=child_id)
            db.session.add(unlock)

    def __repr__(self):
        return f"Reward('{self.name}', threshold={self.points_threshold})"


class RewardUnlock(db.Model):
    __tablename__ = 'reward_unlock'

    id = db.Column(db.Integer, primary_key=True)
    reward_id = db.Column(db.Integer, db.ForeignKey('reward.id'), nullable=False)
    child_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    unlocked_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Has the child actually redeemed/used this reward?
    used = db.Column(db.Boolean, nullable=False, default=False)
    used_at = db.Column(db.DateTime, nullable=True)

    def __repr__(self):
        return f"RewardUnlock(reward={self.reward_id}, child={self.child_id}, used={self.used})"


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

    # Crosses threshold that triggers this punishment
    crosses_threshold = db.Column(db.Integer, nullable=False)
    # Crosses removed when parent marks the punishment as served
    crosses_cost = db.Column(db.Integer, nullable=False, default=0)

    # Track whether punishment has been applied to the child
    used = db.Column(db.Boolean, nullable=False, default=False)
    used_at = db.Column(db.DateTime, nullable=True)

    def __repr__(self):
        return f"Punishment('{self.name}', at {self.crosses_threshold} crosses)"


# ── Money Organizer ───────────────────────────────────────────────────────────

class MoneyAccount(db.Model):
    __tablename__ = 'money_account'

    id = db.Column(db.Integer, primary_key=True)
    child_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False)

    # Master balance = all money received for this child
    total_balance = db.Column(db.Float, nullable=False, default=0.0)

    # Money not yet assigned to a jar
    unassigned_balance = db.Column(db.Float, nullable=False, default=0.0)

    # The three jars — used once the child assigns money manually
    spending_balance = db.Column(db.Float, nullable=False, default=0.0)
    saving_balance = db.Column(db.Float, nullable=False, default=0.0)
    donating_balance = db.Column(db.Float, nullable=False, default=0.0)

    goals = db.relationship('SavingsGoal', backref='account', lazy=True)
    transactions = db.relationship('MoneyTransaction',
                                   foreign_keys='MoneyTransaction.account_id',
                                   backref='owner', lazy=True)

    def __repr__(self):
        return (f"MoneyAccount(child={self.child_id}, "
                f"total={self.total_balance:.2f}, "
                f"unassigned={self.unassigned_balance:.2f})")


class MoneyTransaction(db.Model):
    __tablename__ = 'money_transaction'

    id = db.Column(db.Integer, primary_key=True)
    # Link to the child user (for convenience) and to the money account
    child_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey('money_account.id'), nullable=True)
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
    current_amount = db.Column(db.Float, nullable=False, default=0.0)
    reward_description = db.Column(db.String(255), default="")
    achieved = db.Column(db.Boolean, nullable=False, default=False)


# ── Turn Management (MVP) ─────────────────────────────────────────────────────

class TurnGroup(db.Model):
    __tablename__ = 'turn_group'

    id = db.Column(db.Integer, primary_key=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(80), nullable=False)

    # Fixed duration per turn (minutes)
    turn_duration_min = db.Column(db.Integer, nullable=False, default=30)

    # Category: 'clock' (timed turns), 'calendar' (daily owner), 'event' (queue but no timer)
    category = db.Column(db.String(20), nullable=False, default='clock')

    # How to pick the next child: 'round_robin' or 'random'
    selection_mode = db.Column(db.String(20), nullable=False, default='round_robin')

    # Auto-advance settings (client-side timer triggers POST while the page is open)
    auto_advance_enabled = db.Column(db.Boolean, nullable=False, default=False)
    auto_advance_value = db.Column(db.Integer, nullable=True)
    auto_advance_unit = db.Column(db.String(10), nullable=False, default='minutes')
    auto_advance_paused = db.Column(db.Boolean, nullable=False, default=False)

    # Grace period (seconds) used by the clock view
    grace_period_sec = db.Column(db.Integer, nullable=False, default=120)

    # If True, any overrun during grace is deducted from tomorrow
    deduct_overrun = db.Column(db.Boolean, nullable=False, default=True)

    # Optional penalty integration (crosses -> minute deduction)
    penalty_enabled = db.Column(db.Boolean, nullable=False, default=False)
    penalty_crosses = db.Column(db.Integer, nullable=False, default=3)
    penalty_minutes = db.Column(db.Integer, nullable=False, default=15)

    # Calendar rotation settings
    cal_mode = db.Column(db.String(20), nullable=False, default='n_day')
    cal_n_days = db.Column(db.Integer, nullable=False, default=1)
    cal_paused = db.Column(db.Boolean, nullable=False, default=False)

    # Daily quota per child (minutes)
    daily_quota_min = db.Column(db.Integer, nullable=False, default=180)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    members = db.relationship('TurnGroupMember', backref='group', lazy=True,
                              cascade='all, delete-orphan')


class TurnGroupMember(db.Model):
    __tablename__ = 'turn_group_member'

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('turn_group.id'), nullable=False)
    child_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    position = db.Column(db.Integer, nullable=False, default=0)  # stable order within the group

    # Turn penalties (minutes deducted from quota until cleared)
    penalty_min_owed = db.Column(db.Integer, nullable=False, default=0)

    # Birthday mode: temporarily prefer this child as today's starter
    birthday_mode = db.Column(db.Boolean, nullable=False, default=False)
    birthday_date = db.Column(db.Date, nullable=True)

    __table_args__ = (
        db.UniqueConstraint('group_id', 'child_id', name='uq_turn_group_child'),
    )


class TurnDailyUsage(db.Model):
    __tablename__ = 'turn_daily_usage'

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('turn_group.id'), nullable=False)
    child_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    day = db.Column(db.Date, nullable=False)
    used_min = db.Column(db.Integer, nullable=False, default=0)
    used_sec = db.Column(db.Integer, nullable=False, default=0)

    # Overrun during grace window (deducted from tomorrow if enabled)
    overrun_sec = db.Column(db.Integer, nullable=False, default=0)

    __table_args__ = (
        db.UniqueConstraint('group_id', 'child_id', 'day', name='uq_turn_usage_day'),
    )


class TurnDayState(db.Model):
    __tablename__ = 'turn_day_state'

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('turn_group.id'), nullable=False)
    day = db.Column(db.Date, nullable=False)
    current_position = db.Column(db.Integer, nullable=False, default=0)

    # Clock (timed resource) state
    active_child_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    session_started_at = db.Column(db.DateTime, nullable=True)
    turn_remaining_sec = db.Column(db.Integer, nullable=True)

    # Optional: when grace period began (not required by MVP UI)
    grace_started_at = db.Column(db.DateTime, nullable=True)

    # Grace period notification latch
    grace_notified = db.Column(db.Boolean, nullable=False, default=False)

    # Shared turns: JSON list of child ids
    shared_child_ids = db.Column(db.Text, nullable=True)

    # Random wheel (initial selection) lock for the day
    wheel_used = db.Column(db.Boolean, nullable=False, default=False)

    __table_args__ = (
        db.UniqueConstraint('group_id', 'day', name='uq_turn_state_day'),
    )


class TurnAuditLog(db.Model):
    __tablename__ = 'turn_audit_log'

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('turn_group.id'), nullable=False)
    day = db.Column(db.Date, nullable=False)
    ts = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    action = db.Column(db.String(40), nullable=False)
    actor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    child_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    detail = db.Column(db.String(255), nullable=True)

    actor = db.relationship('User', foreign_keys=[actor_id])
    child = db.relationship('User', foreign_keys=[child_id])


class TurnSwapRequest(db.Model):
    __tablename__ = 'turn_swap_request'

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('turn_group.id'), nullable=False)
    day = db.Column(db.Date, nullable=False)

    requester_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    target_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    requester = db.relationship('User', foreign_keys=[requester_id])
    target = db.relationship('User', foreign_keys=[target_id])

    status = db.Column(db.String(20), nullable=False, default='pending')  # pending/accepted/rejected/cancelled
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    resolved_at = db.Column(db.DateTime, nullable=True)


class TurnWeekdayRule(db.Model):
    __tablename__ = 'turn_weekday_rule'

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('turn_group.id'), nullable=False)
    weekday = db.Column(db.Integer, nullable=False)  # 0=Mon..6=Sun
    child_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    child = db.relationship('User', foreign_keys=[child_id])

    __table_args__ = (
        db.UniqueConstraint('group_id', 'weekday', name='uq_turn_weekday_rule'),
    )


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




class PresetTask(db.Model):
    """
    Built-in common tasks that parents can one-click add to their child's list.
    Populated once via seed_presets() below — not user-created.
    """
    __tablename__ = 'preset_task'
 
    id              = db.Column(db.Integer, primary_key=True)
    title           = db.Column(db.String(100), nullable=False)
    title_ar        = db.Column(db.String(100), nullable=True)   # Arabic title
    description     = db.Column(db.String(255), nullable=False, default='')
    description_ar  = db.Column(db.String(255), nullable=True)
    emoji           = db.Column(db.String(10),  nullable=False, default='📌')
    # Category for grouping in the UI
    category        = db.Column(db.String(50),  nullable=False, default='general')
    # Optional image bundled with the app (stored in static/preset_images/)
    image_filename  = db.Column(db.String(255), nullable=True)
    # Suggested recurrence so parents get sensible defaults
    default_recurrence = db.Column(db.String(20), nullable=False, default='daily')
 
    def __repr__(self):
        return f"PresetTask('{self.title}')"
 
 
# ─────────────────────────────────────────────────────────────
# Seed function — call once from Flask shell or __init__.py
# ─────────────────────────────────────────────────────────────
 
PRESET_DATA = [
    # ── Morning routine ───────────────────────────────────────
    dict(title='Brush Teeth',       title_ar='تنظيف الأسنان',
         description='Morning and evening', description_ar='صباحاً ومساءً',
         emoji='🪥', category='morning', default_recurrence='daily',
         image_filename='preset_brush_teeth.png'),
 
    dict(title='Wash Face',         title_ar='غسل الوجه',
         description='Use soap and rinse well', description_ar='استخدم الصابون واشطف جيداً',
         emoji='🧼', category='morning', default_recurrence='daily',
         image_filename='preset_wash_face.png'),
 
    dict(title='Make Bed',          title_ar='ترتيب السرير',
         description='Straighten the sheets and pillow', description_ar='رتّب الملاءة والوسادة',
         emoji='🛏️', category='morning', default_recurrence='daily',
         image_filename='preset_make_bed.png'),
 
    dict(title='Get Dressed',       title_ar='ارتداء الملابس',
         description='Put on clean clothes', description_ar='البس ملابس نظيفة',
         emoji='👕', category='morning', default_recurrence='daily',
         image_filename='preset_get_dressed.png'),
 
    dict(title='Eat Breakfast',     title_ar='تناول الفطور',
         description='Eat a healthy breakfast', description_ar='تناول فطوراً صحياً',
         emoji='🥣', category='morning', default_recurrence='daily',
         image_filename='preset_breakfast.png'),
 
    # ── School ────────────────────────────────────────────────
    dict(title='Do Homework',       title_ar='إنجاز الواجبات',
         description='Finish all school homework', description_ar='أنهِ جميع الواجبات المدرسية',
         emoji='📚', category='school', default_recurrence='weekly',
         image_filename='preset_homework.png'),
 
    dict(title='Pack School Bag',   title_ar='تحضير حقيبة المدرسة',
         description='Pack everything for tomorrow', description_ar='جهّز كل شيء للغد',
         emoji='🎒', category='school', default_recurrence='weekly',
         image_filename='preset_school_bag.png'),
 
    dict(title='Read for 20 mins',  title_ar='القراءة 20 دقيقة',
         description='Read a book of your choice', description_ar='اقرأ كتاباً تحبه',
         emoji='📖', category='school', default_recurrence='daily',
         image_filename='preset_reading.png'),
 
    # ── Evening ───────────────────────────────────────────────
    dict(title='Tidy Room',         title_ar='ترتيب الغرفة',
         description='Put toys and things away', description_ar='رتّب ألعابك وأغراضك',
         emoji='🧹', category='evening', default_recurrence='daily',
         image_filename='preset_tidy_room.png'),
 
    dict(title='Bath / Shower',     title_ar='الاستحمام',
         description='Wash hair and body', description_ar='اغسل شعرك وجسمك',
         emoji='🚿', category='evening', default_recurrence='daily',
         image_filename='preset_shower.png'),
 
    dict(title='Prepare Clothes',   title_ar='تجهيز ملابس الغد',
         description='Lay out clothes for tomorrow', description_ar='جهّز ملابسك للغد',
         emoji='👗', category='evening', default_recurrence='daily',
         image_filename='preset_clothes.png'),
 
    # ── Health ────────────────────────────────────────────────
    dict(title='Drink Water',       title_ar='شرب الماء',
         description='Drink 6–8 glasses today', description_ar='اشرب ٦–٨ أكواب اليوم',
         emoji='💧', category='health', default_recurrence='daily',
         image_filename='preset_water.png'),
 
    dict(title='Exercise / Play',   title_ar='التمرين / اللعب',
         description='30 minutes of physical activity', description_ar='٣٠ دقيقة نشاط بدني',
         emoji='⚽', category='health', default_recurrence='daily',
         image_filename='preset_exercise.png'),
 
    # ── Chores ────────────────────────────────────────────────
    dict(title='Set the Table',     title_ar='تجهيز الطاولة',
         description='Set plates and cutlery', description_ar='ضع الأطباق والأدوات',
         emoji='🍽️', category='chores', default_recurrence='daily',
         image_filename='preset_set_table.png'),
 
    dict(title='Help with Dishes',  title_ar='مساعدة في الأطباق',
         description='Rinse or dry the dishes', description_ar='اشطف أو جفف الأطباق',
         emoji='🧽', category='chores', default_recurrence='daily',
         image_filename='preset_dishes.png'),
 
    dict(title='Feed the Pet',      title_ar='إطعام الحيوان الأليف',
         description='Give food and fresh water', description_ar='قدّم طعاماً وماءً نظيفاً',
         emoji='🐾', category='chores', default_recurrence='daily',
         image_filename='preset_pet.png'),
 
    dict(title='Take out Trash',    title_ar='إخراج القمامة',
         description='Bring bin to the door', description_ar='أخرج سلة المهملات',
         emoji='🗑️', category='chores', default_recurrence='weekly',
         image_filename='preset_trash.png'),
 
    # ── Wellbeing ─────────────────────────────────────────────
    dict(title='Pray / Meditate',   title_ar='الصلاة / التأمل',
         description='Quiet time for reflection', description_ar='وقت هادئ للتأمل',
         emoji='🤲', category='wellbeing', default_recurrence='daily',
         image_filename='preset_pray.png'),
 
    dict(title='Say Thank You',     title_ar='قول شكراً',
         description='Thank someone today', description_ar='اشكر شخصاً ما اليوم',
         emoji='🙏', category='wellbeing', default_recurrence='daily',
         image_filename='preset_thanks.png'),
 
    dict(title='Screen-free Time',  title_ar='وقت بدون شاشات',
         description='1 hour without any screens', description_ar='ساعة بدون أي شاشات',
         emoji='📵', category='wellbeing', default_recurrence='daily',
         image_filename='preset_no_screen.png'),
]
 
CATEGORY_LABELS = {
    'morning':   ('🌅', 'Morning Routine',  'الروتين الصباحي'),
    'school':    ('📚', 'School',           'المدرسة'),
    'evening':   ('🌙', 'Evening Routine',  'الروتين المسائي'),
    'health':    ('💪', 'Health',           'الصحة'),
    'chores':    ('🏠', 'Chores',           'الأعمال المنزلية'),
    'wellbeing': ('🌟', 'Wellbeing',        'الرفاهية'),
}
 
 
def seed_presets():
    """
    Populate the preset_task table.
    Safe to call multiple times — skips presets that already exist.
 
    Call from Flask shell:
        from app.models import seed_presets
        seed_presets()
 
    Or add to __init__.py inside the app_context block:
        from app.models import seed_presets
        seed_presets()
    """
    from app import db
    added = 0
    for data in PRESET_DATA:
        exists = PresetTask.query.filter_by(title=data['title']).first()
        if not exists:
            db.session.add(PresetTask(**data))
            added += 1
    db.session.commit()
    print(f"[seed_presets] Added {added} preset tasks.")
    return added
 