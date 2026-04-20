#each task done on time will give the child one point
#if the task is done but not on time the child will get no points
#if there is more than threeshold of not doing the task on time the child will get a cross 
#if there is a good action the child will get a number of points based on how the list is set up
#if there is a bad action the child will get a number of cross based on how the list is set up

import datetime

from app.models import User, Task
from app import db
from flask_login import current_user

from sqlalchemy import func




def total_task_points(user_id):
    # Count only completed tasks directly in the database
    completed_count = db.session.query(Task).filter_by(
        user_id=user_id, 
        completion_status=True
    ).count()
    
    # Update the user
    user = User.query.get(user_id)
    if user:
        user.points = completed_count
        db.session.commit()