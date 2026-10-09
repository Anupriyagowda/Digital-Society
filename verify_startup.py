import os
import sys

sys.path.insert(0, os.getcwd())

from app import create_app
from app.config import Config

class TConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

create_app(TConfig)
print('app-created')
