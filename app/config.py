import os
from dotenv import load_dotenv

load_dotenv()

basedir = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'fallback-secret-key'

    # Use DATABASE_URL for production (PostgreSQL) or fall back to SQLite
    SQLALCHEMY_DATABASE_URI = (
        os.environ.get('DATABASE_URL')
        or os.environ.get('SQLALCHEMY_DATABASE_URI')
        or 'sqlite:///' + os.path.join(basedir, 'site.db')
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False  # always False; no need to read from env

    WTF_CSRF_ENABLED = True
    # Use the same secret key for CSRF — reading SECRET_KEY from env here directly
    # so it doesn't depend on the class attribute being resolved first
    WTF_CSRF_SECRET_KEY = os.environ.get('WTF_CSRF_SECRET_KEY') or os.environ.get('SECRET_KEY') or 'fallback-secret-key'