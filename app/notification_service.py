from datetime import date, timedelta

from flask import current_app, url_for

from app import db
from app.mail_service import send_app_email
from app.models import Notification, Resident, Role, User


def notify_user(user_id, title, message, target_url=None):
    if not user_id:
        return False
    if target_url and (not target_url.startswith('/') or target_url.startswith('//')):
        target_url = None
    existing = Notification.query.filter_by(
        user_id=user_id,
        title=title,
        message=message,
    ).first()
    if existing:
        if target_url and not existing.target_url:
            existing.target_url = target_url
            db.session.commit()
        return False
    db.session.add(Notification(user_id=user_id, title=title, message=message, target_url=target_url))
    db.session.commit()
    return True


def notify_role_users(role_names, title, message, exclude_user_id=None, target_urls=None):
    roles = Role.query.filter(Role.name.in_(role_names)).all()
    role_ids = [role.id for role in roles]
    if not role_ids:
        return 0
    query = User.query.filter(
        User.role_id.in_(role_ids),
        User.is_active.is_(True),
    )
    if exclude_user_id:
        query = query.filter(User.id != exclude_user_id)
    created = 0
    for user in query.all():
        target_url = target_urls.get(user.role.name) if isinstance(target_urls, dict) and user.role else target_urls
        created += notify_user(user.id, title, message, target_url)
    return created


def notify_residents(title, message, exclude_user_id=None, target_url=None):
    resident_role = Role.query.filter_by(name='Resident').first()
    if not resident_role:
        return 0
    query = User.query.filter_by(
        role_id=resident_role.id,
        is_active=True,
        is_approved=True,
    )
    if exclude_user_id:
        query = query.filter(User.id != exclude_user_id)
    return sum(notify_user(user.id, title, message, target_url) for user in query.all())


def notify_admins(title, message, target_urls=None):
    return notify_role_users(['Super Admin', 'Society Admin', 'Owner'], title, message, target_urls=target_urls)


def notify_pending_resident_registration(resident):
    resident_name = f'{resident.user.first_name or ""} {resident.user.last_name or ""}'.strip()
    resident_name = resident_name or resident.user.username
    flat_number = resident.flat.number if resident.flat else 'Unassigned'
    return notify_admins(
        'New resident registration',
        f'{resident_name} registered for flat {flat_number} and is awaiting approval.',
    )


def sync_pending_resident_registration_notifications():
    created = 0
    residents = Resident.query.filter_by(approval_status='Pending').all()
    for resident in residents:
        created += notify_pending_resident_registration(resident)
    return created


def email_user(user, subject, body, html=None):
    return send_app_email(user.email if user else None, subject, body, html)


def email_admins(subject, body, html=None):
    admin_roles = Role.query.filter(Role.name.in_(['Super Admin', 'Society Admin', 'Owner'])).all()
    role_ids = [role.id for role in admin_roles]
    users = User.query.filter(User.role_id.in_(role_ids)).all() if role_ids else []
    return sum(email_user(user, subject, body, html) for user in users)


def notify_bill_created(bill):
    title = 'New bill generated'
    message = f'{bill.bill_type} of Rs {bill.amount:,.2f} was generated for your account. Open Billing to view and pay it.'
    target_url = url_for('resident.download_bill', bill_id=bill.id, preview=1)
    if notify_user(bill.resident.user_id, title, message, target_url):
        email_user(bill.resident.user, title, message)


def sync_paid_payment_notifications():
    from app.models import Bill, Payment, Resident

    created = 0
    payments = Payment.query.filter(
        Payment.status == 'Paid',
        Payment.razorpay_payment_id.isnot(None),
    ).all()
    for payment in payments:
        resident = db.session.get(Resident, payment.resident_id)
        bill = db.session.get(Bill, payment.bill_id)
        if not resident or not bill:
            continue
        resident_name = resident.user.first_name or resident.user.username
        created += notify_admins(
            'Payment successful',
            f'{resident_name} paid Rs {payment.amount:,.2f} for {bill.bill_type}.',
            target_urls={
                'Super Admin': url_for('admin.dashboard'),
                'Society Admin': url_for('admin.dashboard'),
                'Owner': url_for('owner.report_bills', status='paid'),
            },
        )
    if created:
        db.session.commit()
    return created


def process_bill_reminders(resident=None, today=None):
    from app.models import Bill

    today = today or date.today()
    due_soon_days = current_app.config.get('BILL_DUE_SOON_DAYS', 3)
    end_date = today + timedelta(days=due_soon_days)
    query = Bill.query.filter(
        Bill.payment_status == 'Pending',
        Bill.due_date.isnot(None),
    )
    if resident:
        query = query.filter_by(resident_id=resident.id)
    created = 0
    for bill in query.all():
        due_date = bill.due_date.date() if hasattr(bill.due_date, 'date') else bill.due_date
        if due_date < today:
            title = 'Bill overdue'
            message = f'{bill.bill_type} of Rs {bill.amount:,.2f} was due on {due_date.strftime("%d %b %Y")}. Please open Billing to pay it.'
        elif due_date <= end_date:
            title = 'Bill due soon'
            message = f'{bill.bill_type} of Rs {bill.amount:,.2f} is due on {due_date.strftime("%d %b %Y")}. Please open Billing to pay it.'
        else:
            continue
        if notify_user(bill.resident.user_id, title, message):
            email_user(bill.resident.user, title, message)
            created += 1
    if created:
        db.session.commit()
    return created
