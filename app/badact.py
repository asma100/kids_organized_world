#bad action from the child  mean +cross in the database
# parent can set list of bad actions and the child will get a cross for each bad action and when the cross reach a certain number the child will get a  punishment from the parent
#the punishmentlist can be predefined or open for the parent to set it as they want
from app import db
from app.models import User, BadAction, Punishment
from flask_login import current_user


def create_bad_action(parent_id, name, crosses_value, description=""):
    """Parent creates a bad action worth a certain number of crosses (penalties)."""
    action = BadAction(
        parent_id=parent_id,
        name=name,
        crosses_value=crosses_value,
        description=description
    )
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
    Assign crosses to a child for a bad action.
    Also checks if any punishment threshold has been reached.
    """
    action = BadAction.query.get(action_id)
    if not action:
        return None

    child = User.query.get(child_id)
    if not child:
        return None

    child.crosses = (child.crosses or 0) + action.crosses_value
    db.session.commit()

    # Check if any punishment threshold has been reached
    _check_punishment_triggered(child)
    return child.crosses


def create_punishment(parent_id, name, crosses_threshold, description=""):
    """Parent defines a punishment that triggers when child reaches a crosses threshold."""
    punishment = Punishment(
        parent_id=parent_id,
        name=name,
        crosses_threshold=crosses_threshold,
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


def _check_punishment_triggered(child):
    """Internal helper: check if the child's crosses have hit a punishment threshold."""
    if not child.parent_id:
        return None
    punishments = Punishment.query.filter_by(parent_id=child.parent_id).order_by(
        Punishment.crosses_threshold.desc()
    ).all()
    for punishment in punishments:
        if (child.crosses or 0) >= punishment.crosses_threshold:
            return punishment
    return None


# Predefined punishment suggestions
PREDEFINED_PUNISHMENTS = [
    {"name": "No Screen Time", "description": "No screens for today", "crosses_threshold": 3},
    {"name": "Early Bedtime", "description": "Bedtime 30 minutes earlier", "crosses_threshold": 5},
    {"name": "Extra Chores", "description": "One extra chore to complete", "crosses_threshold": 7},
    {"name": "No Dessert", "description": "No dessert for the day", "crosses_threshold": 4},
    {"name": "Quiet Time", "description": "30 minutes of quiet reflection", "crosses_threshold": 6},
]
