#good action from the child  mean +points in the database
# parent can set list of good actions and the child will get a point for each good action and when the points reach a certain number the child will get a  reward from the parent
#the rewardlist can be predefined or open for the parent to set it as they want
from app import db
from app.models import User, GoodAction, Reward
from flask_login import current_user


def create_good_action(parent_id, name, points_value, description=""):
    """Parent creates a good action worth a certain number of points."""
    action = GoodAction(
        parent_id=parent_id,
        name=name,
        points_value=points_value,
        description=description
    )
    db.session.add(action)
    db.session.commit()
    return action


def get_good_actions(parent_id):
    """Get all good actions set by a parent."""
    return GoodAction.query.filter_by(parent_id=parent_id).all()


def delete_good_action(action_id, parent_id):
    action = GoodAction.query.get(action_id)
    if action and action.parent_id == parent_id:
        db.session.delete(action)
        db.session.commit()
        return True
    return False


def award_good_action(child_id, action_id):
    """
    Award a child points for completing a good action.
    Also checks if the child has reached any reward thresholds.
    """
    action = GoodAction.query.get(action_id)
    if not action:
        return None

    child = User.query.get(child_id)
    if not child:
        return None

    child.points += action.points_value
    db.session.commit()

    # Check if any reward threshold has been reached
    _check_reward_unlocked(child)
    return child.points


def create_reward(parent_id, name, points_threshold, description=""):
    """Parent defines a reward that unlocks when child reaches a points threshold."""
    reward = Reward(
        parent_id=parent_id,
        name=name,
        points_threshold=points_threshold,
        description=description
    )
    db.session.add(reward)
    db.session.commit()
    return reward


def get_rewards(parent_id):
    return Reward.query.filter_by(parent_id=parent_id).all()


def delete_reward(reward_id, parent_id):
    reward = Reward.query.get(reward_id)
    if reward and reward.parent_id == parent_id:
        db.session.delete(reward)
        db.session.commit()
        return True
    return False


def _check_reward_unlocked(child):
    """
    Internal helper: find the highest reward threshold the child has reached
    and mark it as unlocked if not already. Returns the reward or None.
    """
    # Rewards linked to the child via parent_id (child's parent)
    if not child.parent_id:
        return None
    rewards = Reward.query.filter_by(parent_id=child.parent_id).order_by(
        Reward.points_threshold.desc()
    ).all()
    for reward in rewards:
        if child.points >= reward.points_threshold and not reward.unlocked_for(child.id):
            reward.unlock(child.id)
            db.session.commit()
            return reward
    return None


# Predefined reward suggestions (parents can pick from these or create their own)
PREDEFINED_REWARDS = [
    {"name": "Extra Screen Time", "description": "30 minutes of extra screen time", "points_threshold": 10},
    {"name": "Choose Dinner", "description": "Pick what the family eats tonight", "points_threshold": 15},
    {"name": "Stay Up Late", "description": "30 extra minutes before bedtime", "points_threshold": 20},
    {"name": "Movie Night Pick", "description": "Choose the family movie", "points_threshold": 25},
    {"name": "Special Day Out", "description": "A trip to a place of your choice", "points_threshold": 50},
]
