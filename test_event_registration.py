import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[0]))

from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta

from app import create_app, db
from app.config import Config
from app.models import Building, Flat, Resident, Role, User, Event, Participant


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False


def test_first_event_registration_shows_success():
    """Test that first-time registration for an event shows 'Registration Successful'"""
    app = create_app(TestConfig)
    
    with app.app_context():
        # Setup
        role = Role.query.filter_by(name='Resident').first()
        if not role:
            role = Role(name='Resident', description='Resident role')
            db.session.add(role)
            db.session.commit()
        
        building = Building(name='Test Building', address='Test Address')
        db.session.add(building)
        db.session.commit()
        
        flat = Flat(number='A-101', flat_type='2BHK', building_id=building.id, occupied=True)
        db.session.add(flat)
        db.session.commit()
        
        user = User(
            username='resident@example.com',
            email='resident@example.com',
            first_name='Test',
            last_name='Resident',
            phone='9876543210',
            password_hash=generate_password_hash('secret123'),
            role_id=role.id,
            is_verified=True,
            is_approved=True,
            is_active=True,
        )
        db.session.add(user)
        db.session.flush()
        
        resident = Resident(
            user_id=user.id,
            flat_id=flat.id,
            building_id=building.id,
            approval_status='Approved',
            status='Active',
            resident_type='Tenant'
        )
        db.session.add(resident)
        db.session.commit()
        
        event = Event(
            title='Test Event',
            description='A test event',
            start_date=datetime.utcnow() + timedelta(days=1),
            end_date=datetime.utcnow() + timedelta(days=2),
            location='Test Location',
            created_by_id=user.id,
            max_capacity=100,
            status='Active'
        )
        db.session.add(event)
        db.session.commit()
    
    with app.test_client() as client:
        # Login
        login_response = client.post(
            '/auth/login',
            data={
                'identifier': 'resident@example.com',
                'password': 'secret123',
                'role': 'resident',
            },
            follow_redirects=True,
        )
        assert login_response.status_code == 200
        
        # Get event details to verify we can access it
        with app.app_context():
            event = Event.query.first()
            event_id = event.id
        
        # First registration - should show "Registration Successful"
        registration_response = client.post(
            f'/events/{event_id}/register',
            data={},
            follow_redirects=True,
        )
        
        print("Response data:", registration_response.data.decode())
        assert registration_response.status_code == 200
        assert b'Registration Successful' in registration_response.data, "Should show 'Registration Successful' for first-time registration"
        
        # Verify participant was created
        with app.app_context():
            participant = Participant.query.filter_by(event_id=event_id).first()
            assert participant is not None, "Participant should be created in database"
            assert participant.status == 'Registered'
        
        # Second registration - should show "Already Registered"
        registration_response2 = client.post(
            f'/events/{event_id}/register',
            data={},
            follow_redirects=True,
        )
        
        print("Response data (2nd):", registration_response2.data.decode())
        assert registration_response2.status_code == 200
        # Check if it contains the message (case-insensitive search)
        response_data_lower = registration_response2.data.decode().lower()
        if b'Already Registered' not in registration_response2.data and 'already registered' not in response_data_lower:
            print("ERROR: 'Already Registered' message not found in second registration")
            print("Looking for flash message...")
            import re
            alerts = re.findall(r'<div class="alert[^>]*>([^<]+)</div>', registration_response2.data.decode())
            print("Found alerts:", alerts)
        assert b'Already Registered' in registration_response2.data or 'already registered' in response_data_lower, "Should show 'Already Registered' for duplicate registration"


if __name__ == '__main__':
    test_first_event_registration_shows_success()
    print("All tests passed!")
