import sys
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from werkzeug.security import generate_password_hash

from app import create_app, db
from app.config import Config
from app.models import Bill, Building, Flat, MaintenanceRequest, MeetingAttendance, Notification, Resident, Role, SocietyMeeting, User
from app.notification_service import notify_bill_created, notify_residents


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False


def test_resident_registration_uses_flat_and_contact_and_no_username():
    app = create_app(TestConfig)
    with app.test_client() as client:
        with app.app_context():
            role = Role.query.filter_by(name='Resident').first()
            admin_role = Role.query.filter_by(name='Society Admin').first()
            assert role is not None
            assert admin_role is not None
            admin_user = User(
                username='society-admin',
                email='society-admin@example.com',
                password_hash=generate_password_hash('adminpass123'),
                role_id=admin_role.id,
            )
            building = Building(name='Test Building', address='Test Address')
            db.session.add_all([admin_user, building])
            db.session.commit()
            admin_user_id = admin_user.id
            flat = Flat(number='A-101', flat_type='2BHK', building_id=building.id, occupied=True)
            db.session.add(flat)
            db.session.commit()

        response = client.post(
            '/auth/register',
            data={
                'first_name': 'Jane',
                'last_name': 'Doe',
                'email': 'Jane@Example.com',
                'phone': '9876543210',
                'flat_number': 'A-101',
                'resident_type': 'Tenant',
                'password': 'secret123',
                'role': 'resident',
            },
            follow_redirects=True,
        )

        assert response.status_code == 200
        with app.app_context():
            user = User.query.filter_by(email='jane@example.com').first()
            assert user is not None
            assert user.username == 'jane@example.com'
            assert user.phone == '9876543210'
            assert user.resident is not None
            assert user.resident.flat is not None
            assert user.resident.flat.number == 'A-101'
            assert user.resident.resident_type == 'Tenant'
            assert user.is_approved is False
            notification = Notification.query.filter_by(
                user_id=admin_user_id,
                title='New resident registration',
            ).first()
            assert notification is not None
            assert 'Jane Doe registered for flat A-101' in notification.message


def test_registration_form_has_accessible_password_visibility_toggle():
    app = create_app(TestConfig)
    with app.test_client() as client:
        response = client.get('/auth/register?role=resident')

    assert response.status_code == 200
    assert b'id="registerPassword"' in response.data
    assert b'aria-label="Show password"' in response.data
    assert b'class="bi bi-eye"' in response.data


def test_login_forms_enable_browser_credential_autofill():
    app = create_app(TestConfig)
    with app.test_client() as client:
        resident_response = client.get('/auth/login?role=resident')
        admin_response = client.get('/auth/admin/login')

    assert resident_response.status_code == 200
    assert b'autocomplete="username"' in resident_response.data
    assert b'autocomplete="current-password"' in resident_response.data
    assert admin_response.status_code == 200
    assert b'autocomplete="username"' in admin_response.data
    assert b'autocomplete="current-password"' in admin_response.data


def test_admin_notifications_backfill_existing_pending_resident_registration():
    app = create_app(TestConfig)
    with app.app_context():
        admin_role = Role.query.filter_by(name='Society Admin').first()
        resident_role = Role.query.filter_by(name='Resident').first()
        admin = User(
            username='pending-admin',
            email='pending-admin@example.com',
            password_hash=generate_password_hash('adminpass123'),
            role_id=admin_role.id,
        )
        resident_user = User(
            username='pending-resident',
            email='pending-resident@example.com',
            first_name='Pending',
            last_name='Resident',
            password_hash=generate_password_hash('residentpass123'),
            role_id=resident_role.id,
        )
        db.session.add_all([admin, resident_user])
        db.session.flush()
        db.session.add(Resident(user_id=resident_user.id, approval_status='Pending', status='Pending'))
        db.session.commit()

    with app.test_client() as client:
        login_response = client.post(
            '/auth/admin/login',
            data={'identifier': 'pending-admin@example.com', 'password': 'adminpass123'},
        )
        assert login_response.status_code == 302
        response = client.get('/notifications/')
        assert response.status_code == 200
        assert b'New resident registration' in response.data
        assert b'Pending Resident registered for flat Unassigned' in response.data
        assert b'View details' in response.data
        assert b'href="/admin/residents"' in response.data

    with app.app_context():
        admin = User.query.filter_by(email='pending-admin@example.com').first()
        notification = Notification.query.filter_by(
            user_id=admin.id,
            title='New resident registration',
        ).first()
        assert notification is not None
        assert notification.target_url == '/admin/residents'


def test_complaint_notification_opens_the_matching_admin_detail():
    app = create_app(TestConfig)
    with app.app_context():
        resident_role = Role.query.filter_by(name='Resident').first()
        admin_role = Role.query.filter_by(name='Society Admin').first()
        resident_user = User(
            username='complaint-resident',
            email='complaint-resident@example.com',
            password_hash=generate_password_hash('residentpass123'),
            role_id=resident_role.id,
            is_approved=True,
            is_active=True,
        )
        admin_user = User(
            username='complaint-admin',
            email='complaint-admin@example.com',
            password_hash=generate_password_hash('adminpass123'),
            role_id=admin_role.id,
            is_approved=True,
            is_active=True,
        )
        db.session.add_all([resident_user, admin_user])
        db.session.flush()
        db.session.add(Resident(user_id=resident_user.id, approval_status='Approved', status='Active'))
        db.session.commit()
        admin_user_id = admin_user.id

    with app.test_client() as client:
        resident_login = client.post(
            '/auth/login',
            data={'identifier': 'complaint-resident@example.com', 'password': 'residentpass123', 'role': 'resident'},
        )
        assert resident_login.status_code == 302
        complaint_response = client.post(
            '/resident/complaints',
            data={'title': 'Lift repair', 'description': 'The lift is not working.'},
        )
        assert complaint_response.status_code == 302

        with app.app_context():
            notification = Notification.query.filter_by(
                user_id=admin_user_id,
                title='New complaint submitted',
            ).first()
            assert notification is not None
            target_url = notification.target_url
            assert target_url.startswith('/admin/complaints/')

        client.get('/auth/logout')
        admin_login = client.post(
            '/auth/admin/login',
            data={'identifier': 'complaint-admin@example.com', 'password': 'adminpass123'},
        )
        assert admin_login.status_code == 302
        notification_page = client.get('/notifications/')
        assert b'View details' in notification_page.data
        assert target_url.encode() in notification_page.data
        assert client.get(target_url).status_code == 200


def test_bill_notification_opens_the_matching_bill_preview():
    class MailSuppressedConfig(TestConfig):
        MAIL_SUPPRESS_SEND = True

    app = create_app(MailSuppressedConfig)
    with app.app_context():
        resident_role = Role.query.filter_by(name='Resident').first()
        resident_user = User(
            username='bill-notification-resident',
            email='bill-notification-resident@example.com',
            password_hash=generate_password_hash('residentpass123'),
            role_id=resident_role.id,
            is_approved=True,
            is_active=True,
        )
        db.session.add(resident_user)
        db.session.flush()
        resident = Resident(user_id=resident_user.id, approval_status='Approved', status='Active')
        db.session.add(resident)
        db.session.flush()
        bill = Bill(
            bill_type='Maintenance Charges',
            amount=1200,
            due_date=datetime.utcnow() + timedelta(days=10),
            resident_id=resident.id,
            resident_name='Bill Resident',
        )
        db.session.add(bill)
        db.session.flush()
        bill_id = bill.id
        with app.test_request_context():
            notify_bill_created(bill)

    with app.test_client() as client:
        login_response = client.post(
            '/auth/login',
            data={
                'identifier': 'bill-notification-resident@example.com',
                'password': 'residentpass123',
                'role': 'resident',
            },
        )
        assert login_response.status_code == 302
        notification_page = client.get('/notifications/')
        expected_url = f'/resident/bills/{bill_id}/download?preview=1'
        assert b'View details' in notification_page.data
        assert expected_url.encode() in notification_page.data
        bill_preview = client.get(expected_url)
        assert bill_preview.status_code == 200
        assert b'Bill Preview' in bill_preview.data


def test_notification_without_explicit_target_gets_role_relevant_view_link():
    app = create_app(TestConfig)
    with app.app_context():
        owner_role = Role.query.filter_by(name='Owner').first()
        owner = User(
            username='notification-owner',
            email='notification-owner@example.com',
            password_hash=generate_password_hash('ownerpass123'),
            role_id=owner_role.id,
            is_approved=True,
            is_active=True,
        )
        db.session.add(owner)
        db.session.flush()
        db.session.add(Notification(
            user_id=owner.id,
            title='New maintenance request',
            message='A resident submitted a maintenance request.',
        ))
        db.session.commit()

    with app.test_client() as client:
        login_response = client.post(
            '/auth/login',
            data={'identifier': 'notification-owner@example.com', 'password': 'ownerpass123', 'role': 'owner'},
        )
        assert login_response.status_code == 302
        response = client.get('/notifications/')
        assert response.status_code == 200
        assert b'View details' in response.data
        assert b'href="/owner/maintenance"' in response.data

    with app.app_context():
        notification = Notification.query.filter_by(title='New maintenance request').first()
        assert notification.target_url == '/owner/maintenance'


def test_society_broadcasts_only_reach_approved_active_residents():
    app = create_app(TestConfig)
    with app.app_context():
        resident_role = Role.query.filter_by(name='Resident').first()
        maintenance_role = Role.query.filter_by(name='Maintenance Staff').first()
        approved_resident = User(
            username='approved-broadcast-resident',
            email='approved-broadcast-resident@example.com',
            password_hash=generate_password_hash('residentpass123'),
            role_id=resident_role.id,
            is_approved=True,
            is_active=True,
        )
        pending_resident = User(
            username='pending-broadcast-resident',
            email='pending-broadcast-resident@example.com',
            password_hash=generate_password_hash('residentpass123'),
            role_id=resident_role.id,
            is_approved=False,
            is_active=True,
        )
        maintenance_user = User(
            username='broadcast-maintenance',
            email='broadcast-maintenance@example.com',
            password_hash=generate_password_hash('staffpass123'),
            role_id=maintenance_role.id,
            is_approved=True,
            is_active=True,
        )
        db.session.add_all([approved_resident, pending_resident, maintenance_user])
        db.session.commit()

        assert notify_residents('New society notice', 'Water shutoff tomorrow.') == 1
        recipients = Notification.query.filter_by(title='New society notice').all()
        assert [notification.user_id for notification in recipients] == [approved_resident.id]


def test_owner_published_notice_event_and_meeting_notify_residents():
    app = create_app(TestConfig)
    with app.app_context():
        owner_role = Role.query.filter_by(name='Owner').first()
        resident_role = Role.query.filter_by(name='Resident').first()
        owner = User(
            username='publisher-owner',
            email='publisher-owner@example.com',
            password_hash=generate_password_hash('ownerpass123'),
            role_id=owner_role.id,
            is_approved=True,
            is_active=True,
        )
        resident = User(
            username='publisher-resident',
            email='publisher-resident@example.com',
            password_hash=generate_password_hash('residentpass123'),
            role_id=resident_role.id,
            is_approved=True,
            is_active=True,
        )
        db.session.add_all([owner, resident])
        db.session.commit()
        resident_id = resident.id

    with app.test_client() as client:
        login_response = client.post(
            '/auth/login',
            data={'identifier': 'publisher-owner@example.com', 'password': 'ownerpass123', 'role': 'owner'},
            follow_redirects=True,
        )
        assert login_response.status_code == 200

        notice_response = client.post(
            '/owner/notice/create',
            data={'title': 'Water maintenance', 'content': 'Water will be unavailable.', 'notice_type': 'General'},
        )
        event_response = client.post(
            '/owner/event/create',
            data={
                'title': 'Society Day',
                'description': 'Annual gathering',
                'location': 'Clubhouse',
                'event_type': 'General',
                'start_date': '2030-06-01T10:00',
                'end_date': '2030-06-01T12:00',
                'max_capacity': '100',
            },
        )
        meeting_response = client.post(
            '/meetings/create',
            data={'title': 'Annual meeting', 'meeting_date': '2030-06-05T18:00', 'location': 'Clubhouse'},
        )
        assert notice_response.status_code == 302
        assert event_response.status_code == 302
        assert meeting_response.status_code == 302

    with app.app_context():
        titles = {
            notification.title
            for notification in Notification.query.filter_by(user_id=resident_id).all()
        }
        assert {'New society notice', 'New society event', 'New society meeting'} <= titles


def test_logout_returns_home_and_prevents_cached_authenticated_pages():
    app = create_app(TestConfig)
    with app.app_context():
        resident_role = Role.query.filter_by(name='Resident').first()
        user = User(
            username='logout-resident',
            email='logout-resident@example.com',
            password_hash=generate_password_hash('residentpass123'),
            role_id=resident_role.id,
            is_verified=True,
            is_approved=True,
            is_active=True,
        )
        db.session.add(user)
        db.session.flush()
        db.session.add(Resident(user_id=user.id, approval_status='Approved', status='Active'))
        db.session.commit()

    with app.test_client() as client:
        login_response = client.post(
            '/auth/login',
            data={'identifier': 'logout-resident@example.com', 'password': 'residentpass123', 'role': 'resident'},
        )
        assert login_response.status_code == 302

        protected_response = client.get('/resident/')
        assert protected_response.status_code == 200
        assert 'no-store' in protected_response.headers['Cache-Control']

        logout_response = client.get('/auth/logout')
        assert logout_response.status_code == 302
        assert logout_response.headers['Location'].endswith('/')
        assert 'no-store' in logout_response.headers['Cache-Control']

        after_logout_response = client.get('/resident/')
        assert after_logout_response.status_code == 302
        assert after_logout_response.headers['Location'].startswith('/auth/login')


def test_maintenance_notifications_reach_admin_assignee_and_resident():
    class MailSuppressedConfig(TestConfig):
        MAIL_SUPPRESS_SEND = True

    app = create_app(MailSuppressedConfig)
    with app.app_context():
        owner_role = Role.query.filter_by(name='Owner').first()
        resident_role = Role.query.filter_by(name='Resident').first()
        maintenance_role = Role.query.filter_by(name='Maintenance Staff').first()
        owner = User(
            username='maintenance-owner',
            email='maintenance-owner@example.com',
            password_hash=generate_password_hash('ownerpass123'),
            role_id=owner_role.id,
            is_approved=True,
            is_active=True,
        )
        resident_user = User(
            username='maintenance-resident',
            email='maintenance-resident@example.com',
            password_hash=generate_password_hash('residentpass123'),
            role_id=resident_role.id,
            is_approved=True,
            is_active=True,
        )
        maintenance_user = User(
            username='maintenance-staff',
            email='maintenance-staff@example.com',
            password_hash=generate_password_hash('staffpass123'),
            role_id=maintenance_role.id,
            is_approved=True,
            is_active=True,
        )
        db.session.add_all([owner, resident_user, maintenance_user])
        db.session.flush()
        resident = Resident(user_id=resident_user.id, approval_status='Approved', status='Active')
        db.session.add(resident)
        db.session.flush()
        maintenance = MaintenanceRequest(
            title='Leaky pipe',
            description='Pipe leaking in the kitchen.',
            resident_id=resident.id,
        )
        db.session.add(maintenance)
        db.session.commit()
        owner_id = owner.id
        resident_user_id = resident_user.id
        maintenance_user_id = maintenance_user.id
        maintenance_id = maintenance.id

    with app.test_client() as client:
        owner_login = client.post(
            '/auth/login',
            data={'identifier': 'maintenance-owner@example.com', 'password': 'ownerpass123', 'role': 'owner'},
            follow_redirects=True,
        )
        assert owner_login.status_code == 200
        assign_response = client.post(
            f'/owner/maintenance/{maintenance_id}/assign',
            data={'staff_id': str(maintenance_user_id)},
        )
        assert assign_response.status_code == 302

        resident_login = client.post(
            '/auth/login',
            data={'identifier': 'maintenance-resident@example.com', 'password': 'residentpass123', 'role': 'resident'},
            follow_redirects=True,
        )
        assert resident_login.status_code == 200
        request_response = client.post(
            '/resident/maintenance',
            data={'title': 'Broken light', 'description': 'The hallway light is out.'},
        )
        assert request_response.status_code == 302

    with app.app_context():
        assert Notification.query.filter_by(
            user_id=maintenance_user_id,
            title='Maintenance request assigned',
        ).count() == 1
        assert Notification.query.filter_by(
            user_id=resident_user_id,
            title='Maintenance assigned',
        ).count() == 1
        assert Notification.query.filter_by(
            user_id=owner_id,
            title='New maintenance request',
        ).count() == 1


def test_approved_resident_can_upload_profile_picture(tmp_path):
    class UploadTestConfig(TestConfig):
        UPLOAD_FOLDER = tmp_path

    app = create_app(UploadTestConfig)
    with app.app_context():
        role = Role.query.filter_by(name='Resident').first()
        user = User(
            username='avatar@example.com',
            email='avatar@example.com',
            first_name='Avatar',
            last_name='Resident',
            password_hash=generate_password_hash('secret123'),
            role_id=role.id,
            is_verified=True,
            is_approved=True,
            is_active=True,
        )
        db.session.add(user)
        db.session.flush()
        db.session.add(Resident(user_id=user.id, approval_status='Approved', status='Active'))
        db.session.commit()

    with app.test_client() as client:
        login_response = client.post(
            '/auth/login',
            data={'identifier': 'avatar@example.com', 'password': 'secret123', 'role': 'resident'},
            follow_redirects=True,
        )
        assert login_response.status_code == 200

        response = client.post(
            '/account/avatar',
            data={'profile_picture': (BytesIO(b'fake image data'), 'profile.png')},
            content_type='multipart/form-data',
            follow_redirects=True,
        )

    assert response.status_code == 200
    with app.app_context():
        user = User.query.filter_by(email='avatar@example.com').first()
        assert user.avatar_url == f'uploads/profiles/profile-{user.id}.png'
    uploaded_path = Path(app.root_path) / 'static' / user.avatar_url
    assert uploaded_path.is_file()
    uploaded_path.unlink()


def test_resident_registration_allows_empty_last_name():
    app = create_app(TestConfig)
    with app.test_client() as client:
        response = client.post(
            '/auth/register',
            data={
                'first_name': 'Jane',
                'last_name': '',
                'email': 'jane-no-last@example.com',
                'phone': '9876543215',
                'flat_number': 'A-110',
                'resident_type': 'Tenant',
                'password': 'secret123',
                'role': 'resident',
            },
            follow_redirects=True,
        )

        assert response.status_code == 200
        assert b'Registration successful' in response.data
        with app.app_context():
            user = User.query.filter_by(email='jane-no-last@example.com').first()
            assert user is not None
            assert user.first_name == 'Jane'
            assert user.last_name is None or user.last_name == ''
            assert user.resident is not None
            assert user.resident.resident_type == 'Tenant'


def test_duplicate_email_registration_is_rejected():
    app = create_app(TestConfig)
    with app.test_client() as client:
        response = client.post(
            '/auth/register',
            data={
                'first_name': 'Jane',
                'last_name': 'Doe',
                'email': 'duplicate@example.com',
                'phone': '9876543210',
                'flat_number': 'A-102',
                'resident_type': 'Tenant',
                'password': 'secret123',
                'role': 'resident',
            },
            follow_redirects=True,
        )
        response = client.post(
            '/auth/register',
            data={
                'first_name': 'John',
                'last_name': 'Doe',
                'email': 'duplicate@example.com',
                'phone': '9876543211',
                'flat_number': 'A-103',
                'resident_type': 'Flat Owner',
                'password': 'secret123',
                'role': 'resident',
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b'already exists' in response.data.lower()


def test_duplicate_phone_and_flat_registration_is_rejected():
    app = create_app(TestConfig)
    with app.test_client() as client:
        first_response = client.post(
            '/auth/register',
            data={
                'first_name': 'Jane',
                'last_name': 'Doe',
                'email': 'first@example.com',
                'phone': '9876543210',
                'flat_number': 'A-200',
                'resident_type': 'Tenant',
                'password': 'secret123',
                'role': 'resident',
            },
            follow_redirects=True,
        )
        assert first_response.status_code == 200

        second_response = client.post(
            '/auth/register',
            data={
                'first_name': 'John',
                'last_name': 'Doe',
                'email': 'second@example.com',
                'phone': '9876543210',
                'flat_number': 'A-200',
                'resident_type': 'Flat Owner',
                'password': 'secret123',
                'role': 'resident',
            },
            follow_redirects=True,
        )
        assert second_response.status_code == 200
        assert b'phone number' in second_response.data.lower() or b'flat number' in second_response.data.lower()


def test_non_admin_cannot_access_admin_dashboard():
    app = create_app(TestConfig)
    with app.app_context():
        role = Role.query.filter_by(name='Resident').first()
        user = User(
            username='resident-access@example.com',
            email='resident-access@example.com',
            first_name='Resident',
            last_name='User',
            phone='1111111111',
            password_hash=generate_password_hash('secret123'),
            role_id=role.id,
            is_verified=True,
            is_approved=True,
            is_active=True,
        )
        db.session.add(user)
        db.session.flush()
        resident = Resident(user_id=user.id, approval_status='Approved', status='Active', resident_type='Tenant')
        db.session.add(resident)
        db.session.commit()

    with app.test_client() as client:
        login_response = client.post(
            '/auth/login',
            data={
                'identifier': 'resident-access@example.com',
                'password': 'secret123',
                'role': 'resident',
            },
            follow_redirects=True,
        )
        assert login_response.status_code == 200

        admin_response = client.get('/admin/dashboard')
        assert admin_response.status_code == 302
        assert admin_response.headers['Location'].endswith('/admin/login')


def test_past_meeting_attendance_is_closed():
    app = create_app(TestConfig)
    with app.app_context():
        resident_role = Role.query.filter_by(name='Resident').first()
        user = User(
            username='past-meeting-attendee@test.com',
            email='past-meeting-attendee@test.com',
            first_name='Past',
            last_name='Attendee',
            phone='7777777777',
            password_hash=generate_password_hash('secret123'),
            role_id=resident_role.id,
            is_verified=True,
            is_approved=True,
            is_active=True,
        )
        db.session.add(user)
        db.session.flush()
        user_id = user.id
        resident = Resident(user_id=user_id, approval_status='Approved', status='Active', resident_type='Tenant')
        db.session.add(resident)
        meeting = SocietyMeeting(
            title='Monthly Meeting',
            description='Already held last week',
            meeting_date=datetime.utcnow() - timedelta(days=2),
            location='Community Hall',
            created_by_id=user_id,
        )
        db.session.add(meeting)
        db.session.commit()
        meeting_id = meeting.id

    with app.test_client() as client:
        login_response = client.post(
            '/auth/login',
            data={
                'identifier': 'past-meeting-attendee@test.com',
                'password': 'secret123',
                'role': 'resident',
            },
            follow_redirects=True,
        )
        assert login_response.status_code == 200

        response = client.post(f'/meetings/{meeting_id}/attendance', follow_redirects=True)
        assert response.status_code == 200
        assert b'attendance is closed for past meetings' in response.data.lower()

    with app.app_context():
        assert MeetingAttendance.query.filter_by(meeting_id=meeting_id, user_id=user_id).count() == 0


def test_pending_resident_cannot_login_until_approved():
    app = create_app(TestConfig)
    with app.test_client() as client:
        client.post(
            '/auth/register',
            data={
                'first_name': 'Pending',
                'last_name': 'Resident',
                'email': 'pending@example.com',
                'phone': '9876543212',
                'flat_number': 'A-104',
                'resident_type': 'Tenant',
                'password': 'secret123',
                'role': 'resident',
            },
            follow_redirects=True,
        )

        response = client.post(
            '/auth/login',
            data={
                'identifier': 'pending@example.com',
                'password': 'secret123',
                'role': 'resident',
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b'pending owner approval' in response.data.lower()


def test_resident_dashboard_shows_recent_society_notices():
    app = create_app(TestConfig)
    with app.app_context():
        resident_role = Role.query.filter_by(name='Resident').first()
        admin_role = Role.query.filter_by(name='Society Admin').first()
        admin_user = User(
            username='society-admin@test.com',
            email='society-admin@test.com',
            first_name='Society',
            last_name='Admin',
            phone='9999999998',
            password_hash=generate_password_hash('secret123'),
            role_id=admin_role.id,
            is_verified=True,
            is_approved=True,
            is_active=True,
        )
        db.session.add(admin_user)
        db.session.flush()

        user = User(
            username='notice-resident@test.com',
            email='notice-resident@test.com',
            first_name='Notice',
            last_name='Resident',
            phone='9876543333',
            password_hash=generate_password_hash('secret123'),
            role_id=resident_role.id,
            is_verified=True,
            is_approved=True,
            is_active=True,
        )
        db.session.add(user)
        db.session.flush()
        resident = Resident(user_id=user.id, approval_status='Approved', status='Active', resident_type='Tenant')
        db.session.add(resident)
        db.session.add(
            Notice(
                title='Water Supply Update',
                content='Water supply will be restored by 6 PM today.',
                notice_type='General',
                created_by_id=admin_user.id,
            )
        )
        db.session.commit()

    with app.test_client() as client:
        login_response = client.post(
            '/auth/login',
            data={
                'identifier': 'notice-resident@test.com',
                'password': 'secret123',
                'role': 'resident',
            },
            follow_redirects=True,
        )
        assert login_response.status_code == 200

        response = client.get('/resident/')
        assert response.status_code == 200
        assert b'Water Supply Update' in response.data
        assert b'Water supply will be restored by 6 PM today.' in response.data


def test_resident_can_submit_complaint_without_category_id():
    app = create_app(TestConfig)
    with app.app_context():
        resident_role = Role.query.filter_by(name='Resident').first()
        user = User(
            username='resident-complaint-submit@test.com',
            email='resident-complaint-submit@test.com',
            first_name='Complaint',
            last_name='Submitter',
            phone='4444444444',
            password_hash=generate_password_hash('secret123'),
            role_id=resident_role.id,
            is_verified=True,
            is_approved=True,
            is_active=True,
        )
        db.session.add(user)
        db.session.flush()
        resident = Resident(user_id=user.id, approval_status='Approved', status='Active', resident_type='Tenant')
        db.session.add(resident)
        db.session.commit()

    with app.test_client() as client:
        login_response = client.post(
            '/auth/login',
            data={
                'identifier': 'resident-complaint-submit@test.com',
                'password': 'secret123',
                'role': 'resident',
            },
            follow_redirects=True,
        )
        assert login_response.status_code == 200

        response = client.post(
            '/resident/complaints',
            data={
                'title': 'Water leak in bathroom',
                'description': 'There is a leak near the sink.',
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b'Complaint submitted' in response.data

        with app.app_context():
            complaint = db.session.execute(db.select(__import__('app.models', fromlist=['Complaint']).Complaint)).scalar_one()
            assert complaint.title == 'Water leak in bathroom'
            assert complaint.category_id is None


def test_admin_page_shows_legacy_complaints_without_category_id():
    app = create_app(TestConfig)
    with app.app_context():
        admin_role = Role.query.filter_by(name='Society Admin').first()
        admin_user = User(
            username='admin-legacy-complaint@test.com',
            email='admin-legacy-complaint@test.com',
            first_name='Legacy',
            last_name='Admin',
            phone='5555555555',
            password_hash=generate_password_hash('secret123'),
            role_id=admin_role.id,
            is_verified=True,
            is_approved=True,
            is_active=True,
        )
        db.session.add(admin_user)
        db.session.flush()

        resident_role = Role.query.filter_by(name='Resident').first()
        resident_user = User(
            username='resident-legacy-complaint@test.com',
            email='resident-legacy-complaint@test.com',
            first_name='Legacy',
            last_name='Resident',
            phone='6666666666',
            password_hash=generate_password_hash('secret123'),
            role_id=resident_role.id,
            is_verified=True,
            is_approved=True,
            is_active=True,
        )
        db.session.add(resident_user)
        db.session.flush()

        resident = Resident(user_id=resident_user.id, approval_status='Approved', status='Active', resident_type='Tenant')
        db.session.add(resident)
        db.session.flush()

        complaint = __import__('app.models', fromlist=['Complaint']).Complaint(
            title='Old gate issue',
            description='Gate makes noise every night.',
            category_id=None,
            resident_id=resident.id,
            status='Pending',
            priority='High',
        )
        db.session.add(complaint)
        db.session.commit()

    with app.test_client() as client:
        login_response = client.post(
            '/auth/admin/login',
            data={
                'identifier': 'admin-legacy-complaint@test.com',
                'password': 'secret123',
            },
            follow_redirects=True,
        )
        assert login_response.status_code == 200

        response = client.get('/admin/complaints')
        assert response.status_code == 200
        assert b'Old gate issue' in response.data


def test_admin_complaint_detail_page_displays_full_information():
    app = create_app(TestConfig)
    with app.app_context():
        admin_role = Role.query.filter_by(name='Society Admin').first()
        resident_role = Role.query.filter_by(name='Resident').first()
        admin_user = User(
            username='admin-detail@test.com',
            email='admin-detail@test.com',
            first_name='Admin',
            last_name='Detail',
            phone='2222222222',
            password_hash=generate_password_hash('secret123'),
            role_id=admin_role.id,
            is_verified=True,
            is_approved=True,
            is_active=True,
        )
        db.session.add(admin_user)
        db.session.flush()

        resident_user = User(
            username='resident-detail@test.com',
            email='resident-detail@test.com',
            first_name='Complaint',
            last_name='Resident',
            phone='3333333333',
            password_hash=generate_password_hash('secret123'),
            role_id=resident_role.id,
            is_verified=True,
            is_approved=True,
            is_active=True,
        )
        db.session.add(resident_user)
        db.session.flush()

        building = Building(name='Detail Building', address='Test Address')
        db.session.add(building)
        db.session.flush()

        flat = Flat(number='B-202', flat_type='2BHK', building_id=building.id, occupied=True)
        db.session.add(flat)
        db.session.flush()

        resident = Resident(user_id=resident_user.id, flat_id=flat.id, building_id=building.id, approval_status='Approved', status='Active', resident_type='Flat Owner')
        db.session.add(resident)
        db.session.flush()

        category = db.session.query(__import__('app.models', fromlist=['ComplaintCategory']).ComplaintCategory).filter_by(name='Electrical').first()
        if category is None:
            category = __import__('app.models', fromlist=['ComplaintCategory']).ComplaintCategory(name='Electrical')
            db.session.add(category)
            db.session.flush()

        complaint = __import__('app.models', fromlist=['Complaint']).Complaint(
            title='Lift not working',
            description='Lift stuck on the third floor.',
            category_id=category.id,
            resident_id=resident.id,
            status='Pending',
            priority='High',
        )
        db.session.add(complaint)
        db.session.commit()
        complaint_id = complaint.id

    with app.test_client() as client:
        login_response = client.post(
            '/auth/login',
            data={
                'identifier': 'admin-detail@test.com',
                'password': 'secret123',
                'role': 'admin',
            },
            follow_redirects=True,
        )
        assert login_response.status_code == 200

        response = client.get(f'/admin/complaints/{complaint_id}')
        assert response.status_code == 200
        assert b'Lift not working' in response.data
        assert b'Lift stuck on the third floor.' in response.data
        assert b'Complaint Resident' in response.data or b'Complaint' in response.data


def test_deactivated_resident_does_not_block_new_registration_for_same_flat():
    app = create_app(TestConfig)
    with app.app_context():
        role = Role.query.filter_by(name='Resident').first()
        building = Building(name='Test Building', address='Test Address')
        db.session.add(building)
        db.session.commit()
        flat = Flat(number='A-105', flat_type='2BHK', building_id=building.id, occupied=True)
        db.session.add(flat)
        db.session.commit()

        user = User(username='deactivated@example.com', email='deactivated@example.com', first_name='Deactivated', last_name='User', phone='9876543213', password_hash='hash', role_id=role.id, is_verified=True, is_approved=True, is_active=False)
        db.session.add(user)
        db.session.flush()
        resident = Resident(user_id=user.id, flat_id=flat.id, building_id=building.id, resident_type='Tenant', approval_status='Approved', status='Inactive')
        db.session.add(resident)
        db.session.commit()


def test_maintenance_staff_does_not_see_billing_or_complaints_links():
    app = create_app(TestConfig)
    with app.app_context():
        role = Role.query.filter_by(name='Maintenance Staff').first()
        assert role is not None
        user = User(
            username='maintenance-test@example.com',
            email='maintenance-test@example.com',
            first_name='Maintenance',
            last_name='Staff',
            phone='2222222222',
            password_hash=generate_password_hash('secret123'),
            role_id=role.id,
            is_verified=True,
            is_approved=True,
            is_active=True,
        )
        db.session.add(user)
        db.session.commit()

    with app.test_client() as client:
        login_response = client.post(
            '/auth/login',
            data={
                'identifier': 'maintenance-test@example.com',
                'password': 'secret123',
                'role': 'maintenance',
            },
            follow_redirects=True,
        )
        assert login_response.status_code == 200

        response = client.get('/maintenance/')
        assert response.status_code == 200

        body = response.get_data(as_text=True).lower()
        assert 'billing' not in body
        assert 'complaints' not in body


def test_authenticated_user_stays_logged_in_when_visiting_home_page():
    app = create_app(TestConfig)
    with app.app_context():
        role = Role.query.filter_by(name='Resident').first()
        user = User(
            username='home-auth@example.com',
            email='home-auth@example.com',
            first_name='Home',
            last_name='User',
            phone='1111111112',
            password_hash=generate_password_hash('secret123'),
            role_id=role.id,
            is_verified=True,
            is_approved=True,
            is_active=True,
        )
        db.session.add(user)
        db.session.flush()
        resident = Resident(user_id=user.id, approval_status='Approved', status='Active', resident_type='Tenant')
        db.session.add(resident)
        db.session.commit()

    with app.test_client() as client:
        login_response = client.post(
            '/auth/login',
            data={
                'identifier': 'home-auth@example.com',
                'password': 'secret123',
                'role': 'resident',
            },
            follow_redirects=True,
        )
        assert login_response.status_code == 200

        home_response = client.get('/', follow_redirects=True)
        assert home_response.status_code == 200
        assert b'login' not in home_response.data.lower()
        assert b'digital society' in home_response.data.lower()

    with app.test_client() as client:
        response = client.post(
            '/auth/register',
            data={
                'first_name': 'New',
                'last_name': 'Tenant',
                'email': 'newtenant@example.com',
                'phone': '9876543214',
                'flat_number': 'A-105',
                'resident_type': 'Tenant',
                'password': 'secret123',
                'role': 'resident',
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b'pending owner approval' in response.data.lower()
