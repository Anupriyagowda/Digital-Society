import re
from flask import Blueprint, current_app, render_template, redirect, url_for, flash, request, jsonify, send_file
from flask_login import login_required, current_user
from functools import wraps
from datetime import datetime, timedelta
from sqlalchemy import func, desc
from sqlalchemy.orm import joinedload
from werkzeug.security import generate_password_hash
from app import db
from app.mail_service import send_app_email
from app.pdf_service import build_pdf, preview_or_download
from app.billing_service import get_billing_schedule
from app.notification_service import notify_admins, notify_residents, notify_user
from app.notification_service import email_user
from app.models import (
    User, Resident, Event, Participant, Activity, ActivityParticipant, Notice,
    Complaint, ComplaintMessage, MaintenanceRequest, MaintenanceRequestHistory, Bill, Payment,
    Building, Flat, Visitor, Feedback, ComplaintCategory, AuditLog, Role,
    Notification, SurveyResponse, Memo, FamilyMember, EmergencyContact, AuthorizedPerson
)

owner_bp = Blueprint('owner', __name__)


def _normalize_text(value):
    return (value or '').strip()


def _validate_email(email):
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        raise ValueError('Please enter a valid email address.')
    return email.lower()


def _validate_phone(phone):
    if not re.fullmatch(r'\d{10}', phone):
        raise ValueError('Please enter a 10-digit phone number.')
    return phone


def _validate_flat_number(flat_number):
    if len(flat_number) < 2 or len(flat_number) > 20:
        raise ValueError('Flat number must be between 2 and 20 characters long.')
    if not re.fullmatch(r'[A-Za-z0-9\-\/\s]+', flat_number):
        raise ValueError('Flat number contains invalid characters.')
    return flat_number


def _get_allowed_bill_type(resident):
    if getattr(resident, 'resident_type', None) == 'Tenant':
        return 'Monthly Rent'
    if getattr(resident, 'resident_type', None) == 'Flat Owner':
        return 'Maintenance Charges'
    return None


# Decorator to check if user is an owner
def owner_required(f):
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.role or current_user.role.name != 'Owner':
            flash('You need to be an owner to access this page.', 'danger')
            return redirect(url_for('main.dashboard'))
        return f(*args, **kwargs)
    return decorated_function

# ==================== DASHBOARD ====================
@owner_bp.route('/dashboard')
@owner_required
def dashboard():
    """Owner dashboard with analytics and summary"""
    
    # Get statistics
    pending_residents = Resident.query.filter_by(approval_status='Pending').count()
    approved_residents = Resident.query.filter_by(approval_status='Approved').count()
    rejected_residents = Resident.query.filter_by(approval_status='Rejected').count()
    
    total_complaints = Complaint.query.count()
    pending_complaints = Complaint.query.filter_by(status='Pending').count()
    resolved_complaints = Complaint.query.filter_by(status='Resolved').count()
    
    total_maintenance = MaintenanceRequest.query.count()
    pending_maintenance = MaintenanceRequest.query.filter_by(status='Pending').count()
    
    total_events = Event.query.count()
    upcoming_events = Event.query.filter(Event.start_date > datetime.utcnow()).count()
    
    total_notices = Notice.query.count()
    
    # Revenue metrics
    pending_bills = Bill.query.filter_by(status='Pending').count()
    total_revenue = db.session.query(func.sum(Payment.amount)).scalar() or 0
    
    # Get recent data for display
    recent_complaints = Complaint.query.order_by(desc(Complaint.created_at)).limit(5).all()
    recent_notices = Notice.query.order_by(desc(Notice.created_at)).limit(5).all()
    upcoming_events_list = Event.query.filter(Event.start_date > datetime.utcnow()).order_by(Event.start_date).limit(5).all()
    
    # Chart data - Complaints by status
    complaints_by_status = db.session.query(
        Complaint.status, func.count(Complaint.id)
    ).group_by(Complaint.status).all()
    
    # Chart data - Maintenance by status
    maintenance_by_status = db.session.query(
        MaintenanceRequest.status, func.count(MaintenanceRequest.id)
    ).group_by(MaintenanceRequest.status).all()
    
    return render_template('owner/dashboard.html',
        pending_residents=pending_residents,
        approved_residents=approved_residents,
        rejected_residents=rejected_residents,
        total_complaints=total_complaints,
        pending_complaints=pending_complaints,
        resolved_complaints=resolved_complaints,
        total_maintenance=total_maintenance,
        pending_maintenance=pending_maintenance,
        total_events=total_events,
        upcoming_events=upcoming_events,
        total_notices=total_notices,
        pending_bills=pending_bills,
        total_revenue=total_revenue,
        recent_complaints=recent_complaints,
        recent_notices=recent_notices,
        upcoming_events_list=upcoming_events_list,
        complaints_by_status=complaints_by_status,
        maintenance_by_status=maintenance_by_status
    )

# ==================== RESIDENT MANAGEMENT ====================
@owner_bp.route('/residents')
@owner_required
def residents():
    """List all residents with approval status"""
    page = request.args.get('page', 1, type=int)
    status = request.args.get('status', 'all')
    
    # Use the resident relationship instead of an explicit join to avoid ambiguous user joins
    query = Resident.query.options(joinedload(Resident.user), joinedload(Resident.flat))
    
    if status != 'all':
        query = query.filter(Resident.approval_status == status)
    
    residents = query.paginate(page=page, per_page=10)
    return render_template('owner/residents.html', residents=residents, current_status=status)

@owner_bp.route('/resident/<int:resident_id>/approve', methods=['POST'])
@owner_required
def approve_resident(resident_id):
    """Approve a resident"""
    resident = Resident.query.get_or_404(resident_id)
    resident.approval_status = 'Approved'
    resident.status = 'Active'
    resident.approved_by_id = current_user.id
    resident.approval_date = datetime.utcnow()
    if resident.user:
        resident.user.is_approved = True
        notify_user(
            resident.user.id,
            'Resident registration approved',
            'Your society registration has been approved. You can now use the resident portal.',
        )
    db.session.commit()

    if resident.user:
        send_app_email(
            resident.user.email,
            'Digital Society registration approved',
            f'Hello {resident.user.first_name}, your society registration has been approved. You can now log in to the resident portal.',
            f'<p>Hello {resident.user.first_name},</p><p>Your society registration has been approved. You can now log in to the resident portal.</p>',
        )
    
    # Log action
    audit = AuditLog(
        user_id=current_user.id,
        action=f'Approved resident {resident.user.username}',
        details=f'Resident ID: {resident_id}'
    )
    db.session.add(audit)
    db.session.commit()
    
    flash(f'Resident {resident.user.username} has been approved.', 'success')
    return redirect(url_for('owner.residents'))

@owner_bp.route('/resident/<int:resident_id>/reject', methods=['POST'])
@owner_required
def reject_resident(resident_id):
    """Reject a resident"""
    resident = Resident.query.get_or_404(resident_id)
    resident.approval_status = 'Rejected'
    resident.approved_by_id = current_user.id
    resident.approval_date = datetime.utcnow()
    if resident.user:
        resident.user.is_approved = False
    db.session.commit()
    
    # Log action
    audit = AuditLog(
        user_id=current_user.id,
        action=f'Rejected resident {resident.user.username}',
        details=f'Resident ID: {resident_id}'
    )
    db.session.add(audit)
    db.session.commit()
    
    flash(f'Resident {resident.user.username} has been rejected.', 'warning')
    return redirect(url_for('owner.residents'))

@owner_bp.route('/resident/<int:resident_id>/details')
@owner_required
def resident_details(resident_id):
    """View detailed information about a resident"""
    resident = Resident.query.get_or_404(resident_id)
    bills = Bill.query.filter_by(resident_id=resident_id).all()
    complaints = Complaint.query.filter_by(resident_id=resident_id).all()
    maintenance = MaintenanceRequest.query.filter_by(resident_id=resident_id).all()
    family_members = FamilyMember.query.filter_by(resident_id=resident_id).all()
    emergency_contacts = EmergencyContact.query.filter_by(resident_id=resident_id).order_by(EmergencyContact.priority).all()
    authorized_people = AuthorizedPerson.query.filter_by(resident_id=resident_id).all()
    billing_generation_day, billing_generation_time, billing_due_day = get_billing_schedule()
    
    return render_template('owner/resident_detail.html',
        resident=resident,
        bills=bills,
        complaints=complaints,
        maintenance=maintenance,
        family_members=family_members,
        emergency_contacts=emergency_contacts,
        authorized_people=authorized_people,
        billing_generation_day=billing_generation_day,
        billing_generation_time=billing_generation_time.strftime('%H:%M'),
        billing_due_day=billing_due_day,
    )

@owner_bp.route('/resident/<int:resident_id>/edit', methods=['GET', 'POST'])
@owner_required
def edit_resident(resident_id):
    """Edit resident details"""
    resident = Resident.query.get_or_404(resident_id)
    if request.method == 'POST':
        try:
            first_name = request.form.get('first_name', '').strip()
            last_name = request.form.get('last_name', '').strip()
            email = request.form.get('email', '').strip().lower()
            phone = request.form.get('phone', '').strip()
            flat_number = request.form.get('flat_number', '').strip()
            resident_type = request.form.get('resident_type', '').strip()
            emergency_contact = request.form.get('emergency_contact', '').strip()

            if not first_name or not last_name:
                flash('First name and last name are required.', 'warning')
                return redirect(url_for('owner.resident_details', resident_id=resident.id))
            if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
                flash('Please enter a valid email address.', 'warning')
                return redirect(url_for('owner.resident_details', resident_id=resident.id))
            if not re.fullmatch(r'\d{10}', phone):
                flash('Please enter a 10-digit phone number.', 'warning')
                return redirect(url_for('owner.resident_details', resident_id=resident.id))
            if resident_type not in {'Flat Owner', 'Tenant'}:
                flash('Please select a resident type.', 'warning')
                return redirect(url_for('owner.resident_details', resident_id=resident.id))

            existing_user = User.query.filter(User.email == email, User.id != resident.user_id).first()
            if existing_user:
                flash('A different account already uses that email address.', 'warning')
                return redirect(url_for('owner.resident_details', resident_id=resident.id))

            if flat_number:
                existing_flat = Flat.query.filter_by(number=flat_number).first()
                if not existing_flat:
                    building = Building.query.order_by(Building.id).first()
                    if not building:
                        building = Building(name=current_app.config['SOCIETY_NAME'], address='Society')
                        db.session.add(building)
                        db.session.flush()
                    existing_flat = Flat(number=flat_number, flat_type='2BHK', building_id=building.id, occupied=True)
                    db.session.add(existing_flat)
                    db.session.flush()

                duplicate = Resident.query.filter(
                    Resident.id != resident.id,
                    Resident.flat_id == existing_flat.id,
                    Resident.resident_type == resident_type,
                    Resident.approval_status == 'Approved'
                ).first()
                if duplicate:
                    flash('This flat already has an active resident of the same type.', 'warning')
                    return redirect(url_for('owner.resident_details', resident_id=resident.id))

            resident.user.first_name = first_name
            resident.user.last_name = last_name
            resident.user.email = email
            resident.user.phone = phone
            resident.emergency_contact = emergency_contact
            resident.resident_type = resident_type
            if flat_number:
                resident.flat_id = existing_flat.id
                resident.building_id = existing_flat.building_id
            resident.approval_status = 'Pending' if resident.approval_status == 'Rejected' else resident.approval_status
            db.session.add(resident)
            db.session.add(AuditLog(
                user_id=current_user.id,
                action='Resident Edited',
                owner_name=f'{current_user.first_name or current_user.username} {current_user.last_name or ""}'.strip(),
                resident_name=f'{first_name} {last_name}'.strip(),
                flat_number=flat_number,
                description='Resident profile updated by owner'
            ))
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash('We could not update the resident details. Please try again.', 'danger')
            return redirect(url_for('owner.resident_details', resident_id=resident.id))

        flash('Resident details updated successfully.', 'success')
        return redirect(url_for('owner.residents'))

    return redirect(url_for('owner.resident_details', resident_id=resident.id))

@owner_bp.route('/resident/<int:resident_id>/billing', methods=['POST'])
@owner_required
def manage_resident_bill(resident_id):
    resident = Resident.query.get_or_404(resident_id)
    bill_id = request.form.get('bill_id', type=int)
    bill_type = (request.form.get('bill_type') or '').strip()
    description = (request.form.get('description') or '').strip()
    amount_text = (request.form.get('amount') or '').strip()
    due_date_text = (request.form.get('due_date') or '').strip()
    payment_status = (request.form.get('payment_status') or 'Pending').strip() or 'Pending'
    payment_date_text = (request.form.get('payment_date') or '').strip()

    if not amount_text or not due_date_text:
        flash('Please provide a bill amount and due date.', 'warning')
        return redirect(url_for('owner.resident_details', resident_id=resident.id))

    allowed_bill_type = _get_allowed_bill_type(resident)
    valid_bill_types = {'Maintenance Charges', 'Monthly Rent'}

    if not bill_type:
        bill_type = allowed_bill_type or 'Maintenance Charges'
    elif bill_type not in valid_bill_types:
        bill_type = allowed_bill_type or 'Maintenance Charges'

    try:
        amount = float(amount_text)
    except ValueError:
        flash('Please enter a valid amount.', 'warning')
        return redirect(url_for('owner.resident_details', resident_id=resident.id))

    try:
        due_date = datetime.strptime(due_date_text, '%Y-%m-%d')
    except ValueError:
        flash('Please enter a valid due date in YYYY-MM-DD format.', 'warning')
        return redirect(url_for('owner.resident_details', resident_id=resident.id))

    payment_date = None
    if payment_date_text:
        try:
            payment_date = datetime.strptime(payment_date_text, '%Y-%m-%d').date()
        except ValueError:
            flash('Please enter a valid payment date in YYYY-MM-DD format.', 'warning')
            return redirect(url_for('owner.resident_details', resident_id=resident.id))

    resident_name = f"{resident.user.first_name or ''} {resident.user.last_name or ''}".strip() or resident.user.username
    flat_number = resident.flat.number if resident.flat else 'Unassigned'
    created_new_bill = False

    if bill_id:
        bill = Bill.query.get_or_404(bill_id)
        bill.bill_type = bill_type
        bill.description = description or f'{bill_type} for {resident_name}'
        bill.amount = amount
        bill.due_date = due_date
        bill.status = 'Paid' if payment_status == 'Paid' else 'Pending'
        bill.payment_status = payment_status
        bill.payment_date = payment_date
        bill.resident_name = resident_name
        bill.flat_number = flat_number
        bill.flat_id = resident.flat_id
    else:
        existing_bill = Bill.query.filter_by(resident_id=resident.id, bill_type=bill_type).first()
        if existing_bill:
            bill = existing_bill
            bill.description = description or f'{bill_type} for {resident_name}'
            bill.amount = amount
            bill.due_date = due_date
            bill.status = 'Paid' if payment_status == 'Paid' else 'Pending'
            bill.payment_status = payment_status
            bill.payment_date = payment_date
            bill.resident_name = resident_name
            bill.flat_number = flat_number
            bill.flat_id = resident.flat_id
        else:
            bill = Bill(
                bill_type=bill_type,
                description=description or f'{bill_type} for {resident_name}',
                amount=amount,
                due_date=due_date,
                status='Paid' if payment_status == 'Paid' else 'Pending',
                resident_name=resident_name,
                flat_number=flat_number,
                payment_status=payment_status,
                payment_date=payment_date,
                resident_id=resident.id,
                flat_id=resident.flat_id,
            )
            db.session.add(bill)
            created_new_bill = True

    if payment_status == 'Paid' and not bill.payment_date:
        bill.payment_date = datetime.utcnow().date()
        bill.payment_status = 'Paid'
        bill.status = 'Paid'
    elif payment_status == 'Pending':
        bill.payment_date = None
        bill.payment_status = 'Pending'
        bill.status = 'Pending'

    if payment_status == 'Paid':
        payment = Payment.query.filter_by(bill_id=bill.id).first()
        if not payment:
            db.session.add(Payment(
                bill_id=bill.id,
                resident_id=resident.id,
                amount=amount,
                payment_method='Online',
                status='Paid',
                transaction_id=f'BILL-{bill.id}-{int(datetime.utcnow().timestamp())}',
            ))

    if created_new_bill:
        notify_user(
            resident.user_id,
            'New bill generated',
            f'{bill.bill_type} of Rs {bill.amount:,.2f} was added to your account. Open Billing to view and pay it.',
            url_for('resident.download_bill', bill_id=bill.id, preview=1),
        )
        email_user(resident.user, 'New bill generated', f'{bill.bill_type} of Rs {bill.amount:,.2f} was added to your account. Open Billing to view and pay it.')

    db.session.commit()
    flash('Billing record saved successfully.', 'success')
    return redirect(url_for('owner.resident_details', resident_id=resident.id))


@owner_bp.route('/resident/<int:resident_id>/billing/<int:bill_id>/mark-paid', methods=['POST'])
@owner_required
def mark_resident_bill_paid(resident_id, bill_id):
    resident = Resident.query.get_or_404(resident_id)
    bill = Bill.query.filter_by(id=bill_id, resident_id=resident.id).first_or_404()
    bill.status = 'Paid'
    bill.payment_status = 'Paid'
    bill.payment_date = datetime.utcnow().date()
    payment = Payment.query.filter_by(bill_id=bill.id).first()
    if not payment:
        db.session.add(Payment(
            bill_id=bill.id,
            resident_id=resident.id,
            amount=bill.amount,
            payment_method='Online',
            status='Paid',
            transaction_id=f'BILL-{bill.id}-{int(datetime.utcnow().timestamp())}',
        ))
    db.session.commit()
    flash('Bill marked as paid.', 'success')
    return redirect(url_for('owner.resident_details', resident_id=resident.id))


@owner_bp.route('/resident/<int:resident_id>/deactivate', methods=['POST'])
@owner_required
def deactivate_resident(resident_id):
    """Deactivate a resident without deleting related records"""
    resident = Resident.query.get_or_404(resident_id)
    if resident.user:
        resident.user.is_active = False
        resident.user.is_approved = False
    resident.approval_status = 'Rejected'
    resident.status = 'Inactive'
    db.session.add(AuditLog(
        user_id=current_user.id,
        action='Resident Deactivated',
        owner_name=f'{current_user.first_name or current_user.username} {current_user.last_name or ""}'.strip(),
        resident_name=f'{resident.user.first_name or resident.user.username} {resident.user.last_name or ""}'.strip(),
        flat_number=resident.flat.number if resident.flat else 'Unassigned',
        description='Resident account deactivated by owner'
    ))
    db.session.commit()
    flash('Resident account deactivated successfully.', 'warning')
    return redirect(url_for('owner.residents'))

@owner_bp.route('/resident/<int:resident_id>/reactivate', methods=['POST'])
@owner_required
def reactivate_resident(resident_id):
    """Reactivate a previously deactivated resident"""
    resident = Resident.query.get_or_404(resident_id)
    if resident.user:
        resident.user.is_active = True
        resident.user.is_approved = False
    resident.approval_status = 'Pending'
    resident.status = 'Active'
    db.session.add(AuditLog(
        user_id=current_user.id,
        action='Resident Reactivated',
        owner_name=f'{current_user.first_name or current_user.username} {current_user.last_name or ""}'.strip(),
        resident_name=f'{resident.user.first_name or resident.user.username} {resident.user.last_name or ""}'.strip(),
        flat_number=resident.flat.number if resident.flat else 'Unassigned',
        description='Resident account reactivated by owner'
    ))
    db.session.commit()
    flash('Resident account reactivated successfully.', 'success')
    return redirect(url_for('owner.residents'))

@owner_bp.route('/resident/<int:resident_id>/delete', methods=['POST'])
@owner_required
def delete_resident_user(resident_id):
    """Delete a resident and their linked user account."""
    resident = Resident.query.get_or_404(resident_id)
    user = resident.user

    if user:
        Notification.query.filter_by(user_id=user.id).delete()
        Complaint.query.filter_by(resident_id=resident.id).delete()
        MaintenanceRequestHistory.query.filter(
            MaintenanceRequestHistory.maintenance_request_id.in_(
                db.session.query(MaintenanceRequest.id).filter_by(resident_id=resident.id)
            )
        ).delete(synchronize_session=False)
        MaintenanceRequest.query.filter_by(resident_id=resident.id).delete()
        Payment.query.filter_by(resident_id=resident.id).delete()
        Bill.query.filter_by(resident_id=resident.id).delete()
        Participant.query.filter_by(resident_id=resident.id).delete()
        ActivityParticipant.query.filter_by(resident_id=resident.id).delete()
        SurveyResponse.query.filter_by(resident_id=resident.id).delete()
        Memo.query.filter_by(resident_id=resident.id).delete()
        Visitor.query.filter_by(resident_id=resident.id).delete()

        db.session.delete(resident)
        db.session.delete(user)
        db.session.commit()
        flash('Resident user deleted successfully.', 'success')
        return redirect(url_for('owner.residents'))

    db.session.delete(resident)
    db.session.commit()
    flash('Resident record deleted successfully.', 'success')
    return redirect(url_for('owner.residents'))

@owner_bp.route('/activity-logs')
@owner_required
def activity_logs():
    """Display owner activity logs with search and filters"""
    search = request.args.get('search', '').strip()
    action_filter = request.args.get('action', '').strip()
    resident_filter = request.args.get('resident', '').strip()
    flat_filter = request.args.get('flat', '').strip()
    date_filter = request.args.get('date', '').strip()

    query = AuditLog.query.order_by(AuditLog.created_at.desc())
    if search:
        query = query.filter((AuditLog.action.ilike(f'%{search}%')) | (AuditLog.details.ilike(f'%{search}%')) | (AuditLog.resident_name.ilike(f'%{search}%')) | (AuditLog.flat_number.ilike(f'%{search}%')))
    if action_filter:
        query = query.filter(AuditLog.action == action_filter)
    if resident_filter:
        query = query.filter(AuditLog.resident_name.ilike(f'%{resident_filter}%'))
    if flat_filter:
        query = query.filter(AuditLog.flat_number.ilike(f'%{flat_filter}%'))
    if date_filter:
        query = query.filter(db.func.date(AuditLog.created_at) == date_filter)

    logs = query.all()
    actions = [row[0] for row in db.session.query(AuditLog.action).distinct().order_by(AuditLog.action).all()]
    return render_template('owner/activity_logs.html', logs=logs, actions=actions, search=search, action_filter=action_filter, resident_filter=resident_filter, flat_filter=flat_filter, date_filter=date_filter)

# ==================== NOTICE MANAGEMENT ====================
@owner_bp.route('/notices')
@owner_required
def notices():
    """List all notices"""
    page = request.args.get('page', 1, type=int)
    notices = Notice.query.order_by(desc(Notice.created_at)).paginate(page=page, per_page=10)
    return render_template('owner/notices.html', notices=notices)

@owner_bp.route('/notice/create', methods=['GET', 'POST'])
@owner_required
def create_notice():
    """Create a new notice"""
    if request.method == 'POST':
        title = _normalize_text(request.form.get('title'))
        content = _normalize_text(request.form.get('content'))
        notice_type = _normalize_text(request.form.get('notice_type', 'General'))
        priority = _normalize_text(request.form.get('priority', 'Normal'))
        is_pinned = 'is_pinned' in request.form
        expires_at = request.form.get('expires_at')

        if not title or len(title) > 120:
            flash('Notice title is required and must be 120 characters or less.', 'warning')
            return render_template('owner/create_notice.html')
        if not content or len(content) > 4000:
            flash('Notice content is required and must be 4000 characters or less.', 'warning')
            return render_template('owner/create_notice.html')
        if expires_at:
            try:
                expires_at = datetime.fromisoformat(expires_at)
            except ValueError:
                flash('Please enter a valid expiry date.', 'warning')
                return render_template('owner/create_notice.html')
        
        notice = Notice(
            title=title,
            content=content,
            notice_type=notice_type,
            priority=priority,
            is_pinned=is_pinned,
            expires_at=expires_at,
            created_by_id=current_user.id
        )
        db.session.add(notice)
        db.session.commit()
        notify_residents('New society notice', f'{title} has been posted. Open Notices to read it.')
        
        # Log action
        audit = AuditLog(
            user_id=current_user.id,
            action='Created notice',
            details=f'Notice: {title}'
        )
        db.session.add(audit)
        db.session.commit()
        
        flash('Notice created successfully!', 'success')
        return redirect(url_for('owner.notices'))
    
    return render_template('owner/create_notice.html')

@owner_bp.route('/notice/<int:notice_id>/edit', methods=['GET', 'POST'])
@owner_required
def edit_notice(notice_id):
    """Edit a notice"""
    notice = Notice.query.get_or_404(notice_id)
    
    if request.method == 'POST':
        notice.title = request.form.get('title')
        notice.content = request.form.get('content')
        notice.notice_type = request.form.get('notice_type')
        notice.priority = request.form.get('priority')
        notice.is_pinned = 'is_pinned' in request.form
        expires_at = request.form.get('expires_at')
        if expires_at:
            notice.expires_at = datetime.fromisoformat(expires_at)
        
        db.session.commit()
        flash('Notice updated successfully!', 'success')
        return redirect(url_for('owner.notices'))
    
    return render_template('owner/edit_notice.html', notice=notice)

@owner_bp.route('/notice/<int:notice_id>/delete', methods=['POST'])
@owner_required
def delete_notice(notice_id):
    """Delete a notice"""
    notice = Notice.query.get_or_404(notice_id)
    db.session.delete(notice)
    db.session.commit()
    
    flash('Notice deleted successfully!', 'success')
    return redirect(url_for('owner.notices'))

# ==================== EVENT MANAGEMENT ====================
@owner_bp.route('/events')
@owner_required
def events():
    """List all events"""
    page = request.args.get('page', 1, type=int)
    events = Event.query.order_by(desc(Event.start_date)).paginate(page=page, per_page=10)
    return render_template('owner/events.html', events=events)

@owner_bp.route('/event/create', methods=['GET', 'POST'])
@owner_required
def create_event():
    """Create a new event"""
    if request.method == 'POST':
        title = _normalize_text(request.form.get('title'))
        description = _normalize_text(request.form.get('description'))
        location = _normalize_text(request.form.get('location'))
        event_type = _normalize_text(request.form.get('event_type', 'General'))
        try:
            start_date = datetime.fromisoformat(request.form.get('start_date'))
            end_date = datetime.fromisoformat(request.form.get('end_date'))
            max_capacity = int(request.form.get('max_capacity', 100))
        except ValueError:
            flash('Please enter valid event dates and capacity.', 'warning')
            return render_template('owner/create_event.html')
        if not title or len(title) > 120:
            flash('Event title is required and must be 120 characters or less.', 'warning')
            return render_template('owner/create_event.html')
        if len(location) > 120:
            flash('Location must be 120 characters or less.', 'warning')
            return render_template('owner/create_event.html')
        if start_date >= end_date:
            flash('End date must be after the start date.', 'warning')
            return render_template('owner/create_event.html')
        if max_capacity < 1 or max_capacity > 1000:
            flash('Capacity must be between 1 and 1000.', 'warning')
            return render_template('owner/create_event.html')
        
        event = Event(
            title=title,
            description=description,
            start_date=start_date,
            end_date=end_date,
            location=location,
            event_type=event_type,
            max_capacity=max_capacity,
            created_by_id=current_user.id
        )
        db.session.add(event)
        db.session.commit()
        
        activity_titles = request.form.getlist('activity_title[]')
        activity_descriptions = request.form.getlist('activity_description[]')
        activity_limits = request.form.getlist('activity_max_participants[]')
        created_activities = False

        for title_value, description_value, limit_value in zip(activity_titles, activity_descriptions, activity_limits):
            title_value = title_value.strip()
            if not title_value:
                continue
            try:
                max_participants = int(limit_value)
            except (ValueError, TypeError):
                max_participants = 20
            if max_participants < 1:
                max_participants = 1

            activity = Activity(
                title=title_value,
                description=_normalize_text(description_value),
                max_participants=max_participants,
                status='Active',
                created_by_id=current_user.id,
                event_id=event.id
            )
            db.session.add(activity)
            created_activities = True

        if created_activities:
            db.session.commit()

        # Log action
        audit = AuditLog(
            user_id=current_user.id,
            action='Created event',
            details=f'Event: {title}'
        )
        db.session.add(audit)
        db.session.commit()
        notify_residents(
            'New society event',
            f'{title} is scheduled for {start_date.strftime("%d %b %Y")} at {location or "the society"}.',
        )
        
        flash('Event created successfully!', 'success')
        return redirect(url_for('owner.events'))
    
    return render_template('owner/create_event.html')

@owner_bp.route('/activities')
@owner_required
def activities():
    page = request.args.get('page', 1, type=int)
    activities = Activity.query.order_by(desc(Activity.created_at)).paginate(page=page, per_page=10)
    return render_template('owner/activities.html', activities=activities)


@owner_bp.route('/activity/create', methods=['GET', 'POST'])
@owner_required
def create_activity():
    if request.method == 'POST':
        title = _normalize_text(request.form.get('title'))
        description = _normalize_text(request.form.get('description'))
        status = _normalize_text(request.form.get('status', 'Active'))
        try:
            max_participants = int(request.form.get('max_participants', 20))
        except ValueError:
            flash('Please enter a valid participant limit.', 'warning')
            return render_template('owner/create_activity.html')

        if not title or len(title) > 120:
            flash('Activity title is required and must be 120 characters or less.', 'warning')
            return render_template('owner/create_activity.html')
        if max_participants < 1 or max_participants > 200:
            flash('Participant limit must be between 1 and 200.', 'warning')
            return render_template('owner/create_activity.html')
        if status not in {'Active', 'Closed'}:
            status = 'Active'

        activity = Activity(
            title=title,
            description=description,
            max_participants=max_participants,
            status=status,
            created_by_id=current_user.id
        )
        db.session.add(activity)
        db.session.commit()
        notify_residents('New society activity', f'{title} is now open for registration.')

        flash('Activity created successfully!', 'success')
        return redirect(url_for('owner.activities'))

    return render_template('owner/create_activity.html')


@owner_bp.route('/activity/<int:activity_id>/details')
@owner_required
def activity_details(activity_id):
    activity = Activity.query.get_or_404(activity_id)
    participants = ActivityParticipant.query.filter_by(activity_id=activity_id).all()
    return render_template('owner/activity_detail.html', activity=activity, participants=participants)


@owner_bp.route('/event/<int:event_id>/edit', methods=['GET', 'POST'])
@owner_required
def edit_event(event_id):
    """Edit an event"""
    event = Event.query.get_or_404(event_id)
    
    if request.method == 'POST':
        event.title = request.form.get('title')
        event.description = request.form.get('description')
        event.start_date = datetime.fromisoformat(request.form.get('start_date'))
        event.end_date = datetime.fromisoformat(request.form.get('end_date'))
        event.location = request.form.get('location')
        event.event_type = request.form.get('event_type')
        event.max_capacity = int(request.form.get('max_capacity'))
        event.status = request.form.get('status', 'Active')

        participants = Participant.query.filter_by(event_id=event.id, status='Registered').all()
        if event.status == 'Cancelled':
            for participant in participants:
                notify_user(
                    participant.resident.user_id,
                    'Event cancelled',
                    f'The event "{event.title}" has been cancelled by the society administrator.',
                )
        else:
            for participant in participants:
                notify_user(
                    participant.resident.user_id,
                    'Event updated',
                    f'The event "{event.title}" details or schedule have changed.',
                )
        
        db.session.commit()
        flash('Event updated successfully!', 'success')
        return redirect(url_for('owner.events'))
    
    return render_template('owner/edit_event.html', event=event)

@owner_bp.route('/event/<int:event_id>/details')
@owner_required
def event_details(event_id):
    """View event details with participants"""
    event = Event.query.get_or_404(event_id)
    participants = Participant.query.filter_by(event_id=event_id, status='Registered').all()
    activity_summaries = []
    for activity in event.activities:
        activity_participants = ActivityParticipant.query.filter_by(activity_id=activity.id, status='Registered').all()
        activity_summaries.append({
            'activity': activity,
            'participants': activity_participants,
            'count': len(activity_participants)
        })

    return render_template(
        'owner/event_detail.html',
        event=event,
        participants=participants,
        participant_count=len(participants),
        activity_summaries=activity_summaries
    )

@owner_bp.route('/event/<int:event_id>/delete', methods=['POST'])
@owner_required
def delete_event(event_id):
    """Delete an event"""
    event = Event.query.get_or_404(event_id)
    db.session.delete(event)
    db.session.commit()
    
    flash('Event deleted successfully!', 'success')
    return redirect(url_for('owner.events'))

# ==================== STAFF MANAGEMENT ====================
@owner_bp.route('/staff')
@owner_required
def staff_management():
    """Manage security and maintenance staff"""
    page = request.args.get('page', 1, type=int)
    staff_type = request.args.get('type', 'all')
    
    query = User.query.join(Role)
    
    if staff_type == 'security':
        query = query.filter(Role.name == 'Security Guard')
    elif staff_type == 'maintenance':
        query = query.filter(Role.name == 'Maintenance Staff')
    else:
        query = query.filter(Role.name.in_(['Security Guard', 'Maintenance Staff']))
    
    staff = query.paginate(page=page, per_page=10)
    return render_template('owner/staff.html', staff=staff, staff_type=staff_type)

@owner_bp.route('/staff/create', methods=['GET', 'POST'])
@owner_required
def create_staff():
    """Create a new staff user"""
    roles = Role.query.filter(Role.name.in_(['Security Guard', 'Maintenance Staff'])).all()
    if request.method == 'POST':
        username = _normalize_text(request.form.get('username'))
        email = _normalize_text(request.form.get('email'))
        first_name = _normalize_text(request.form.get('first_name'))
        last_name = _normalize_text(request.form.get('last_name'))
        phone = _normalize_text(request.form.get('phone'))
        role_name = _normalize_text(request.form.get('role_name'))
        password = request.form.get('password') or 'Password123'

        if not username or len(username) > 80:
            flash('Username is required and must be 80 characters or less.', 'warning')
            return render_template('owner/manage_staff.html', action='Create', roles=roles, staff=None)
        if not email or len(email) > 120:
            flash('Email is required and must be 120 characters or less.', 'warning')
            return render_template('owner/manage_staff.html', action='Create', roles=roles, staff=None)
        if not role_name:
            flash('Role is required.', 'warning')
            return render_template('owner/manage_staff.html', action='Create', roles=roles, staff=None)
        try:
            email = _validate_email(email)
            phone = _validate_phone(phone) if phone else ''
        except ValueError as exc:
            flash(str(exc), 'warning')
            return render_template('owner/manage_staff.html', action='Create', roles=roles, staff=None)

        if User.query.filter((User.username == username) | (User.email == email)).first():
            flash('A user with that username or email already exists.', 'warning')
            return render_template('owner/manage_staff.html', action='Create', roles=roles, staff=None)

        role = Role.query.filter_by(name=role_name).first()
        if not role:
            flash('Selected role is invalid.', 'danger')
            return render_template('owner/manage_staff.html', action='Create', roles=roles, staff=None)

        staff = User(
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            role_id=role.id,
            password_hash=generate_password_hash(password),
            is_verified=True,
            is_approved=True
        )
        db.session.add(staff)
        db.session.commit()
        flash('Staff member created successfully!', 'success')
        return redirect(url_for('owner.staff_management'))

    return render_template('owner/manage_staff.html', action='Create', roles=roles, staff=None)


@owner_bp.route('/staff/<int:staff_id>/edit', methods=['GET', 'POST'])
@owner_required
def edit_staff(staff_id):
    """Edit a staff user"""
    staff = User.query.get_or_404(staff_id)
    allowed_roles = ['Security Guard', 'Maintenance Staff']
    if staff.role.name not in allowed_roles:
        flash('Only staff members can be edited here.', 'danger')
        return redirect(url_for('owner.staff_management'))

    roles = Role.query.filter(Role.name.in_(allowed_roles)).all()
    if request.method == 'POST':
        username = _normalize_text(request.form.get('username'))
        email = _normalize_text(request.form.get('email'))
        first_name = _normalize_text(request.form.get('first_name'))
        last_name = _normalize_text(request.form.get('last_name'))
        phone = _normalize_text(request.form.get('phone'))
        role_name = _normalize_text(request.form.get('role_name'))
        password = request.form.get('password')
        is_approved = 'is_approved' in request.form

        if not username or len(username) > 80:
            flash('Username is required and must be 80 characters or less.', 'warning')
            return render_template('owner/manage_staff.html', action='Edit', roles=roles, staff=staff)
        if not email or len(email) > 120:
            flash('Email is required and must be 120 characters or less.', 'warning')
            return render_template('owner/manage_staff.html', action='Edit', roles=roles, staff=staff)
        if not role_name:
            flash('Role is required.', 'warning')
            return render_template('owner/manage_staff.html', action='Edit', roles=roles, staff=staff)
        try:
            email = _validate_email(email)
            phone = _validate_phone(phone) if phone else ''
        except ValueError as exc:
            flash(str(exc), 'warning')
            return render_template('owner/manage_staff.html', action='Edit', roles=roles, staff=staff)

        existing = User.query.filter(User.id != staff.id).filter((User.username == username) | (User.email == email)).first()
        if existing:
            flash('A different user already uses that username or email.', 'warning')
            return render_template('owner/manage_staff.html', action='Edit', roles=roles, staff=staff)

        role = Role.query.filter_by(name=role_name).first()
        if not role:
            flash('Selected role is invalid.', 'danger')
            return render_template('owner/manage_staff.html', action='Edit', roles=roles, staff=staff)

        staff.username = username
        staff.email = email
        staff.first_name = first_name
        staff.last_name = last_name
        staff.phone = phone
        staff.role_id = role.id
        if password:
            staff.password_hash = generate_password_hash(password)
        staff.is_approved = is_approved
        db.session.commit()
        flash('Staff member updated successfully!', 'success')
        return redirect(url_for('owner.staff_management'))

    return render_template('owner/manage_staff.html', action='Edit', roles=roles, staff=staff)


@owner_bp.route('/staff/<int:staff_id>/delete', methods=['POST'])
@owner_required
def delete_staff(staff_id):
    """Delete a staff user"""
    staff = User.query.get_or_404(staff_id)
    if staff.role.name not in ['Security Guard', 'Maintenance Staff']:
        flash('Only staff members can be deleted here.', 'danger')
        return redirect(url_for('owner.staff_management'))

    Complaint.query.filter_by(assigned_to_id=staff.id).update({'assigned_to_id': None})
    MaintenanceRequest.query.filter_by(staff_id=staff.id).update({'staff_id': None})
    db.session.delete(staff)
    db.session.commit()

    flash('Staff member deleted successfully!', 'success')
    return redirect(url_for('owner.staff_management'))


@owner_bp.route('/staff/<int:staff_id>/details')
@owner_required
def staff_details(staff_id):
    """View staff details and assignments"""
    staff = User.query.get_or_404(staff_id)

    if staff.role.name == 'Security Guard':
        assignments = Visitor.query.filter_by(status='Checked In').all()
    elif staff.role.name == 'Maintenance Staff':
        assignments = MaintenanceRequest.query.filter_by(staff_id=staff_id).all()
    else:
        assignments = []

    return render_template('owner/staff_detail.html', staff=staff, assignments=assignments)


@owner_bp.route('/staff/<int:staff_id>/toggle-status', methods=['POST'])
@owner_required
def toggle_staff_status(staff_id):
    """Toggle staff active/inactive status"""
    staff = User.query.get_or_404(staff_id)
    staff.is_approved = not staff.is_approved
    db.session.commit()

    status = 'activated' if staff.is_approved else 'deactivated'
    flash(f'Staff member {status} successfully!', 'success')
    return redirect(url_for('owner.staff_management'))


# ==================== COMPLAINT MANAGEMENT ====================
@owner_bp.route('/complaints')
@owner_required
def complaints():
    """View all complaints."""
    page = request.args.get('page', 1, type=int)
    status = request.args.get('status', 'all')

    query = Complaint.query.options(
        joinedload(Complaint.resident).joinedload(Resident.user),
        joinedload(Complaint.assigned_to)
    )

    if status not in ('all', None, ''):
        query = query.filter(Complaint.status == status)

    complaints = query.order_by(desc(Complaint.created_at)).paginate(page=page, per_page=10)
    return render_template('owner/complaints.html', complaints=complaints, current_status=status)

@owner_bp.route('/complaint/<int:complaint_id>/assign', methods=['POST'])
@owner_required
def assign_complaint(complaint_id):
    """Assign a complaint to staff"""
    complaint = Complaint.query.get_or_404(complaint_id)
    staff_id = request.form.get('staff_id')
    staff = None

    if staff_id:
        staff = User.query.filter_by(id=int(staff_id)).first()
        if not staff or not staff.role or staff.role.name not in {'Security Guard', 'Maintenance Staff'}:
            flash('Selected staff member is not valid.', 'warning')
            return redirect(url_for('owner.complaint_detail', complaint_id=complaint.id))
        complaint.assigned_to_id = staff.id
        complaint.status = 'Assigned'
    else:
        complaint.assigned_to_id = None
        complaint.status = 'Pending'

    db.session.commit()
    if staff:
        notify_user(staff.id, 'Complaint assigned', f'Complaint "{complaint.title}" has been assigned to you.')
    notify_user(
        complaint.resident.user_id,
        'Complaint status changed',
        f'Your complaint "{complaint.title}" is now {complaint.status}.',
        url_for('resident.complaint_detail', complaint_id=complaint.id),
    )
    flash('Complaint assignment updated successfully!', 'success')
    return redirect(url_for('owner.complaints'))


@owner_bp.route('/complaint/<int:complaint_id>/status', methods=['POST'])
@owner_required
def update_complaint_status(complaint_id):
    """Update complaint status"""
    complaint = Complaint.query.get_or_404(complaint_id)
    action = request.form.get('action')

    status_map = {
        'pending': 'Pending',
        'processing': 'Processing',
        'assigned': 'Assigned',
        'resolved': 'Resolved'
    }
    if action not in status_map:
        flash('Unknown complaint action.', 'warning')
        return redirect(url_for('owner.complaints', status=request.args.get('status', 'all')))

    complaint.status = status_map[action]
    notify_user(
        complaint.resident.user_id,
        'Complaint status changed',
        f'Your complaint "{complaint.title}" is now {complaint.status}.',
        url_for('resident.complaint_detail', complaint_id=complaint.id),
    )
    db.session.commit()
    email_user(complaint.resident.user, 'Complaint status changed', f'Your complaint "{complaint.title}" is now {complaint.status}.')
    flash(f'Complaint status updated to {complaint.status}.', 'success')
    return redirect(url_for('owner.complaints', status=request.args.get('status', 'all')))


@owner_bp.route('/complaint/<int:complaint_id>')
@owner_required
def complaint_detail(complaint_id):
    """View complaint detail and update status"""
    complaint = Complaint.query.get_or_404(complaint_id)
    staff_roles = Role.query.filter(Role.name.in_(['Security Guard', 'Maintenance Staff'])).all()
    staff_members = User.query.filter(User.role_id.in_([role.id for role in staff_roles])).all()
    return render_template('owner/complaint_detail.html', complaint=complaint, staff_members=staff_members)


@owner_bp.route('/complaint/<int:complaint_id>/messages', methods=['POST'])
@owner_required
def reply_to_complaint(complaint_id):
    complaint = Complaint.query.get_or_404(complaint_id)
    message = (request.form.get('message') or '').strip()
    if not message:
        flash('Reply cannot be empty.', 'warning')
        return redirect(url_for('owner.complaint_detail', complaint_id=complaint.id))
    db.session.add(ComplaintMessage(complaint_id=complaint.id, sender_id=current_user.id, message=message))
    db.session.commit()
    notify_user(
        complaint.resident.user_id,
        'New complaint reply',
        f'An administrator replied to your complaint "{complaint.title}".',
        url_for('resident.complaint_detail', complaint_id=complaint.id),
    )
    db.session.commit()
    email_user(complaint.resident.user, 'New complaint reply', f'An administrator replied to your complaint "{complaint.title}". Log in to view the reply.')
    flash('Reply sent.', 'success')
    return redirect(url_for('owner.complaint_detail', complaint_id=complaint.id))


# ==================== MAINTENANCE MANAGEMENT ====================
@owner_bp.route('/maintenance')
@owner_required
def maintenance_requests():
    """View all maintenance requests"""
    page = request.args.get('page', 1, type=int)
    status = request.args.get('status', 'all')
    
    query = MaintenanceRequest.query
    if status != 'all':
        query = query.filter(MaintenanceRequest.status == status)
    
    maintenance = query.order_by(desc(MaintenanceRequest.created_at)).paginate(page=page, per_page=10)
    return render_template('owner/maintenance.html', maintenance=maintenance, current_status=status)

@owner_bp.route('/maintenance/<int:request_id>')
@owner_required
def maintenance_detail(request_id):
    """View maintenance request details and assign staff."""
    maintenance = MaintenanceRequest.query.get_or_404(request_id)
    staff_role = Role.query.filter_by(name='Maintenance Staff').first()
    staff_members = User.query.filter_by(role_id=staff_role.id).all() if staff_role else []
    status_options = ['Pending', 'Assigned', 'In Progress', 'Completed', 'Resolved']
    return render_template('owner/maintenance_detail.html', maintenance=maintenance, staff_members=staff_members, status_options=status_options)


@owner_bp.route('/maintenance/<int:request_id>/assign', methods=['POST'])
@owner_required
def assign_maintenance(request_id):
    """Assign maintenance to staff"""
    maintenance = MaintenanceRequest.query.get_or_404(request_id)
    staff_role = Role.query.filter_by(name='Maintenance Staff').first()
    staff_id = request.form.get('staff_id')
    note = request.form.get('note', '').strip()
    previous_staff_id = maintenance.staff_id
    staff = None

    if staff_id and staff_role:
        staff = User.query.filter_by(id=int(staff_id), role_id=staff_role.id).first()
        if staff:
            maintenance.staff_id = staff.id
            if maintenance.status == 'Pending':
                maintenance.status = 'Assigned'
            history_note = note or f'Assigned to {staff.first_name or staff.username}'
        else:
            flash('Selected staff member is not valid.', 'warning')
            return redirect(url_for('owner.maintenance_detail', request_id=request_id))
    else:
        maintenance.staff_id = None
        if maintenance.status == 'Assigned':
            maintenance.status = 'Pending'
        history_note = note or 'Maintenance request unassigned.'

    db.session.add(MaintenanceRequestHistory(
        maintenance_request_id=maintenance.id,
        updated_by_id=current_user.id,
        status=maintenance.status,
        note=history_note
    ))
    db.session.commit()
    if staff and staff.id != previous_staff_id:
        notify_user(staff.id, 'Maintenance request assigned', f'Maintenance request "{maintenance.title}" has been assigned to you.')
    if previous_staff_id and previous_staff_id != maintenance.staff_id:
        notify_user(previous_staff_id, 'Maintenance assignment changed', f'Maintenance request "{maintenance.title}" is no longer assigned to you.')
    if maintenance.resident and maintenance.resident.user:
        notify_user(
            maintenance.resident.user_id,
            'Maintenance assigned',
            f'Your maintenance request "{maintenance.title}" is now {maintenance.status}. {history_note}'.strip(),
        )
        email_user(maintenance.resident.user, 'Maintenance assigned', f'Your maintenance request "{maintenance.title}" is now {maintenance.status}. {history_note}')
    
    flash('Maintenance assignment updated successfully!', 'success')
    return redirect(url_for('owner.maintenance_detail', request_id=request_id))


@owner_bp.route('/maintenance/<int:request_id>/status', methods=['POST'], endpoint='update_maintenance_status_owner')
@owner_required
def update_maintenance_status_owner(request_id):
    """Update maintenance request status from owner view"""
    maintenance = MaintenanceRequest.query.get_or_404(request_id)
    status = request.form.get('status')
    note = request.form.get('note', '').strip()
    valid_statuses = ['Pending', 'Assigned', 'In Progress', 'Completed']

    if status not in valid_statuses:
        flash('Invalid maintenance status selected.', 'warning')
        return redirect(url_for('owner.maintenance_detail', request_id=request_id))

    maintenance.status = status
    db.session.add(MaintenanceRequestHistory(
        maintenance_request_id=maintenance.id,
        updated_by_id=current_user.id,
        status=status,
        note=note or f'Status updated to {status}'
    ))
    db.session.commit()
    if maintenance.resident and maintenance.resident.user:
        notify_user(
            maintenance.resident.user_id,
            'Maintenance request updated',
            f'Your maintenance request "{maintenance.title}" is now {status}. {note or ""}'.strip(),
        )
        email_user(maintenance.resident.user, 'Maintenance status updated', f'Your maintenance request "{maintenance.title}" is now {status}.')

    flash('Maintenance status updated successfully.', 'success')
    return redirect(url_for('owner.maintenance_detail', request_id=request_id))

# ==================== REPORTS & ANALYTICS ====================
@owner_bp.route('/reports')
@owner_required
def reports():
    """View detailed reports and analytics"""
    
    # Monthly data for charts
    today = datetime.utcnow()
    six_months_ago = today - timedelta(days=180)
    
    # Complaints trend
    complaints_by_month = db.session.query(
        func.strftime('%Y-%m', Complaint.created_at).label('month'),
        func.count(Complaint.id).label('count')
    ).filter(Complaint.created_at >= six_months_ago).group_by('month').all()
    
    # Revenue trend
    revenue_by_month = db.session.query(
        func.strftime('%Y-%m', Payment.created_at).label('month'),
        func.sum(Payment.amount).label('total')
    ).filter(Payment.created_at >= six_months_ago).group_by('month').all()
    
    # Top complaint categories
    top_categories = db.session.query(
        ComplaintCategory.name,
        func.count(Complaint.id).label('count')
    ).join(Complaint).group_by(ComplaintCategory.id).order_by(desc('count')).limit(10).all()
    
    # Feedback summary
    avg_rating = db.session.query(func.avg(Feedback.rating)).scalar() or 0
    recent_feedback = Feedback.query.order_by(Feedback.created_at.desc()).limit(5).all()

    society_snapshot = {
        'total_residents': Resident.query.count(),
        'total_bills': Bill.query.count(),
        'pending_bills': Bill.query.filter_by(payment_status='Pending').count(),
        'collected_revenue': db.session.query(func.sum(Payment.amount)).filter_by(status='Paid').scalar() or 0,
        'total_visitors': Visitor.query.count(),
        'upcoming_events': Event.query.filter(
            Event.start_date >= today,
            Event.status == 'Active',
        ).count(),
    }
    
    return render_template('owner/reports.html',
        complaints_by_month=complaints_by_month,
        revenue_by_month=revenue_by_month,
        top_categories=top_categories,
        avg_rating=round(avg_rating, 2),
        recent_feedback=recent_feedback,
        society_snapshot=society_snapshot,
    )


@owner_bp.route('/reports/download')
@owner_required
def download_reports():
    snapshot = {
        'Total residents': Resident.query.count(),
        'Total bills': Bill.query.count(),
        'Pending bills': Bill.query.filter_by(payment_status='Pending').count(),
        'Collected revenue': f'Rs {db.session.query(func.sum(Payment.amount)).filter_by(status="Paid").scalar() or 0:,.2f}',
        'Total visitors': Visitor.query.count(),
        'Open complaints': Complaint.query.filter(Complaint.status != 'Resolved').count(),
        'Maintenance requests': MaintenanceRequest.query.count(),
    }
    pdf = build_pdf('Society Management Report', [('Society snapshot', list(snapshot.items()))])
    return preview_or_download(pdf, 'society-report.pdf', 'Society Management Report')


@owner_bp.route('/reports/bills')
@owner_required
def report_bills():
    status = request.args.get('status', 'all')
    bills_query = Bill.query
    if status == 'pending':
        bills_query = bills_query.filter(Bill.payment_status == 'Pending')
        heading = 'Pending bills'
    elif status == 'paid':
        bills_query = bills_query.filter(Bill.payment_status == 'Paid')
        heading = 'Collected bills'
    else:
        status = 'all'
        heading = 'All bills'

    bills = bills_query.order_by(Bill.due_date.desc()).all()
    return render_template('owner/report_bills.html', bills=bills, heading=heading, current_status=status)

# ==================== ACCOUNT MANAGEMENT ====================
@owner_bp.route('/account')
@owner_required
def account():
    """View and edit owner account"""
    return render_template('owner/account.html')

@owner_bp.route('/account/edit', methods=['POST'])
@owner_required
def edit_account():
    """Update owner account information"""
    first_name = _normalize_text(request.form.get('first_name'))
    last_name = _normalize_text(request.form.get('last_name'))
    email = _normalize_text(request.form.get('email'))
    phone = _normalize_text(request.form.get('phone'))

    if not first_name or not last_name:
        flash('First name and last name are required.', 'warning')
        return redirect(url_for('owner.account'))
    try:
        email = _validate_email(email)
        phone = _validate_phone(phone)
    except ValueError as exc:
        flash(str(exc), 'warning')
        return redirect(url_for('owner.account'))

    current_user.first_name = first_name
    current_user.last_name = last_name
    current_user.email = email
    current_user.phone = phone
    
    db.session.commit()
    flash('Account information updated successfully!', 'success')
    return redirect(url_for('owner.account'))

# ==================== API ENDPOINTS FOR AJAX ====================
@owner_bp.route('/api/dashboard-stats')
@owner_required
def api_dashboard_stats():
    """Get dashboard statistics as JSON"""
    stats = {
        'pending_residents': Resident.query.filter_by(approval_status='Pending').count(),
        'approved_residents': Resident.query.filter_by(approval_status='Approved').count(),
        'pending_complaints': Complaint.query.filter_by(status='Pending').count(),
        'pending_maintenance': MaintenanceRequest.query.filter_by(status='Pending').count(),
    }
    return jsonify(stats)
