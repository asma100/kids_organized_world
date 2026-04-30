from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_login import LoginManager
from flask_migrate import Migrate
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
    except Exception as e:
        print(f"Database initialization warning: {e}")