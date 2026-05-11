from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_wtf import CSRFProtect
from app.config import Config
from sqlalchemy import text

app = Flask(__name__)
app.config.from_object(Config)

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'
migrate = Migrate(app, db)
csrf = CSRFProtect(app)

# Import routes and models AFTER app/db are created to avoid circular imports
from app import routes, models

# Create tables automatically if they don't exist
with app.app_context():
    try:
        db.create_all()
        print("Database tables created successfully!")

        # Lightweight SQLite-only schema patching (no migrations folder in repo).
        # Adds new columns needed by newer code without requiring users to delete site.db.
        uri = (app.config.get('SQLALCHEMY_DATABASE_URI') or '')
        if uri.startswith('sqlite'):
            cols = [row[1] for row in db.session.execute(text('PRAGMA table_info(savings_goal)')).all()]
            if 'current_amount' not in cols:
                db.session.execute(text(
                    'ALTER TABLE savings_goal ADD COLUMN current_amount FLOAT NOT NULL DEFAULT 0.0'
                ))
                db.session.commit()

            turn_cols = [row[1] for row in db.session.execute(text('PRAGMA table_info(turn_group)')).all()]
            if 'selection_mode' not in turn_cols:
                db.session.execute(text(
                    "ALTER TABLE turn_group ADD COLUMN selection_mode VARCHAR(20) NOT NULL DEFAULT 'round_robin'"
                ))
                db.session.commit()
            if 'auto_advance_enabled' not in turn_cols:
                db.session.execute(text(
                    'ALTER TABLE turn_group ADD COLUMN auto_advance_enabled BOOLEAN NOT NULL DEFAULT 0'
                ))
                db.session.commit()
            if 'auto_advance_value' not in turn_cols:
                db.session.execute(text(
                    'ALTER TABLE turn_group ADD COLUMN auto_advance_value INTEGER'
                ))
                db.session.commit()
            if 'auto_advance_unit' not in turn_cols:
                db.session.execute(text(
                    "ALTER TABLE turn_group ADD COLUMN auto_advance_unit VARCHAR(10) NOT NULL DEFAULT 'minutes'"
                ))
                db.session.commit()
            if 'auto_advance_paused' not in turn_cols:
                db.session.execute(text(
                    'ALTER TABLE turn_group ADD COLUMN auto_advance_paused BOOLEAN NOT NULL DEFAULT 0'
                ))
                db.session.commit()

            if 'category' not in turn_cols:
                db.session.execute(text(
                    "ALTER TABLE turn_group ADD COLUMN category VARCHAR(20) NOT NULL DEFAULT 'clock'"
                ))
                db.session.commit()
            if 'grace_period_sec' not in turn_cols:
                db.session.execute(text(
                    'ALTER TABLE turn_group ADD COLUMN grace_period_sec INTEGER NOT NULL DEFAULT 120'
                ))
                db.session.commit()
            if 'deduct_overrun' not in turn_cols:
                db.session.execute(text(
                    'ALTER TABLE turn_group ADD COLUMN deduct_overrun BOOLEAN NOT NULL DEFAULT 1'
                ))
                db.session.commit()
            if 'penalty_enabled' not in turn_cols:
                db.session.execute(text(
                    'ALTER TABLE turn_group ADD COLUMN penalty_enabled BOOLEAN NOT NULL DEFAULT 0'
                ))
                db.session.commit()
            if 'penalty_crosses' not in turn_cols:
                db.session.execute(text(
                    'ALTER TABLE turn_group ADD COLUMN penalty_crosses INTEGER NOT NULL DEFAULT 3'
                ))
                db.session.commit()
            if 'penalty_minutes' not in turn_cols:
                db.session.execute(text(
                    'ALTER TABLE turn_group ADD COLUMN penalty_minutes INTEGER NOT NULL DEFAULT 15'
                ))
                db.session.commit()
            if 'cal_mode' not in turn_cols:
                db.session.execute(text(
                    "ALTER TABLE turn_group ADD COLUMN cal_mode VARCHAR(20) NOT NULL DEFAULT 'n_day'"
                ))
                db.session.commit()
            if 'cal_n_days' not in turn_cols:
                db.session.execute(text(
                    'ALTER TABLE turn_group ADD COLUMN cal_n_days INTEGER NOT NULL DEFAULT 1'
                ))
                db.session.commit()
            if 'cal_paused' not in turn_cols:
                db.session.execute(text(
                    'ALTER TABLE turn_group ADD COLUMN cal_paused BOOLEAN NOT NULL DEFAULT 0'
                ))
                db.session.commit()

            usage_cols = [row[1] for row in db.session.execute(text('PRAGMA table_info(turn_daily_usage)')).all()]
            if 'used_sec' not in usage_cols:
                db.session.execute(text(
                    'ALTER TABLE turn_daily_usage ADD COLUMN used_sec INTEGER NOT NULL DEFAULT 0'
                ))
                db.session.commit()
            if 'overrun_sec' not in usage_cols:
                db.session.execute(text(
                    'ALTER TABLE turn_daily_usage ADD COLUMN overrun_sec INTEGER NOT NULL DEFAULT 0'
                ))
                db.session.commit()

            member_cols = [row[1] for row in db.session.execute(text('PRAGMA table_info(turn_group_member)')).all()]
            if 'penalty_min_owed' not in member_cols:
                db.session.execute(text(
                    'ALTER TABLE turn_group_member ADD COLUMN penalty_min_owed INTEGER NOT NULL DEFAULT 0'
                ))
                db.session.commit()
            if 'birthday_mode' not in member_cols:
                db.session.execute(text(
                    'ALTER TABLE turn_group_member ADD COLUMN birthday_mode BOOLEAN NOT NULL DEFAULT 0'
                ))
                db.session.commit()
            if 'birthday_date' not in member_cols:
                db.session.execute(text(
                    'ALTER TABLE turn_group_member ADD COLUMN birthday_date DATE'
                ))
                db.session.commit()

            state_cols = [row[1] for row in db.session.execute(text('PRAGMA table_info(turn_day_state)')).all()]
            if 'active_child_id' not in state_cols:
                db.session.execute(text(
                    'ALTER TABLE turn_day_state ADD COLUMN active_child_id INTEGER'
                ))
                db.session.commit()
            if 'session_started_at' not in state_cols:
                db.session.execute(text(
                    'ALTER TABLE turn_day_state ADD COLUMN session_started_at DATETIME'
                ))
                db.session.commit()
            if 'turn_remaining_sec' not in state_cols:
                db.session.execute(text(
                    'ALTER TABLE turn_day_state ADD COLUMN turn_remaining_sec INTEGER'
                ))
                db.session.commit()
            if 'wheel_used' not in state_cols:
                db.session.execute(text(
                    'ALTER TABLE turn_day_state ADD COLUMN wheel_used BOOLEAN NOT NULL DEFAULT 0'
                ))
                db.session.commit()

            if 'grace_notified' not in state_cols:
                db.session.execute(text(
                    'ALTER TABLE turn_day_state ADD COLUMN grace_notified BOOLEAN NOT NULL DEFAULT 0'
                ))
                db.session.commit()
            if 'shared_child_ids' not in state_cols:
                db.session.execute(text(
                    'ALTER TABLE turn_day_state ADD COLUMN shared_child_ids TEXT'
                ))
                db.session.commit()
            if 'grace_started_at' not in state_cols:
                db.session.execute(text(
                    'ALTER TABLE turn_day_state ADD COLUMN grace_started_at DATETIME'
                ))
                db.session.commit()

            task_cols = [row[1] for row in db.session.execute(text('PRAGMA table_info(task)')).all()]
            if 'recurrence_interval_days' not in task_cols:
                db.session.execute(text(
                    'ALTER TABLE task ADD COLUMN recurrence_interval_days INTEGER'
                ))
                db.session.commit()
            if 'recurrence_monthly_ordinal' not in task_cols:
                db.session.execute(text(
                    'ALTER TABLE task ADD COLUMN recurrence_monthly_ordinal INTEGER'
                ))
                db.session.commit()
            if 'recurrence_monthly_weekday' not in task_cols:
                db.session.execute(text(
                    'ALTER TABLE task ADD COLUMN recurrence_monthly_weekday INTEGER'
                ))
                db.session.commit()
    except Exception as e:
        print(f"Database initialization warning: {e}")