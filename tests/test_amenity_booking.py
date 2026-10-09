from datetime import date, time, timedelta

from werkzeug.security import generate_password_hash

from app import create_app, db
from app.config import Config
from app.models import Amenity, AmenityBooking, Notification, Resident, Role, User


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False


def test_resident_requests_booking_and_admin_approves_it(monkeypatch):
    sent_emails = []
    monkeypatch.setattr(
        'app.routes.resident.email_user',
        lambda user, subject, body, html=None: sent_emails.append((user, subject, body)),
    )
    app = create_app(TestConfig)
    with app.test_client() as client:
        with app.app_context():
            resident_role = Role.query.filter_by(name='Resident').first()
            admin_role = Role.query.filter_by(name='Society Admin').first()
            resident_user = User(
                username='amenity-resident', email='amenity-resident@example.com',
                password_hash=generate_password_hash('password'), role_id=resident_role.id,
                first_name='Amenity', last_name='Resident', is_verified=True,
                is_approved=True, is_active=True,
            )
            admin_user = User(
                username='amenity-admin', email='amenity-admin@example.com',
                password_hash=generate_password_hash('password'), role_id=admin_role.id,
                first_name='Society', last_name='Admin', is_verified=True,
                is_approved=True, is_active=True,
            )
            db.session.add_all([resident_user, admin_user])
            db.session.commit()
            resident = Resident(
                user_id=resident_user.id, approval_status='Approved', status='Active',
            )
            amenity = Amenity(
                name='Community Hall', capacity=50, opening_time=time(8),
                closing_time=time(22), created_by_id=admin_user.id,
            )
            db.session.add_all([resident, amenity])
            db.session.commit()
            resident_user_id = resident_user.id
            amenity_id = amenity.id
            resident_id = resident.id
            booking_date = date.today() + timedelta(days=1)

        response = client.post('/auth/login', data={
            'identifier': 'amenity-resident@example.com',
            'password': 'password',
            'role': 'resident',
        }, follow_redirects=True)
        assert response.status_code == 200

        response = client.post('/resident/amenities', data={
            'amenity_id': amenity_id,
            'booking_date': booking_date.isoformat(),
            'start_time': '10:00',
            'end_time': '11:00',
            'purpose': 'Resident meeting',
        }, follow_redirects=True)
        assert response.status_code == 200
        assert len(sent_emails) == 1
        assert sent_emails[0][1] == 'Amenity booking request received'
        assert 'pending administrator approval' in sent_emails[0][2]
        assert 'Community Hall' in sent_emails[0][2]

        with app.app_context():
            booking = AmenityBooking.query.filter_by(resident_id=resident_id).one()
            assert booking.status == 'Pending'
            assert Notification.query.filter_by(user_id=resident_user_id).count() == 0
            assert Notification.query.filter(Notification.title == 'New amenity booking request').count() >= 1
            booking_id = booking.id

        response = client.post('/auth/admin/login', data={
            'identifier': 'amenity-admin@example.com',
            'password': 'password',
        }, follow_redirects=True)
        assert response.status_code == 200
        response = client.post(f'/admin/amenity-bookings/{booking_id}/status', data={'status': 'Approved'}, follow_redirects=True)
        assert response.status_code == 200

        with app.app_context():
            assert db.session.get(AmenityBooking, booking_id).status == 'Approved'
            resident_notifications = Notification.query.filter_by(user_id=resident_user_id).all()
            assert len(resident_notifications) == 1
            assert resident_notifications[0].title == 'Amenity booking approved'
