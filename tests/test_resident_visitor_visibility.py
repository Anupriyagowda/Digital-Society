import sys
from datetime import datetime
from pathlib import Path
import re

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app, db
from app.config import Config
from app.models import Activity, Building, Event, Flat, Memo, Participant, Resident, Role, User, Visitor
from werkzeug.security import generate_password_hash


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False


def test_resident_only_sees_visitors_for_their_own_flat():
    app = create_app(TestConfig)
    with app.test_client() as client:
        with app.app_context():
            resident_role = Role.query.filter_by(name='Resident').first()
            building = Building(name='Test Building', address='Test Address')
            db.session.add(building)
            db.session.commit()

            flat_a = Flat(number='A-101', flat_type='2BHK', building_id=building.id, occupied=True)
            flat_b = Flat(number='A-102', flat_type='2BHK', building_id=building.id, occupied=True)
            db.session.add_all([flat_a, flat_b])
            db.session.commit()

            resident_user_a = User(
                username='resident-a',
                email='resident-a@example.com',
                password_hash=generate_password_hash('residentpass123'),
                first_name='Resident',
                last_name='A',
                role_id=resident_role.id,
                is_verified=True,
                is_approved=True,
                is_active=True,
            )
            db.session.add(resident_user_a)
            db.session.commit()

            resident_a = Resident(user_id=resident_user_a.id, flat_id=flat_a.id, building_id=building.id, resident_type='Flat Owner', approval_status='Approved', status='Active')
            db.session.add(resident_a)
            db.session.commit()

            resident_user_b = User(
                username='resident-b',
                email='resident-b@example.com',
                password_hash=generate_password_hash('residentpass123'),
                first_name='Resident',
                last_name='B',
                role_id=resident_role.id,
                is_verified=True,
                is_approved=True,
                is_active=True,
            )
            db.session.add(resident_user_b)
            db.session.commit()

            resident_b = Resident(user_id=resident_user_b.id, flat_id=flat_b.id, building_id=building.id, resident_type='Tenant', approval_status='Approved', status='Active')
            db.session.add(resident_b)
            db.session.commit()

            db.session.add(Visitor(full_name='Other Visitor', phone='9999999999', purpose='Visit', resident_id=resident_b.id, flat_number=flat_b.number, status='Pending Approval'))
            db.session.add(Visitor(full_name='My Visitor', phone='8888888888', purpose='Delivery', resident_id=resident_a.id, flat_number=flat_a.number, status='Pending Approval'))
            db.session.commit()

        login_response = client.post(
            '/auth/login',
            data={'identifier': 'resident-a@example.com', 'password': 'residentpass123', 'role': 'resident'},
            follow_redirects=True,
        )
        assert login_response.status_code == 200

        response = client.get('/resident/visitors')
        assert response.status_code == 200
        body = response.get_data(as_text=True)
        assert 'My Visitor' in body
        assert 'Other Visitor' not in body


def test_security_dashboard_renders_when_memo_has_missing_resident():
    app = create_app(TestConfig)
    with app.test_client() as client:
        with app.app_context():
            security_role = Role.query.filter_by(name='Security Guard').first()
            security_user = User(
                username='security-only',
                email='security-only@example.com',
                password_hash=generate_password_hash('securitypass123'),
                first_name='Sam',
                last_name='Guard',
                role_id=security_role.id,
                is_verified=True,
                is_approved=True,
                is_active=True,
            )
            db.session.add(security_user)
            db.session.commit()
            db.session.add(Memo(resident_id=999999, title='Broken memo', content='Missing resident context', status='Pending'))
            db.session.commit()

        login_response = client.post(
            '/auth/login',
            data={'identifier': 'security-only@example.com', 'password': 'securitypass123', 'role': 'security'},
            follow_redirects=True,
        )
        assert login_response.status_code == 200

        response = client.get('/security/')
        assert response.status_code == 200
        body = response.get_data(as_text=True)
        assert 'Broken memo' in body


def test_security_dashboard_shows_memo_source_and_checkout_action():
    app = create_app(TestConfig)
    with app.test_client() as client:
        with app.app_context():
            resident_role = Role.query.filter_by(name='Resident').first()
            security_role = Role.query.filter_by(name='Security Guard').first()
            building = Building(name='Security Building', address='Security Address')
            db.session.add(building)
            db.session.commit()

            flat = Flat(number='B-204', flat_type='2BHK', building_id=building.id, occupied=True)
            db.session.add(flat)
            db.session.commit()

            resident_user = User(
                username='resident-security',
                email='resident-security@example.com',
                password_hash=generate_password_hash('residentpass123'),
                first_name='Mina',
                last_name='Patel',
                role_id=resident_role.id,
                is_verified=True,
                is_approved=True,
                is_active=True,
            )
            security_user = User(
                username='security-guard',
                email='security-guard@example.com',
                password_hash=generate_password_hash('securitypass123'),
                first_name='Ravi',
                last_name='Sharma',
                role_id=security_role.id,
                is_verified=True,
                is_approved=True,
                is_active=True,
            )
            db.session.add_all([resident_user, security_user])
            db.session.commit()

            resident = Resident(user_id=resident_user.id, flat_id=flat.id, building_id=building.id, resident_type='Flat Owner', approval_status='Approved', status='Active')
            db.session.add(resident)
            db.session.commit()

            memo = Memo(resident_id=resident.id, title='Gate access change', content='Please note the visitor policy update.', status='Pending')
            visitor = Visitor(
                full_name='Nina Guest',
                phone='7777777777',
                purpose='Visit',
                resident_id=resident.id,
                flat_number=flat.number,
                entry_time=datetime.utcnow(),
                status='Approved',
            )
            db.session.add_all([memo, visitor])
            db.session.commit()
            visitor_id = visitor.id

        login_response = client.post(
            '/auth/login',
            data={'identifier': 'security-guard@example.com', 'password': 'securitypass123', 'role': 'security'},
            follow_redirects=True,
        )
        assert login_response.status_code == 200

        dashboard_response = client.get('/security/')
        assert dashboard_response.status_code == 200
        body = dashboard_response.get_data(as_text=True)
        assert 'Mina Patel' in body
        assert 'B-204' in body
        assert 'Allow entry' in body

        checkin_response = client.post(f'/security/visitor/{visitor_id}/allow-entry', follow_redirects=True)
        assert checkin_response.status_code == 200
        with app.app_context():
            checked_in_visitor = db.session.get(Visitor, visitor_id)
            assert checked_in_visitor.status == 'Checked In'
            assert checked_in_visitor.check_in is not None

        dashboard_response = client.get('/security/')
        assert b'Check Out' in dashboard_response.data

        checkout_response = client.post(f'/security/visitor/{visitor_id}/check-out', follow_redirects=True)
        assert checkout_response.status_code == 200

        with app.app_context():
            updated_visitor = Visitor.query.get(visitor_id)
            assert updated_visitor.status == 'Checked Out'
            assert updated_visitor.check_out is not None


def test_security_email_includes_visitor_details_and_allows_without_login(monkeypatch):
    sent_emails = []
    monkeypatch.setattr(
        'app.routes.security.email_user',
        lambda user, subject, body, html=None: sent_emails.append((user, subject, body, html)),
    )
    monkeypatch.setattr('app.routes.security.email_admins', lambda *args, **kwargs: 1)
    app = create_app(TestConfig)
    with app.test_client() as client:
        with app.app_context():
            resident_role = Role.query.filter_by(name='Resident').first()
            security_role = Role.query.filter_by(name='Security Guard').first()
            building = Building(name='Visitor Approval Building', address='Test Address')
            db.session.add(building)
            db.session.commit()
            flat = Flat(number='V-305', flat_type='2BHK', building_id=building.id, occupied=True)
            db.session.add(flat)
            db.session.commit()

            resident_user = User(
                username='resident-visitor-approval',
                email='resident-visitor-approval@example.com',
                password_hash=generate_password_hash('residentpass123'),
                first_name='Mina',
                last_name='Patel',
                role_id=resident_role.id,
                is_verified=True,
                is_approved=True,
                is_active=True,
            )
            security_user = User(
                username='security-visitor-approval',
                email='security-visitor-approval@example.com',
                password_hash=generate_password_hash('securitypass123'),
                first_name='Ravi',
                last_name='Guard',
                role_id=security_role.id,
                is_verified=True,
                is_approved=True,
                is_active=True,
            )
            db.session.add_all([resident_user, security_user])
            db.session.commit()
            resident = Resident(
                user_id=resident_user.id,
                flat_id=flat.id,
                building_id=building.id,
                resident_type='Flat Owner',
                approval_status='Approved',
                status='Active',
            )
            db.session.add(resident)
            db.session.commit()

        login_response = client.post(
            '/auth/login',
            data={'identifier': 'security-visitor-approval@example.com', 'password': 'securitypass123', 'role': 'security'},
            follow_redirects=True,
        )
        assert login_response.status_code == 200

        request_response = client.post('/security/visitor/new', data={
            'full_name': 'Asha Visitor',
            'phone': '9876543210',
            'purpose': 'Family visit',
            'entry_time': '2026-10-04T14:30',
            'flat_number': 'V-305',
        }, follow_redirects=True)
        assert request_response.status_code == 200
        assert len(sent_emails) == 1
        assert sent_emails[0][1] == 'Visitor request pending approval'
        for detail in ('Asha Visitor', '9876543210', 'Family visit', 'V-305', '04 Oct 2026, 02:30 PM'):
            assert detail in sent_emails[0][2]
            assert detail in sent_emails[0][3]

        approval_match = re.search(r'/security/visitor/approval/(\S+)', sent_emails[0][2])
        assert approval_match
        approval_url = f'/security/visitor/approval/{approval_match.group(1)}'
        with app.app_context():
            visitor = Visitor.query.filter_by(full_name='Asha Visitor').one()
            visitor_id = visitor.id

        client.get('/auth/logout')
        confirmation_response = client.get(approval_url)
        assert confirmation_response.status_code == 200
        assert b'Allow visitor' in confirmation_response.data
        assert b'Reject visitor' in confirmation_response.data
        with app.app_context():
            assert db.session.get(Visitor, visitor_id).status == 'Pending Approval'

        allow_response = client.post(approval_url, data={'decision': 'allow'}, follow_redirects=True)
        assert allow_response.status_code == 200
        assert b'Visitor approved' in allow_response.data
        with app.app_context():
            assert db.session.get(Visitor, visitor_id).status == 'Approved'

        approved_page = client.get(approval_url)
        assert b'Status' in approved_page.data
        assert b'Approved' in approved_page.data
        assert b'Reject visitor' in approved_page.data
        assert 'no-store' in approved_page.headers['Cache-Control']
        reject_response = client.post(approval_url, data={'decision': 'reject'}, follow_redirects=True)
        assert reject_response.status_code == 200
        assert b'Visitor request rejected' in reject_response.data
        assert b'Visitor approved. Security has been notified.' not in reject_response.data
        with app.app_context():
            assert db.session.get(Visitor, visitor_id).status == 'Rejected'
        assert b'Rejected' in reject_response.data


def test_activity_registration_shows_success_then_already_registered():
    app = create_app(TestConfig)
    with app.test_client() as client:
        with app.app_context():
            resident_role = Role.query.filter_by(name='Resident').first()
            owner_role = Role.query.filter_by(name='Owner').first()
            building = Building(name='Activity Building', address='Apartment block')
            db.session.add(building)
            db.session.commit()

            flat = Flat(number='C-101', flat_type='2BHK', building_id=building.id, occupied=True)
            db.session.add(flat)
            db.session.commit()

            owner = User(
                username='owner-activity',
                email='owner-activity@example.com',
                password_hash=generate_password_hash('ownerpass123'),
                first_name='Owner',
                last_name='User',
                role_id=owner_role.id,
                is_verified=True,
                is_approved=True,
                is_active=True,
            )
            resident_user = User(
                username='resident-activity',
                email='resident-activity@example.com',
                password_hash=generate_password_hash('residentpass123'),
                first_name='Resident',
                last_name='Activity',
                role_id=resident_role.id,
                is_verified=True,
                is_approved=True,
                is_active=True,
            )
            db.session.add_all([owner, resident_user])
            db.session.commit()

            resident = Resident(user_id=resident_user.id, flat_id=flat.id, building_id=building.id, resident_type='Flat Owner', approval_status='Approved', status='Active')
            db.session.add(resident)
            db.session.commit()

            activity = Activity(
                title='Yoga Class',
                description='Morning yoga',
                max_participants=5,
                status='Active',
                created_by_id=owner.id,
            )
            db.session.add(activity)
            db.session.commit()

        login_response = client.post(
            '/auth/login',
            data={'identifier': 'resident-activity@example.com', 'password': 'residentpass123', 'role': 'resident'},
            follow_redirects=True,
        )
        assert login_response.status_code == 200

        first_response = client.post('/resident/activity/1/register', follow_redirects=True)
        assert first_response.status_code == 200
        assert 'Registration Successful' in first_response.get_data(as_text=True)

        second_response = client.post('/resident/activity/1/register', follow_redirects=True)
        assert second_response.status_code == 200
        body = second_response.get_data(as_text=True)
        assert 'Already Registered' in body


def test_event_registration_shows_success_then_already_registered():
    app = create_app(TestConfig)
    with app.test_client() as client:
        with app.app_context():
            resident_role = Role.query.filter_by(name='Resident').first()
            owner_role = Role.query.filter_by(name='Owner').first()
            building = Building(name='Event Building', address='Event place')
            db.session.add(building)
            db.session.commit()

            flat = Flat(number='D-201', flat_type='2BHK', building_id=building.id, occupied=True)
            db.session.add(flat)
            db.session.commit()

            owner = User(
                username='owner-event',
                email='owner-event@example.com',
                password_hash=generate_password_hash('ownerpass123'),
                first_name='Owner',
                last_name='Event',
                role_id=owner_role.id,
                is_verified=True,
                is_approved=True,
                is_active=True,
            )
            resident_user = User(
                username='resident-event',
                email='resident-event@example.com',
                password_hash=generate_password_hash('residentpass123'),
                first_name='Class',
                last_name='Resident',
                role_id=resident_role.id,
                is_verified=True,
                is_approved=True,
                is_active=True,
            )
            db.session.add_all([owner, resident_user])
            db.session.commit()

            resident = Resident(user_id=resident_user.id, flat_id=flat.id, building_id=building.id, resident_type='Flat Owner', approval_status='Approved', status='Active')
            db.session.add(resident)
            db.session.commit()

            event = Event(
                title='Community Meetup',
                description='Neighborhood event',
                start_date=datetime.utcnow(),
                end_date=datetime.utcnow(),
                location='Clubhouse',
                created_by_id=owner.id,
                max_capacity=20,
                event_type='General',
                status='Active',
            )
            db.session.add(event)
            db.session.commit()

        login_response = client.post(
            '/auth/login',
            data={'identifier': 'resident-event@example.com', 'password': 'residentpass123', 'role': 'resident'},
            follow_redirects=True,
        )
        assert login_response.status_code == 200

        first_response = client.post('/events/1/register', follow_redirects=True)
        assert first_response.status_code == 200
        assert 'Registration Successful' in first_response.get_data(as_text=True)

        second_response = client.post('/events/1/register', follow_redirects=True)
        assert second_response.status_code == 200
        body = second_response.get_data(as_text=True)
        assert 'Already Registered' in body


def test_event_registration_after_cancellation_can_be_reactivated():
    app = create_app(TestConfig)
    with app.test_client() as client:
        with app.app_context():
            resident_role = Role.query.filter_by(name='Resident').first()
            owner_role = Role.query.filter_by(name='Owner').first()
            building = Building(name='Event Rejoin Building', address='Rejoin place')
            db.session.add(building)
            db.session.commit()

            flat = Flat(number='E-301', flat_type='2BHK', building_id=building.id, occupied=True)
            db.session.add(flat)
            db.session.commit()

            owner = User(
                username='owner-event-rejoin',
                email='owner-event-rejoin@example.com',
                password_hash=generate_password_hash('ownerpass123'),
                first_name='Owner',
                last_name='Rejoin',
                role_id=owner_role.id,
                is_verified=True,
                is_approved=True,
                is_active=True,
            )
            resident_user = User(
                username='resident-event-rejoin',
                email='resident-event-rejoin@example.com',
                password_hash=generate_password_hash('residentpass123'),
                first_name='Rejoin',
                last_name='Resident',
                role_id=resident_role.id,
                is_verified=True,
                is_approved=True,
                is_active=True,
            )
            db.session.add_all([owner, resident_user])
            db.session.commit()

            resident = Resident(user_id=resident_user.id, flat_id=flat.id, building_id=building.id, resident_type='Flat Owner', approval_status='Approved', status='Active')
            db.session.add(resident)
            db.session.commit()

            event = Event(
                title='Rejoin Meetup',
                description='Second chance event',
                start_date=datetime.utcnow(),
                end_date=datetime.utcnow(),
                location='Clubhouse',
                created_by_id=owner.id,
                max_capacity=20,
                event_type='General',
                status='Active',
            )
            db.session.add(event)
            db.session.commit()

        login_response = client.post(
            '/auth/login',
            data={'identifier': 'resident-event-rejoin@example.com', 'password': 'residentpass123', 'role': 'resident'},
            follow_redirects=True,
        )
        assert login_response.status_code == 200

        first_response = client.post('/events/1/register', follow_redirects=True)
        assert first_response.status_code == 200
        assert 'Registration Successful' in first_response.get_data(as_text=True)

        with app.app_context():
            participant = Participant.query.filter_by(event_id=1, resident_id=1).first()
            participant.status = 'Cancelled'
            participant.cancel_reason = 'Changed plans'
            participant.cancelled_at = datetime.utcnow()
            db.session.commit()

        re_register_response = client.post('/events/1/register', follow_redirects=True)
        assert re_register_response.status_code == 200
        body = re_register_response.get_data(as_text=True)
        assert 'Registration Successful' in body

        with app.app_context():
            registrations = Participant.query.filter_by(event_id=1, resident_id=1).all()
            assert len(registrations) == 1
            assert registrations[0].status == 'Registered'
            assert registrations[0].cancel_reason is None
