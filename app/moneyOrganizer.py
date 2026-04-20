#money organizer for the child money to learn how to manage it and save it for the future and also to learn how to spend it wisely and not waste it on things that are not important
#it will track:1. how much money the child has and will update when the kid get more money or spend it on something
#2. the child can set a goal for saving money and when the child reach the goal the child will get a reward from the parent
#3. the child can divide the money into different categories like: saving, spending, and donating and the child can set a percentage for each category and the child will get a reward from the parent when the child reach the percentage for each category
from app import db
from app.models import User, MoneyAccount, MoneyTransaction, SavingsGoal
from datetime import datetime


# Default category split percentages (can be overridden per child)
DEFAULT_CATEGORIES = {
    "saving": 50,
    "spending": 40,
    "donating": 10,
}


def get_or_create_account(child_id):
    """Get the child's money account, creating it if it doesn't exist."""
    account = MoneyAccount.query.filter_by(child_id=child_id).first()
    if not account:
        account = MoneyAccount(
            child_id=child_id,
            total_balance=0.0,
            saving_balance=0.0,
            spending_balance=0.0,
            donating_balance=0.0,
            saving_pct=DEFAULT_CATEGORIES["saving"],
            spending_pct=DEFAULT_CATEGORIES["spending"],
            donating_pct=DEFAULT_CATEGORIES["donating"],
        )
        db.session.add(account)
        db.session.commit()
    return account


def add_money(child_id, amount, note=""):
    """
    Add money to a child's account.
    Automatically splits it into saving / spending / donating buckets
    based on the child's configured percentages.
    """
    if amount <= 0:
        return None

    account = get_or_create_account(child_id)

    saving_share = round(amount * account.saving_pct / 100, 2)
    spending_share = round(amount * account.spending_pct / 100, 2)
    donating_share = round(amount - saving_share - spending_share, 2)  # remainder avoids rounding gaps

    account.total_balance += amount
    account.saving_balance += saving_share
    account.spending_balance += spending_share
    account.donating_balance += donating_share

    transaction = MoneyTransaction(
        child_id=child_id,
        amount=amount,
        transaction_type="income",
        note=note,
        timestamp=datetime.utcnow()
    )
    db.session.add(transaction)
    db.session.commit()

    _check_savings_goal(child_id, account)
    return account


def spend_money(child_id, amount, note=""):
    """
    Deduct from the spending bucket.
    Returns None if insufficient spending funds.
    """
    if amount <= 0:
        return None

    account = get_or_create_account(child_id)
    if account.spending_balance < amount:
        return None  # not enough spending money

    account.spending_balance -= amount
    account.total_balance -= amount

    transaction = MoneyTransaction(
        child_id=child_id,
        amount=-amount,
        transaction_type="expense",
        note=note,
        timestamp=datetime.utcnow()
    )
    db.session.add(transaction)
    db.session.commit()
    return account


def donate_money(child_id, amount, note=""):
    """Deduct from the donating bucket."""
    if amount <= 0:
        return None

    account = get_or_create_account(child_id)
    if account.donating_balance < amount:
        return None

    account.donating_balance -= amount
    account.total_balance -= amount

    transaction = MoneyTransaction(
        child_id=child_id,
        amount=-amount,
        transaction_type="donation",
        note=note,
        timestamp=datetime.utcnow()
    )
    db.session.add(transaction)
    db.session.commit()
    return account


def set_category_percentages(child_id, saving_pct, spending_pct, donating_pct):
    """Update the auto-split percentages for a child's account."""
    if saving_pct + spending_pct + donating_pct != 100:
        return None  # must add up to 100%

    account = get_or_create_account(child_id)
    account.saving_pct = saving_pct
    account.spending_pct = spending_pct
    account.donating_pct = donating_pct
    db.session.commit()
    return account


def create_savings_goal(child_id, name, target_amount, reward_description=""):
    """Set a savings goal for a child."""
    goal = SavingsGoal(
        child_id=child_id,
        name=name,
        target_amount=target_amount,
        reward_description=reward_description,
        achieved=False
    )
    db.session.add(goal)
    db.session.commit()
    return goal


def get_savings_goals(child_id):
    return SavingsGoal.query.filter_by(child_id=child_id).all()


def get_transactions(child_id, limit=20):
    return MoneyTransaction.query.filter_by(child_id=child_id)\
        .order_by(MoneyTransaction.timestamp.desc()).limit(limit).all()


def _check_savings_goal(child_id, account):
    """Mark any unachieved savings goals as achieved if target is reached."""
    goals = SavingsGoal.query.filter_by(child_id=child_id, achieved=False).all()
    for goal in goals:
        if account.saving_balance >= goal.target_amount:
            goal.achieved = True
            db.session.commit()
