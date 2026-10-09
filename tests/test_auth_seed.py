import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app, db
from app.config import Config
from app.models import Role


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False


def test_create_app_seeds_required_roles():
    app = create_app(TestConfig)
    with app.app_context():
        roles = {role.name for role in Role.query.all()}
        assert 'Resident' in roles
        assert 'Owner' in roles
        assert 'Super Admin' in roles
