from datetime import datetime
from app import db, login_manager
from flask_login import UserMixin


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
    description = db.Column(db.Text, nullable=False)
    date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    time = db.Column(db.Time, nullable=False)
    completion_status = db.Column(db.Boolean, nullable=False, default=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    def __repr__(self):
        return f"Task('{self.title}', done={self.completion_status})"


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
    transaction_type = db.Column(db.String(20), nullable=False)  # 'income','expense','donation'
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