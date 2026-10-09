import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app, db
from app.config import Config
from app.models import Building, Flat, Resident, Role, User, Bill, Payment
from werkzeug.security import generate_password_hash


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False


def test_resident_can_see_all_assigned_bills_regardless_of_bill_type():
    app = create_app(TestConfig)
    with app.test_client() as client:
        with app.app_context():
            resident_role = Role.query.filter_by(name='Resident').first()
            owner_role = Role.query.filter_by(name='Owner').first()
            owner = User(
                username='owner-billing',
                email='owner-billing@example.com',
                password_hash=generate_password_hash('ownerpass123'),
                first_name='Owner',
                last_name='Billing',
                role_id=owner_role.id,
                is_verified=True,
                is_approved=True,
                is_active=True,
            )
            db.session.add(owner)
            db.session.commit()

            building = Building(name='Billing Building', address='Test Address')
            db.session.add(building)
            db.session.commit()

            flat = Flat(number='B-301', flat_type='2BHK', building_id=building.id, occupied=True)
            db.session.add(flat)
            db.session.commit()

            resident_user = User(
                username='resident-billing',
                email='resident-billing@example.com',
                password_hash=generate_password_hash('residentpass123'),
                first_name='Bill',
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
                resident_type='Flat Owner',
                approval_status='Approved',
                status='Active',
            )
            db.session.add(resident)
            db.session.commit()

            db.session.add_all([
                Bill(
                    bill_type='Maintenance Charges',
                    description='Maintenance bill',
                    amount=150.0,
                    due_date=datetime(2026, 8, 1),
                    status='Pending',
                    resident_id=resident.id,
                    flat_id=flat.id,
                ),
                Bill(
                    bill_type='Monthly Rent',
                    description='Rent bill',
                    amount=300.0,
                    due_date=datetime(2026, 8, 1),
                    status='Pending',
                    resident_id=resident.id,
                    flat_id=flat.id,
                ),
            ])
            db.session.commit()

        login_response = client.post(
            '/auth/login',
            data={'identifier': 'resident-billing@example.com', 'password': 'residentpass123', 'role': 'resident'},
            follow_redirects=True,
        )
        assert login_response.status_code == 200

        response = client.get('/resident/bills', follow_redirects=True)
        assert response.status_code == 200
        body = response.get_data(as_text=True)
        assert 'Maintenance Charges' in body
        assert 'Monthly Rent' in body


def test_owner_can_save_custom_bill_type_and_amount():
    app = create_app(TestConfig)
    with app.test_client() as client:
        with app.app_context():
            resident_role = Role.query.filter_by(name='Resident').first()
            owner_role = Role.query.filter_by(name='Owner').first()
            owner = User(
                username='owner-bill-entry',
                email='owner-bill-entry@example.com',
                password_hash=generate_password_hash('ownerpass123'),
                first_name='Owner',
                last_name='BillEntry',
                role_id=owner_role.id,
                is_verified=True,
                is_approved=True,
                is_active=True,
            )
            db.session.add(owner)
            db.session.commit()

            building = Building(name='Entry Building', address='Entry Address')
            db.session.add(building)
            db.session.commit()

            flat = Flat(number='E-101', flat_type='2BHK', building_id=building.id, occupied=True)
            db.session.add(flat)
            db.session.commit()

            resident_user = User(
                username='resident-bill-entry',
                email='resident-bill-entry@example.com',
                password_hash=generate_password_hash('residentpass123'),
                first_name='Bill',
                last_name='Entry',
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
                resident_type='Flat Owner',
                approval_status='Approved',
                status='Active',
            )
            db.session.add(resident)
            db.session.commit()
            resident_id = resident.id

        login_response = client.post(
            '/auth/login',
            data={'identifier': 'owner-bill-entry@example.com', 'password': 'ownerpass123', 'role': 'owner'},
            follow_redirects=True,
        )
        assert login_response.status_code == 200

        response = client.post(
            f'/owner/resident/{resident_id}/billing',
            data={
                'bill_type': 'Monthly Rent',
                'amount': '20000',
                'due_date': '2026-09-10',
                'payment_status': 'Pending',
                'description': 'Custom rent entry',
            },
            follow_redirects=True,
        )
        assert response.status_code == 200

        with app.app_context():
            bill = Bill.query.filter_by(resident_id=resident_id).order_by(Bill.id.desc()).first()
            assert bill is not None
            assert bill.bill_type == 'Monthly Rent'
            assert bill.amount == 20000.0


def test_resident_can_select_payment_method_before_paying_bill():
    app = create_app(TestConfig)
    with app.test_client() as client:
        with app.app_context():
            resident_role = Role.query.filter_by(name='Resident').first()
            user = User(
                username='resident-payment-method',
                email='resident-payment-method@example.com',
                password_hash=generate_password_hash('residentpass123'),
                first_name='Resident',
                last_name='Pay',
                role_id=resident_role.id,
                is_verified=True,
                is_approved=True,
                is_active=True,
            )
            db.session.add(user)
            db.session.commit()

            building = Building(name='Payment Building', address='Payment Address')
            db.session.add(building)
            db.session.commit()

            flat = Flat(number='P-101', flat_type='2BHK', building_id=building.id, occupied=True)
            db.session.add(flat)
            db.session.commit()

            resident = Resident(
                user_id=user.id,
                flat_id=flat.id,
                building_id=building.id,
                resident_type='Tenant',
                approval_status='Approved',
                status='Active',
            )
            db.session.add(resident)
            db.session.commit()

            bill = Bill(
                bill_type='Monthly Rent',
                description='Monthly rent',
                amount=2000.0,
                due_date=datetime(2026, 9, 4),
                status='Pending',
                resident_id=resident.id,
                flat_id=flat.id,
                payment_status='Pending',
            )
            db.session.add(bill)
            db.session.commit()
            bill_id = bill.id

        login_response = client.post(
            '/auth/login',
            data={'identifier': 'resident-payment-method@example.com', 'password': 'residentpass123', 'role': 'resident'},
            follow_redirects=True,
        )
        assert login_response.status_code == 200

        response = client.post(
            f'/billing/pay/{bill_id}',
            data={'payment_method': 'PhonePe'},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b'Payment simulated successfully.' in response.data

        with app.app_context():
            payment = Payment.query.filter_by(bill_id=bill_id).order_by(Payment.id.desc()).first()
            assert payment is not None
            assert payment.payment_method == 'PhonePe'
            bill = Bill.query.get(bill_id)
            assert bill.payment_status == 'Paid'


def test_razorpay_emails_receipt_and_bill_only_after_payment_verification(monkeypatch):
    sent_emails = []
    admin_emails = []
    monkeypatch.setattr(
        'app.routes.billing.email_user',
        lambda user, subject, body, html=None: sent_emails.append((user, subject, body)),
    )
    monkeypatch.setattr(
        'app.routes.billing.email_admins',
        lambda subject, body, html=None: admin_emails.append((subject, body)),
    )
    fake_razorpay_client = SimpleNamespace(
        order=SimpleNamespace(create=lambda data: {'id': 'order_test_123'}),
        utility=SimpleNamespace(verify_payment_signature=lambda data: None),
    )
    monkeypatch.setattr(
        'app.routes.billing.get_razorpay_client',
        lambda: fake_razorpay_client,
    )

    app = create_app(TestConfig)
    with app.test_client() as client:
        with app.app_context():
            resident_role = Role.query.filter_by(name='Resident').first()
            user = User(
                username='resident-verified-payment',
                email='resident-verified-payment@example.com',
                password_hash=generate_password_hash('residentpass123'),
                first_name='Verified',
                last_name='Resident',
                role_id=resident_role.id,
                is_verified=True,
                is_approved=True,
                is_active=True,
            )
            db.session.add(user)
            db.session.commit()

            building = Building(name='Receipt Building', address='Receipt Address')
            db.session.add(building)
            db.session.commit()
            flat = Flat(number='R-101', flat_type='2BHK', building_id=building.id, occupied=True)
            db.session.add(flat)
            db.session.commit()

            resident = Resident(
                user_id=user.id,
                flat_id=flat.id,
                building_id=building.id,
                resident_type='Tenant',
                approval_status='Approved',
                status='Active',
            )
            db.session.add(resident)
            db.session.commit()
            bill = Bill(
                bill_type='Monthly Rent',
                description='Monthly rent',
                amount=2000.0,
                due_date=datetime(2026, 9, 4),
                status='Pending',
                payment_status='Pending',
                resident_id=resident.id,
                flat_id=flat.id,
            )
            db.session.add(bill)
            db.session.commit()
            bill_id = bill.id

        login_response = client.post(
            '/auth/login',
            data={
                'identifier': 'resident-verified-payment@example.com',
                'password': 'residentpass123',
                'role': 'resident',
            },
            follow_redirects=True,
        )
        assert login_response.status_code == 200

        order_response = client.post(f'/billing/create-order/{bill_id}')
        assert order_response.status_code == 200
        assert sent_emails == []
        assert admin_emails == []

        response = client.post('/billing/verify-payment', json={
            'bill_id': bill_id,
            'razorpay_order_id': 'order_test_123',
            'razorpay_payment_id': 'pay_test_456',
            'razorpay_signature': 'signature',
        })
        assert response.status_code == 200
        assert len(sent_emails) == 1
        assert sent_emails[0][1] == 'Payment receipt: Monthly Rent'
        assert 'Transaction ID: pay_test_456' in sent_emails[0][2]
        assert '/billing/payment/' in sent_emails[0][2]
        assert f'/resident/bills/{bill_id}/download' in sent_emails[0][2]
        assert len(admin_emails) == 1
