import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app, db
from app.config import Config
from app.models import Building, Flat, Resident, Role, User
from werkzeug.security import generate_password_hash


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False


def test_owner_can_edit_resident_and_persist_changes():
    app = create_app(TestConfig)
    with app.test_client() as client:
        with app.app_context():
            owner_role = Role.query.filter_by(name='Owner').first()
            resident_role = Role.query.filter_by(name='Resident').first()
            owner = User(
                username='owner-edit',
                email='owner-edit@example.com',
                password_hash=generate_password_hash('ownerpass123'),
                first_name='Owner',
                last_name='Edit',
                role_id=owner_role.id,
                is_verified=True,
                is_approved=True,
                is_active=True,
            )
            db.session.add(owner)
            db.session.commit()

            building = Building(name='Test Building', address='Test Address')
            db.session.add(building)
            db.session.commit()

            flat = Flat(number='B-202', flat_type='2BHK', building_id=building.id, occupied=True)
            db.session.add(flat)
            db.session.commit()

            resident_user = User(
                username='resident-edit',
                email='resident-edit@example.com',
                password_hash=generate_password_hash('residentpass123'),
                first_name='Old',
                last_name='Resident',
                role_id=resident_role.id,
                is_verified=True,
                is_approved=True,
                is_active=True,
            )
            db.session.add(resident_user)
            db.session.commit()

            resident = Resident(
                user_id=resident_user.id,
                flat_id=flat.id,
                building_id=building.id,
                resident_type='Tenant',
                approval_status='Approved',
                status='Active',
            )
            db.session.add(resident)
            db.session.commit()
            resident_id = resident.id

        login_response = client.post(
            '/auth/login',
            data={'identifier': 'owner-edit@example.com', 'password': 'ownerpass123', 'role': 'owner'},
            follow_redirects=True,
        )
        assert login_response.status_code == 200

        edit_response = client.post(
            f'/owner/resident/{resident_id}/edit',
            data={
                'first_name': 'Updated',
                'last_name': 'Resident',
                'email': 'updated@example.com',
                'phone': '8888888888',
                'flat_number': 'B-202',
                'resident_type': 'Flat Owner',
                'emergency_contact': '7777777777',
            },
            follow_redirects=True,
        )
        assert edit_response.status_code == 200
        assert b'Resident details updated successfully.' in edit_response.data

        with app.app_context():
            refreshed_resident = Resident.query.get(resident_id)
            refreshed_user = User.query.get(refreshed_resident.user_id)
            assert refreshed_user.first_name == 'Updated'
            assert refreshed_user.email == 'updated@example.com'
            assert refreshed_user.phone == '8888888888'
            assert refreshed_resident.resident_type == 'Flat Owner'
            assert refreshed_resident.emergency_contact == '7777777777'


def test_owner_events_page_renders_without_build_error():
    app = create_app(TestConfig)
    with app.test_client() as client:
        with app.app_context():
            owner_role = Role.query.filter_by(name='Owner').first()
            owner = User(
                username='owner-events',
                email='owner-events@example.com',
                password_hash=generate_password_hash('ownerpass123'),
                first_name='Owner',
                last_name='Events',
                role_id=owner_role.id,
                is_verified=True,
                is_approved=True,
                is_active=True,
            )
            db.session.add(owner)
            db.session.commit()

        login_response = client.post(
            '/auth/login',
            data={'identifier': 'owner-events@example.com', 'password': 'ownerpass123', 'role': 'owner'},
            follow_redirects=True,
        )
        assert login_response.status_code == 200

        events_response = client.get('/owner/events', follow_redirects=True)
        assert events_response.status_code == 200
        assert b'Event Management' in events_response.data
