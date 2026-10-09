import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[0]))

from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta

from app import create_app, db
from app.config import Config
from app.models import Building, Flat, Resident, Role, User, Event, Participant, Activity, ActivityParticipant, Notification


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False


def test_event_registration_with_activities():
    """Test registration for event with activities"""
    app = create_app(TestConfig)
    
    with app.app_context():
        # Setup
        role = Role.query.filter_by(name='Resident').first()
        owner_role = Role.query.filter_by(name='Owner').first()
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

        owner = User(
            username='event-owner@example.com',
            email='event-owner@example.com',
            first_name='Event',
            last_name='Owner',
            password_hash=generate_password_hash('secret123'),
            role_id=owner_role.id,
            is_approved=True,
            is_active=True,
        )
        db.session.add(owner)
        db.session.flush()
        owner_id = owner.id
        
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
            created_by_id=owner.id,
            max_capacity=100,
            status='Active'
        )
        db.session.add(event)
        db.session.flush()
        event_id = event.id
        
        activity1 = Activity(
            title='Activity 1',
            description='First activity',
            event_id=event.id,
            status='Active',
            max_participants=20,
            created_by_id=user.id
        )
        activity2 = Activity(
            title='Activity 2',
            description='Second activity',
            event_id=event.id,
            status='Active',
            max_participants=20,
            created_by_id=user.id
        )
        activity3 = Activity(
            title='Standalone Activity',
            description='Independent activity',
            status='Active',
            max_participants=20,
            created_by_id=owner.id,
        )
        db.session.add(activity1)
        db.session.add(activity2)
        db.session.add(activity3)
        db.session.commit()
        activity1_id = activity1.id
        activity2_id = activity2.id
        activity3_id = activity3.id
    
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
        
        # First registration - with activity 1
        print("\n=== First Registration (with Activity 1) ===")
        registration_response = client.post(
            f'/events/{event_id}/register',
            data={'activity_ids': [activity1_id]},
            follow_redirects=True,
        )
        
        print("Status Code:", registration_response.status_code)
        response_data = registration_response.data.decode()
        
        # Check for success message
        if b'Registration Successful' in registration_response.data:
            print("[PASS] Shows 'Registration Successful' for first-time registration with activity")
        else:
            print("[FAIL] Does NOT show 'Registration Successful'")
            print("Looking for alert messages...")
            import re
            alerts = re.findall(r'<div class="alert[^>]*>([^<]+)</div>', response_data)
            print("Found alerts:", alerts)
        
        # Verify participant was created
        with app.app_context():
            participant = Participant.query.filter_by(event_id=event_id).first()
            assert participant is not None, "Participant should be created in database"
            assert participant.status == 'Registered'
            
            activity_participant = ActivityParticipant.query.filter_by(
                activity_id=activity1_id,
                resident_id=participant.resident_id
            ).first()
            if activity_participant:
                print("[PASS] Activity participant created")
            else:
                print("[FAIL] Activity participant NOT created")
            assert Notification.query.filter_by(
                user_id=owner_id,
                title='New event registration',
            ).count() == 1
        
        # Second registration - try to add activity 2 (already registered for event)
        print("\n=== Second Registration (adding Activity 2) ===")
        registration_response2 = client.post(
            f'/events/{event_id}/register',
            data={'activity_ids': [activity2_id]},
            follow_redirects=True,
        )
        
        print("Status Code:", registration_response2.status_code)
        response_data2 = registration_response2.data.decode()
        
        # Check messages
        if b'Already Registered' in registration_response2.data:
            print("[PASS] Shows 'Already Registered' for re-registration")
            import re
            alerts = re.findall(r'<div class="alert[^>]*>([^<]+)</div>', response_data2)
            print("Alert message:", alerts)
        else:
            print("[FAIL] Does NOT show 'Already Registered'")
            import re
            alerts = re.findall(r'<div class="alert[^>]*>([^<]+)</div>', response_data2)
            print("Found alerts:", alerts)

        with app.app_context():
            assert Notification.query.filter_by(
                user_id=owner_id,
                title='New activity registration',
            ).count() == 1

        standalone_response = client.post(
            f'/resident/activity/{activity3_id}/register',
            follow_redirects=True,
        )
        assert standalone_response.status_code == 200

        with app.app_context():
            assert Notification.query.filter_by(
                user_id=owner_id,
                title='New activity registration',
            ).count() == 2


if __name__ == '__main__':
    test_event_registration_with_activities()
    print("\n=== Test Complete ===")
