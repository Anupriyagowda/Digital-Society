from calendar import monthrange
from datetime import datetime, time

from flask import current_app

from app import db
from app.models import Bill, Resident, Setting
from app.notification_service import notify_bill_created


RECURRING_BILL_TYPES = {
    'Flat Owner': 'Maintenance Charges',
    'Tenant': 'Monthly Rent',
}


def get_billing_schedule():
    generation_day = current_app.config['AUTO_BILL_GENERATION_DAY']
    generation_time_text = current_app.config['AUTO_BILL_GENERATION_TIME']
    due_day = current_app.config['AUTO_BILL_DUE_DAY']
    settings = {
        setting.key: setting.value
        for setting in Setting.query.filter(
            Setting.key.in_([
                'auto_bill_generation_day',
                'auto_bill_generation_time',
                'auto_bill_due_day',
            ])
        ).all()
    }
    generation_day = int(settings.get('auto_bill_generation_day', generation_day))
    generation_time_text = settings.get('auto_bill_generation_time', generation_time_text)
    due_day = int(settings.get('auto_bill_due_day', due_day))
    return (
        max(1, min(generation_day, 28)),
        time.fromisoformat(generation_time_text),
        max(1, min(due_day, 28)),
    )


def generate_current_month_bills(now=None):
    now = now or datetime.now()
    generation_day, generation_time, due_day = get_billing_schedule()
    if now.day < generation_day or (now.day == generation_day and now.time() < generation_time):
        return 0

    next_year = now.year + (1 if now.month == 12 else 0)
    next_month = 1 if now.month == 12 else now.month + 1
    billing_period = f'{next_year:04d}-{next_month:02d}'
    due_date = datetime(
        next_year,
        next_month,
        min(due_day, monthrange(next_year, next_month)[1]),
    )
    created_count = 0

    residents = Resident.query.filter(
        Resident.resident_type.in_(RECURRING_BILL_TYPES.keys()),
        Resident.approval_status == 'Approved',
        Resident.status.in_(['Active', 'Pending']),
    ).all()

    for resident in residents:
        bill_type = RECURRING_BILL_TYPES[resident.resident_type]
        current_bill = Bill.query.filter_by(
            resident_id=resident.id,
            bill_type=bill_type,
            billing_period=billing_period,
        ).first()
        if current_bill:
            continue

        template_bill = Bill.query.filter(
            Bill.resident_id == resident.id,
            Bill.bill_type == bill_type,
            Bill.amount > 0,
        ).order_by(Bill.created_at.desc()).first()
        amount = template_bill.amount if template_bill else 0
        if not template_bill and resident.resident_type == 'Tenant':
            amount = current_app.config['AUTO_TENANT_RENT_AMOUNT']
        if amount <= 0:
            continue

        resident_name = (
            f'{resident.user.first_name or ""} {resident.user.last_name or ""}'.strip()
            or resident.user.username
        )
        bill = Bill(
            bill_type=bill_type,
            description=f'{bill_type} for {billing_period}',
            amount=amount,
            due_date=due_date,
            status='Pending',
            resident_name=resident_name,
            flat_number=resident.flat.number if resident.flat else 'Unassigned',
            payment_status='Pending',
            billing_period=billing_period,
            is_automatic=True,
            resident_id=resident.id,
            flat_id=resident.flat_id,
        )
        db.session.add(bill)
        db.session.flush()
        notify_bill_created(bill)
        created_count += 1

    if created_count:
        db.session.commit()
    return created_count