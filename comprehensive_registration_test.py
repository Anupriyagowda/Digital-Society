#!/usr/bin/env python
"""
Comprehensive test suite for registration functionality.
Tests all scenarios: first-time, re-registration, with/without activities.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[0]))

from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta
from app import create_app, db
from app.config import Config
from app.models import Building, Flat, Resident, Role, User, Event, Participant, Activity, ActivityParticipant


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False


def setup_test_data():
    """Creates test users, building, flat, event, and activities."""
    role = Role.query.filter_by(name='Resident').first()
    if not role:
        role = Role(name='Resident', description='Resident role')
        db.session.add(role)
        db.session.commit()
    
    owner_role = Role.query.filter_by(name='Owner').first()
    if not owner_role:
        owner_role = Role(name='Owner', description='Owner role')
        db.session.add(owner_role)
        db.session.commit()
    
    building = Building(name='Test Building', address='Test Address')
    db.session.add(building)
    db.session.commit()
    
    flat = Flat(number='A-101', flat_type='2BHK', building_id=building.id, occupied=True)
    db.session.add(flat)
    db.session.commit()
    
    owner = User(
        username='owner@example.com',
        email='owner@example.com',
        first_name='Owner',
        last_name='User',
        password_hash=generate_password_hash('secret123'),
        role_id=owner_role.id,
        is_verified=True,
        is_approved=True,
        is_active=True,
    )
    db.session.add(owner)
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
        created_by_id=owner.id,
        max_capacity=100,
        status='Active'
    )
    db.session.add(event)
    db.session.flush()
    
    activity1 = Activity(
        title='Activity 1',
        description='First activity',
        event_id=event.id,
        status='Active',
        max_participants=20,
        created_by_id=owner.id
    )
    activity2 = Activity(
        title='Activity 2',
        description='Second activity',
        event_id=event.id,
        status='Active',
        max_participants=20,
        created_by_id=owner.id
    )
    db.session.add_all([activity1, activity2])
    db.session.commit()
    
    return user.id, event.id, activity1.id, activity2.id


def test_scenario_1():
    """Event registration without activities (first-time and second-time)."""
    app = create_app(TestConfig)
    
    with app.app_context():
        user_id, event_id, _, _ = setup_test_data()
    
    with app.test_client() as client:
        # Login
        client.post('/auth/login', data={
            'identifier': 'resident@example.com',
            'password': 'secret123',
            'role': 'resident',
        }, follow_redirects=True)
        
        # First registration - no activities
        print("\n[SCENARIO 1] Event Registration Without Activities")
        print("=" * 60)
        
        resp1 = client.post(f'/events/{event_id}/register', data={}, follow_redirects=True)
        if b'Registration Successful' in resp1.data:
            print("[PASS] First registration shows 'Registration Successful'")
        else:
            print("[FAIL] First registration should show 'Registration Successful'")
            return False
        
        # Second registration - no activities
        resp2 = client.post(f'/events/{event_id}/register', data={}, follow_redirects=True)
        if b'Already Registered' in resp2.data:
            print("[PASS] Second registration shows 'Already Registered'")
        else:
            print("[FAIL] Second registration should show 'Already Registered'")
            return False
    
    return True


def test_scenario_2():
    """Event registration with activities (first-time and additional activities)."""
    app = create_app(TestConfig)
    
    with app.app_context():
        user_id, event_id, activity1_id, activity2_id = setup_test_data()
    
    with app.test_client() as client:
        # Login
        client.post('/auth/login', data={
            'identifier': 'resident@example.com',
            'password': 'secret123',
            'role': 'resident',
        }, follow_redirects=True)
        
        print("\n[SCENARIO 2] Event Registration With Activities")
        print("=" * 60)
        
        # First registration - with activity 1
        resp1 = client.post(f'/events/{event_id}/register', data={
            'activity_ids': [activity1_id]
        }, follow_redirects=True)
        
        if b'Registration Successful' in resp1.data:
            print("[PASS] First registration with activity shows 'Registration Successful'")
        else:
            print("[FAIL] First registration with activity should show 'Registration Successful'")
            return False
        
        # Second registration - try to add activity 2
        resp2 = client.post(f'/events/{event_id}/register', data={
            'activity_ids': [activity2_id]
        }, follow_redirects=True)
        
        if b'Already Registered' in resp2.data:
            print("[PASS] Second registration (different activity) shows 'Already Registered'")
        else:
            print("[FAIL] Second registration (different activity) should show 'Already Registered'")
            return False
    
    return True


def test_scenario_3():
    """Activity-only registration."""
    app = create_app(TestConfig)
    
    with app.app_context():
        user_id, event_id, activity1_id, _ = setup_test_data()
    
    with app.test_client() as client:
        # Login
        client.post('/auth/login', data={
            'identifier': 'resident@example.com',
            'password': 'secret123',
            'role': 'resident',
        }, follow_redirects=True)
        
        print("\n[SCENARIO 3] Activity-Only Registration")
        print("=" * 60)
        
        # First registration
        resp1 = client.post(f'/resident/activity/{activity1_id}/register', follow_redirects=True)
        
        if b'Registration Successful' in resp1.data:
            print("[PASS] First activity registration shows 'Registration Successful'")
        else:
            print("[FAIL] First activity registration should show 'Registration Successful'")
            return False
        
        # Second registration
        resp2 = client.post(f'/resident/activity/{activity1_id}/register', follow_redirects=True)
        
        if b'Already Registered' in resp2.data:
            print("[PASS] Second activity registration shows 'Already Registered'")
        else:
            print("[FAIL] Second activity registration should show 'Already Registered'")
            return False
    
    return True


if __name__ == '__main__':
    results = []
    
    try:
        results.append(("Scenario 1", test_scenario_1()))
    except Exception as e:
        print(f"[ERROR] Scenario 1: {e}")
        results.append(("Scenario 1", False))
    
    try:
        results.append(("Scenario 2", test_scenario_2()))
    except Exception as e:
        print(f"[ERROR] Scenario 2: {e}")
        results.append(("Scenario 2", False))
    
    try:
        results.append(("Scenario 3", test_scenario_3()))
    except Exception as e:
        print(f"[ERROR] Scenario 3: {e}")
        results.append(("Scenario 3", False))
    
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    all_passed = True
    for scenario, passed in results:
        status = "[PASS]" if passed else "[FAIL]"
        print(f"{status} {scenario}")
        all_passed = all_passed and passed
    
    print("=" * 60)
    if all_passed:
        print("All scenarios passed! Registration check is working correctly.")
        sys.exit(0)
    else:
        print("Some scenarios failed. Registration check needs fixes.")
        sys.exit(1)
