from app import db
from app.models import User, GoodAction, Reward, RewardUnlock
from datetime import datetime


def create_good_action(parent_id, name, points_value, description=""):
    action = GoodAction(parent_id=parent_id, name=name,
                        points_value=points_value, description=description)
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
    Award points and auto-unlock any newly eligible rewards.
    """
    action = GoodAction.query.get(action_id)
    child = User.query.get(child_id)
    if not action or not child:
        return None
    child.points += action.points_value
    db.session.commit()
    _check_reward_unlocks(child)
    return child.points


def use_reward(child_id, reward_id):
    """
    Redeem an unlocked reward.
    Deducts points_cost and marks it used.
    Returns (success: bool, message: str).
    """
    child = User.query.get(child_id)
    reward = Reward.query.get(reward_id)
    if not child or not reward:
        return False, "Reward not found."

    unlock = RewardUnlock.query.filter_by(
        child_id=child_id, reward_id=reward_id
    ).first()

    # If the child already meets the threshold but the unlock row doesn't exist
    # yet (common when rewards are created after points were earned), create it.
    if not unlock:
        is_owner = (reward.parent_id == child.parent_id) or (reward.parent_id == child.id)
        if is_owner and child.points >= reward.points_threshold:
            reward.unlock(child.id)
            db.session.commit()
            unlock = RewardUnlock.query.filter_by(
                child_id=child_id, reward_id=reward_id
            ).first()

    if not unlock:
        return False, "You haven't unlocked this reward yet."
    if unlock.used:
        return False, "You already used this reward."

    if reward.points_cost > 0:
        if child.points < reward.points_cost:
            return False, (f"Not enough points — need {reward.points_cost}, "
                           f"you have {child.points}.")
        child.points -= reward.points_cost

    unlock.used = True
    unlock.used_at = datetime.utcnow()
    db.session.commit()
    return True, f'🎉 "{reward.name}" redeemed! Enjoy!'


def create_reward(parent_id, name, points_threshold,
                  description="", points_cost=None):
    # Default cost = full threshold (spending what you earned)
    if points_cost is None:
        points_cost = points_threshold
    reward = Reward(parent_id=parent_id, name=name,
                    points_threshold=points_threshold,
                    points_cost=points_cost,
                    description=description)
    db.session.add(reward)
    db.session.commit()

    # Auto-unlock for any children of this parent who already have enough points.
    eligible_children = User.query.filter_by(parent_id=parent_id).all()
    for child in eligible_children:
        if child.points >= reward.points_threshold:
            reward.unlock(child.id)
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


def _check_reward_unlocks(child):
    # Consider rewards created by the child's parent. If the child has no parent
    # recorded (data inconsistency or single-user setup), also consider rewards
    # that belong to the child. This makes unlocking more robust in practice.
    parent_id = child.parent_id
    if parent_id is None:
        # fallback: include rewards authored by the child itself
        rewards = Reward.query.filter_by(parent_id=child.id).all()
    else:
        rewards = Reward.query.filter_by(parent_id=parent_id).all()

    for reward in rewards:
        if child.points >= reward.points_threshold:
            reward.unlock(child.id)
    db.session.commit()


# Predefined reward suggestions (parents can pick from these or create their own)
PREDEFINED_REWARDS = [
    {"name": "Extra Screen Time", "description": "30 minutes of extra screen time", "points_threshold": 10},
    {"name": "Choose Dinner", "description": "Pick what the family eats tonight", "points_threshold": 15},
    {"name": "Stay Up Late", "description": "30 extra minutes before bedtime", "points_threshold": 20},
    {"name": "Movie Night Pick", "description": "Choose the family movie", "points_threshold": 25},
    {"name": "Special Day Out", "description": "A trip to a place of your choice", "points_threshold": 50},
]
