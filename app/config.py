import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key')
    SOCIETY_NAME = os.environ.get('SOCIETY_NAME', 'Digital Society')
    RAZORPAY_KEY_ID = os.environ.get('RAZORPAY_KEY_ID', '')
    RAZORPAY_KEY_SECRET = os.environ.get('RAZORPAY_KEY_SECRET', '')
    AUTO_BILL_GENERATION_DAY = int(os.environ.get('AUTO_BILL_GENERATION_DAY', 1))
    AUTO_BILL_GENERATION_TIME = os.environ.get('AUTO_BILL_GENERATION_TIME', '09:00')
    AUTO_BILL_DUE_DAY = int(os.environ.get('AUTO_BILL_DUE_DAY', 4))
    AUTO_TENANT_RENT_AMOUNT = float(os.environ.get('AUTO_TENANT_RENT_AMOUNT', 0))
    BILL_DUE_SOON_DAYS = int(os.environ.get('BILL_DUE_SOON_DAYS', 3))
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', f'sqlite:///{BASE_DIR / "digital_society.db"}')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'localhost')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 1025))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'false').lower() == 'true'
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME', '')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD', '')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', 'noreply@digitalsociety.local')
    UPLOAD_FOLDER = BASE_DIR / 'uploads'
    REPORT_FOLDER = BASE_DIR / 'reports'
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024
