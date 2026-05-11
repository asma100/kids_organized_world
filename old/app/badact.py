from app import db
from app.models import User, BadAction, Punishment
from datetime import datetime


def create_bad_action(parent_id, name, crosses_value, description=""):
    action = BadAction(parent_id=parent_id, name=name,
                       crosses_value=crosses_value, description=description)
    db.session.add(action)
    db.session.commit()
    return action


def get_bad_actions(parent_id):
    return BadAction.query.filter_by(parent_id=parent_id).all()


def delete_bad_action(action_id, parent_id):
    action = BadAction.query.get(action_id)
    if action and action.parent_id == parent_id:
        db.session.delete(action)
        db.session.commit()
        return True
    return False


def assign_bad_action(child_id, action_id):
    """
    Add crosses to a child and check if a punishment is now triggered.
    """
    action = BadAction.query.get(action_id)
    child = User.query.get(child_id)
    if not action or not child:
        return None
    child.crosses = (child.crosses or 0) + action.crosses_value
    db.session.commit()
    return child.crosses


def serve_punishment(child_id, punishment_id):
    """
    Parent marks a punishment as served.
    Deducts crosses_cost from the child's cross count.
    Returns (success: bool, message: str).
    """
    child = User.query.get(child_id)
    punishment = Punishment.query.get(punishment_id)
    if not child or not punishment:
        return False, "Punishment not found."

    if punishment.crosses_cost > 0:
        child.crosses = max(0, (child.crosses or 0) - punishment.crosses_cost)

    punishment.used = True
    punishment.used_at = datetime.utcnow()
    db.session.commit()
    return True, f'Punishment "{punishment.name}" marked as served.'


def create_punishment(parent_id, name, crosses_threshold,
                      description="", crosses_cost=None):
    # Default cost = full threshold
    if crosses_cost is None:
        crosses_cost = crosses_threshold
    punishment = Punishment(
        parent_id=parent_id, name=name,
        crosses_threshold=crosses_threshold,
        crosses_cost=crosses_cost,
        description=description
    )
    db.session.add(punishment)
    db.session.commit()
    return punishment


def get_punishments(parent_id):
    return Punishment.query.filter_by(parent_id=parent_id).all()


def delete_punishment(punishment_id, parent_id):
    punishment = Punishment.query.get(punishment_id)
    if punishment and punishment.parent_id == parent_id:
        db.session.delete(punishment)
        db.session.commit()
        return True
    return False


# Predefined punishment suggestions
PREDEFINED_PUNISHMENTS = [
    {"name": "No Screen Time", "description": "No screens for today", "crosses_threshold": 3},
    {"name": "Early Bedtime", "description": "Bedtime 30 minutes earlier", "crosses_threshold": 5},
    {"name": "Extra Chores", "description": "One extra chore to complete", "crosses_threshold": 7},
    {"name": "No Dessert", "description": "No dessert for the day", "crosses_threshold": 4},
    {"name": "Quiet Time", "description": "30 minutes of quiet reflection", "crosses_threshold": 6},
]
