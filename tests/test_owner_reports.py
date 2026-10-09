import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from werkzeug.security import generate_password_hash

from app import create_app, db
from app.config import Config
from app.models import Feedback, Resident, Role, User


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False


def test_owner_reports_show_resident_feedback_entries():
    app = create_app(TestConfig)
    with app.app_context():
        owner_role = Role.query.filter_by(name='Owner').first()
        resident_role = Role.query.filter_by(name='Resident').first()

        owner = User(
            username='owner_report@example.com',
            email='owner_report@example.com',
            first_name='Owner',
            password_hash=generate_password_hash('secret123'),
            role_id=owner_role.id,
            is_verified=True,
            is_approved=True,
            is_active=True,
        )
        resident = User(
            username='resident_report@example.com',
            email='resident_report@example.com',
            first_name='Resident',
            password_hash=generate_password_hash('secret123'),
            role_id=resident_role.id,
            is_verified=True,
            is_approved=True,
            is_active=True,
        )
        db.session.add_all([owner, resident])
        db.session.flush()
        db.session.add(Resident(user_id=resident.id, approval_status='Approved', status='Active'))
        db.session.commit()

        resident_record = Resident.query.filter_by(user_id=resident.id).first()
        db.session.add(Feedback(
            resident_id=resident_record.id,
            rating=5,
            category='Security',
            comment='Very satisfied with the gate security and response time.'
        ))
        db.session.commit()

    with app.test_client() as client:
        login_response = client.post(
            '/auth/login',
            data={'identifier': 'owner_report@example.com', 'password': 'secret123', 'role': 'owner'},
            follow_redirects=True,
        )
        assert login_response.status_code == 200

        response = client.get('/owner/reports', follow_redirects=True)
        assert response.status_code == 200
        page = response.get_data(as_text=True)
        assert '5.0/5' in page
        assert 'Very satisfied with the gate security and response time.' in page
