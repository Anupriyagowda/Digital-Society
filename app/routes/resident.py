from datetime import date, datetime, time
import base64
from io import BytesIO

from flask import Blueprint, current_app, render_template, request, redirect, url_for, flash, send_file
from flask_login import login_required, current_user
import qrcode
from itsdangerous import URLSafeSerializer

from app import db
from app.notification_service import process_bill_reminders
from app.notification_service import email_admins, email_user, notify_admins, notify_user
from app.billing_service import generate_current_month_bills
from app.pdf_service import build_pdf, preview_or_download
from app.models import Amenity, AmenityBooking, Event, Participant, Activity, ActivityParticipant, Resident, Complaint, ComplaintMessage, MaintenanceRequest, MaintenanceRequestHistory, Bill, Payment, Notice, Feedback, Survey, SurveyResponse, Visitor, Memo, Notification, Role, User, FamilyMember, EmergencyContact, AuthorizedPerson

resident_bp = Blueprint('resident', __name__)


def _create_notification(user_id, title, message):
    if not user_id:
        return
    db.session.add(Notification(user_id=user_id, title=title, message=message))
    db.session.commit()


def _get_security_users():
    security_role = Role.query.filter_by(name='Security Guard').first()
    if not security_role:
        return []
    return User.query.filter_by(role_id=security_role.id).all()


def _get_current_resident():
    if not current_user.role or current_user.role.name != 'Resident':
        return None
    return Resident.query.filter_by(user_id=current_user.id).first()


@resident_bp.route('/household', methods=['GET', 'POST'])
@login_required
def household():
    resident = _get_current_resident()
    if not resident:
        flash('Only residents can manage household details.', 'warning')
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        record_type = request.form.get('record_type')
        name = request.form.get('name', '').strip()
        relationship = request.form.get('relationship', '').strip()
        phone = request.form.get('phone', '').strip() or None
        if not name or not relationship:
            flash('Name and relationship are required.', 'warning')
            return redirect(url_for('resident.household'))

        if record_type == 'family':
            record = FamilyMember(
                resident_id=resident.id, name=name, relationship=relationship,
                phone=phone, email=request.form.get('email', '').strip() or None,
                is_dependent=request.form.get('is_dependent') == 'on',
                notes=request.form.get('notes', '').strip() or None,
            )
        elif record_type == 'emergency':
            if not phone:
                flash('An emergency contact phone number is required.', 'warning')
                return redirect(url_for('resident.household'))
            record = EmergencyContact(
                resident_id=resident.id, name=name, relationship=relationship,
                phone=phone, priority=request.form.get('priority', 1, type=int),
            )
        elif record_type == 'authorized':
            record = AuthorizedPerson(
                resident_id=resident.id, name=name, relationship=relationship,
                phone=phone, vehicle_number=request.form.get('vehicle_number', '').strip() or None,
                valid_from=datetime.strptime(request.form['valid_from'], '%Y-%m-%d').date() if request.form.get('valid_from') else None,
                valid_until=datetime.strptime(request.form['valid_until'], '%Y-%m-%d').date() if request.form.get('valid_until') else None,
            )
        else:
            flash('Invalid household record type.', 'warning')
            return redirect(url_for('resident.household'))

        db.session.add(record)
        db.session.commit()
        flash('Household information saved.', 'success')
        return redirect(url_for('resident.household'))

    return render_template('resident/household.html', resident=resident)


@resident_bp.route('/household/<record_type>/<int:record_id>/delete', methods=['POST'])
@login_required
def delete_household_record(record_type, record_id):
    resident = _get_current_resident()
    record_map = {'family': FamilyMember, 'emergency': EmergencyContact, 'authorized': AuthorizedPerson}
    model = record_map.get(record_type)
    if not resident or not model:
        flash('Invalid household record.', 'warning')
        return redirect(url_for('resident.household'))
    record = model.query.filter_by(id=record_id, resident_id=resident.id).first_or_404()
    db.session.delete(record)
    db.session.commit()
    flash('Household record removed.', 'success')
    return redirect(url_for('resident.household'))


@resident_bp.route('/digital-pass')
@login_required
def digital_pass():
    resident = _get_current_resident()
    if not resident:
        flash('Only residents can access the digital pass.', 'warning')
        return redirect(url_for('main.dashboard'))

    pass_token = URLSafeSerializer(current_app.config['SECRET_KEY']).dumps({'resident_id': resident.id})
    verification_url = url_for('security.verify_digital_pass', token=pass_token, _external=True)
    qr_image = qrcode.make(verification_url)
    image_buffer = BytesIO()
    qr_image.save(image_buffer, format='PNG')
    qr_code = base64.b64encode(image_buffer.getvalue()).decode('ascii')
    return render_template('resident/digital_pass.html', resident=resident, qr_code=qr_code)


def _resident_name(resident):
    return f'{resident.user.first_name or resident.user.username} {resident.user.last_name or ""}'.strip()


def _digital_pass_qr_bytes(resident):
    pass_token = URLSafeSerializer(current_app.config['SECRET_KEY']).dumps({'resident_id': resident.id})
    verification_url = url_for('security.verify_digital_pass', token=pass_token, _external=True)
    qr_image = qrcode.make(verification_url)
    image_buffer = BytesIO()
    qr_image.save(image_buffer, format='PNG')
    return image_buffer.getvalue()


@resident_bp.route('/digital-pass/download')
@login_required
def download_digital_pass():
    resident = _get_current_resident()
    if not resident:
        return redirect(url_for('main.dashboard'))
    flat_number = resident.flat.number if resident.flat else 'Not assigned'
    society_name = resident.flat.building.name if resident.flat and resident.flat.building else current_app.config['SOCIETY_NAME']
    is_active = bool(resident.user.is_active and resident.status == 'Active' and resident.approval_status == 'Approved')
    pdf = build_pdf('Digital Society Pass', [('Resident details', [
        ('Name', _resident_name(resident)),
        ('Flat number', flat_number),
        ('Resident type', resident.resident_type),
        ('Society', society_name),
        ('Status', 'Active' if is_active else 'Inactive'),
    ])], qr_bytes=_digital_pass_qr_bytes(resident))
    return preview_or_download(pdf, 'digital-society-pass.pdf', 'Digital Society Pass')


@resident_bp.route('/bills/<int:bill_id>/download')
@login_required
def download_bill(bill_id):
    resident = _get_current_resident()
    bill = Bill.query.filter_by(id=bill_id, resident_id=resident.id if resident else None).first_or_404()
    pdf = build_pdf('Bill', [('Billing details', [
        ('Resident', bill.resident_name or _resident_name(resident)),
        ('Flat number', bill.flat_number or (resident.flat.number if resident.flat else 'Not assigned')),
        ('Bill type', bill.bill_type),
        ('Description', bill.description),
        ('Amount', f'Rs {bill.amount:,.2f}'),
        ('Payment date', bill.payment_date.strftime('%Y-%m-%d') if bill.payment_date else '-'),
        ('Payment status', bill.payment_status or bill.status),
    ])])
    return preview_or_download(pdf, f'bill-{bill.id}.pdf', 'Bill')


@resident_bp.route('/complaints/<int:complaint_id>/download')
@login_required
def download_complaint(complaint_id):
    resident = _get_current_resident()
    complaint = Complaint.query.filter_by(id=complaint_id, resident_id=resident.id if resident else None).first_or_404()
    rows = [('Title', complaint.title), ('Status', complaint.status), ('Priority', complaint.priority), ('Description', complaint.description)]
    for message in complaint.messages:
        sender = message.sender.first_name or message.sender.username
        rows.append((f'{sender} ({message.created_at.strftime("%Y-%m-%d %H:%M")})', message.message))
    pdf = build_pdf('Complaint Conversation', [('Complaint record', rows)])
    return preview_or_download(pdf, f'complaint-{complaint.id}.pdf', 'Complaint Conversation')


@resident_bp.route('/maintenance/<int:request_id>/download')
@login_required
def download_maintenance(request_id):
    resident = _get_current_resident()
    maintenance = MaintenanceRequest.query.filter_by(id=request_id, resident_id=resident.id if resident else None).first_or_404()
    rows = [('Title', maintenance.title), ('Description', maintenance.description), ('Status', maintenance.status), ('Priority', maintenance.priority)]
    for history in maintenance.histories:
        rows.append((f'{history.status} ({history.created_at.strftime("%Y-%m-%d %H:%M")})', history.note))
    pdf = build_pdf('Maintenance Request', [('Request history', rows)])
    return preview_or_download(pdf, f'maintenance-{maintenance.id}.pdf', 'Maintenance Request')


@resident_bp.route('/visitors/<int:visitor_id>/download')
@login_required
def download_visitor(visitor_id):
    resident = _get_current_resident()
    visitor = Visitor.query.filter_by(id=visitor_id, resident_id=resident.id if resident else None).first_or_404()
    pdf = build_pdf('Visitor Pass', [('Visitor details', [
        ('Visitor name', visitor.full_name),
        ('Phone', visitor.phone),
        ('Purpose', visitor.purpose),
        ('Flat number', visitor.flat_number),
        ('Entry time', visitor.entry_time.strftime('%Y-%m-%d %H:%M') if visitor.entry_time else '-'),
        ('Status', visitor.status),
    ])])
    return preview_or_download(pdf, f'visitor-{visitor.id}.pdf', 'Visitor Pass')


def _get_allowed_bill_type(resident):
    if getattr(resident, 'resident_type', None) == 'Tenant':
        return 'Monthly Rent'
    if getattr(resident, 'resident_type', None) == 'Flat Owner':
        return 'Maintenance Charges'
    return None


@resident_bp.route('/')
@login_required
def index():
    resident = Resident.query.filter_by(user_id=current_user.id).first()
    events = Event.query.filter(Event.start_date >= datetime.utcnow(), Event.status == 'Active').order_by(Event.start_date.asc()).limit(5).all()
    activities = Activity.query.filter(Activity.status == 'Active').order_by(Activity.created_at.desc()).limit(5).all()
    notices = Notice.query.order_by(Notice.created_at.desc()).limit(5).all()
    registrations = set()
    activity_registrations = set()
    if resident:
        registrations = {participant.event_id for participant in Participant.query.filter_by(resident_id=resident.id).all()}
        activity_registrations = {participant.activity_id for participant in ActivityParticipant.query.filter_by(resident_id=resident.id).all()}
    return render_template('resident/index.html', resident=resident, events=events, registrations=registrations, activities=activities, activity_registrations=activity_registrations, notices=notices)


@resident_bp.route('/amenities', methods=['GET', 'POST'])
@login_required
def amenities():
    resident = _get_current_resident()
    if not resident:
        flash('Only residents can book amenities.', 'warning')
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        amenity = Amenity.query.filter_by(id=request.form.get('amenity_id', type=int), is_active=True).first()
        try:
            booking_date = datetime.strptime(request.form.get('booking_date', ''), '%Y-%m-%d').date()
            start_time = time.fromisoformat(request.form.get('start_time', ''))
            end_time = time.fromisoformat(request.form.get('end_time', ''))
        except ValueError:
            amenity = amenity or Amenity.query.get(request.form.get('amenity_id', type=int))
            flash('Enter a valid booking date and time.', 'warning')
            return redirect(url_for('resident.amenities'))

        if not amenity:
            flash('That amenity is not available.', 'warning')
        elif booking_date < date.today() or start_time >= end_time:
            flash('Choose a future date and a valid time range.', 'warning')
        elif amenity.opening_time and (start_time < amenity.opening_time or end_time > amenity.closing_time):
            flash('The selected time is outside the amenity operating hours.', 'warning')
        else:
            conflict = AmenityBooking.query.filter(
                AmenityBooking.amenity_id == amenity.id,
                AmenityBooking.booking_date == booking_date,
                AmenityBooking.status.in_(['Pending', 'Approved']),
                AmenityBooking.start_time < end_time,
                AmenityBooking.end_time > start_time,
            ).first()
            if conflict:
                flash('That time slot is already requested or booked.', 'warning')
            else:
                db.session.add(AmenityBooking(
                    amenity_id=amenity.id,
                    resident_id=resident.id,
                    booking_date=booking_date,
                    start_time=start_time,
                    end_time=end_time,
                    purpose=(request.form.get('purpose') or '').strip() or None,
                ))
                schedule = f'{booking_date.strftime("%d %b %Y")} from {start_time.strftime("%H:%M")} to {end_time.strftime("%H:%M")}'
                notify_admins('New amenity booking request', f'{current_user.first_name or current_user.username} requested {amenity.name} on {schedule}.')
                db.session.commit()
                email_user(
                    current_user,
                    'Amenity booking request received',
                    f'Hello {current_user.first_name or current_user.username},\n\n'
                    f'Your request for {amenity.name} on {schedule} was submitted and is pending administrator approval.\n\n'
                    'Digital Society',
                )
                flash('Booking request submitted for administrator approval.', 'success')
                return redirect(url_for('resident.amenities'))

    amenities_list = Amenity.query.filter_by(is_active=True).order_by(Amenity.name.asc()).all()
    bookings = AmenityBooking.query.filter_by(resident_id=resident.id).order_by(AmenityBooking.booking_date.desc(), AmenityBooking.start_time.desc()).all()
    return render_template('resident/amenities.html', amenities=amenities_list, bookings=bookings, today=date.today().isoformat())


@resident_bp.route('/amenity-bookings/<int:booking_id>/cancel', methods=['POST'])
@login_required
def cancel_amenity_booking(booking_id):
    resident = _get_current_resident()
    booking = AmenityBooking.query.filter_by(id=booking_id, resident_id=resident.id if resident else None).first_or_404()
    if booking.status in {'Pending', 'Approved'}:
        booking.status = 'Cancelled'
        schedule = f'{booking.booking_date.strftime("%d %b %Y")} from {booking.start_time.strftime("%H:%M")} to {booking.end_time.strftime("%H:%M")}'
        notify_admins('Amenity booking cancelled', f'{current_user.first_name or current_user.username} cancelled {booking.amenity.name} on {schedule}.')
        db.session.commit()
        flash('Booking cancelled.', 'success')
    return redirect(url_for('resident.amenities'))


@resident_bp.route('/activities')
@login_required
def activities():
    resident = Resident.query.filter_by(user_id=current_user.id).first()
    registrations = set()
    if resident:
        registrations = {participant.activity_id for participant in ActivityParticipant.query.filter_by(resident_id=resident.id).all()}
    activities = Activity.query.order_by(Activity.created_at.desc()).all()
    return render_template('resident/activities.html', resident=resident, activities=activities, registrations=registrations)


@resident_bp.route('/activity/<int:activity_id>')
@login_required
def activity_detail(activity_id):
    activity = Activity.query.get_or_404(activity_id)
    resident = Resident.query.filter_by(user_id=current_user.id).first()
    registered = False
    if resident:
        registered = ActivityParticipant.query.filter_by(activity_id=activity.id, resident_id=resident.id).first() is not None
    registrations = ActivityParticipant.query.filter_by(activity_id=activity.id).count()
    return render_template('resident/activity_detail.html', activity=activity, registered=registered, resident=resident, registrations=registrations)


@resident_bp.route('/activity/<int:activity_id>/register', methods=['POST'])
@login_required
def register_activity(activity_id):
    activity = Activity.query.get_or_404(activity_id)
    if not current_user.role or current_user.role.name != 'Resident':
        flash('Only residents can register for activities.', 'warning')
        return redirect(url_for('resident.activity_detail', activity_id=activity.id))
    resident = Resident.query.filter_by(user_id=current_user.id).first()
    if not resident:
        resident = Resident(user_id=current_user.id, emergency_contact='', resident_type='Tenant', approval_status='Approved', status='Active')
        db.session.add(resident)
        db.session.flush()

    if ActivityParticipant.query.filter_by(activity_id=activity.id, resident_id=resident.id).first():
        flash('Already Registered', 'info')
        return redirect(url_for('resident.activity_detail', activity_id=activity.id))

    participant_count = ActivityParticipant.query.filter_by(activity_id=activity.id).count()
    if participant_count >= activity.max_participants:
        flash('First registered participants will get the chance. Activity limit reached.', 'warning')
        return redirect(url_for('resident.activity_detail', activity_id=activity.id))

    participant = ActivityParticipant(activity_id=activity.id, resident_id=resident.id)
    db.session.add(participant)
    db.session.commit()
    if activity.created_by_id != current_user.id:
        notify_user(
            activity.created_by_id,
            'New activity registration',
            f'{current_user.first_name or current_user.username} registered for "{activity.title}".',
        )
    flash('Registration Successful', 'success')
    return redirect(url_for('resident.activity_detail', activity_id=activity.id))


@resident_bp.route('/complaints', methods=['GET', 'POST'])
@login_required
def complaints():
    resident = _get_current_resident()
    if not resident:
        flash('Only residents can submit complaints. Please login with a resident account.', 'warning')
        return redirect(url_for('auth.login', role='resident'))

    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        description = (request.form.get('description') or '').strip()
        category_id = request.form.get('category_id') or None

        if not title or not description:
            flash('Title and description are required.', 'warning')
            return redirect(url_for('resident.complaints'))

        complaint = Complaint(
            title=title,
            description=description,
            category_id=category_id,
            resident_id=resident.id,
            status='Pending',
            priority='Medium',
        )
        db.session.add(complaint)
        db.session.commit()
        notify_admins(
            'New complaint submitted',
            f'{current_user.first_name or current_user.username} submitted a complaint: {title}\n\n{description}',
            target_urls={
                'Super Admin': url_for('admin.view_complaint', complaint_id=complaint.id),
                'Society Admin': url_for('admin.view_complaint', complaint_id=complaint.id),
                'Owner': url_for('owner.complaint_detail', complaint_id=complaint.id),
            },
        )
        email_admins(
            'New complaint submitted',
            f'{current_user.first_name or current_user.username} submitted a complaint: {title}\n\n{description}',
        )
        flash('Complaint submitted', 'success')
        return redirect(url_for('resident.complaints'))

    complaints = Complaint.query.filter_by(resident_id=resident.id).all()
    return render_template('resident/complaints.html', complaints=complaints)


@resident_bp.route('/complaints/<int:complaint_id>', methods=['GET', 'POST'])
@login_required
def complaint_detail(complaint_id):
    resident = _get_current_resident()
    if not resident:
        flash('Only residents can view complaints.', 'warning')
        return redirect(url_for('auth.login', role='resident'))

    complaint = Complaint.query.filter_by(id=complaint_id, resident_id=resident.id).first_or_404()
    if request.method == 'POST':
        message = (request.form.get('message') or '').strip()
        if not message:
            flash('Message cannot be empty.', 'warning')
            return redirect(url_for('resident.complaint_detail', complaint_id=complaint.id))
        db.session.add(ComplaintMessage(complaint_id=complaint.id, sender_id=current_user.id, message=message))
        db.session.commit()
        notify_admins(
            'New complaint reply',
            f'{current_user.first_name or current_user.username} replied to complaint "{complaint.title}":\n\n{message}',
            target_urls={
                'Super Admin': url_for('admin.view_complaint', complaint_id=complaint.id),
                'Society Admin': url_for('admin.view_complaint', complaint_id=complaint.id),
                'Owner': url_for('owner.complaint_detail', complaint_id=complaint.id),
            },
        )
        email_admins('New complaint reply', f'{current_user.first_name or current_user.username} replied to complaint "{complaint.title}":\n\n{message}')
        flash('Reply sent.', 'success')
        return redirect(url_for('resident.complaint_detail', complaint_id=complaint.id))

    return render_template('resident/complaint_detail.html', complaint=complaint)


@resident_bp.route('/maintenance', methods=['GET', 'POST'])
@login_required
def maintenance():
    resident = _get_current_resident()
    if not resident:
        flash('Only residents can request maintenance. Please login with a resident account.', 'warning')
        return redirect(url_for('auth.login', role='resident'))

    if request.method == 'POST':
        req = MaintenanceRequest(title=request.form.get('title'), description=request.form.get('description'), resident_id=resident.id)
        db.session.add(req)
        db.session.flush()
        db.session.add(MaintenanceRequestHistory(
            maintenance_request_id=req.id,
            updated_by_id=current_user.id,
            status='Pending',
            note='Maintenance request submitted by resident.'
        ))
        db.session.commit()
        notify_admins(
            'New maintenance request',
            f'{current_user.first_name or current_user.username} submitted a maintenance request: {req.title}.',
        )
        email_admins('New maintenance request', f'{current_user.first_name or current_user.username} submitted a maintenance request: {req.title}\n\n{req.description}')
        flash('Maintenance request submitted', 'success')
        return redirect(url_for('resident.maintenance'))

    requests = MaintenanceRequest.query.filter_by(resident_id=resident.id).all()
    return render_template('resident/maintenance.html', requests=requests)


@resident_bp.route('/bills')
@login_required
def bills():
    resident = _get_current_resident()
    if not resident:
        flash('Only residents can view bills. Please login with a resident account.', 'warning')
        return redirect(url_for('auth.login', role='resident'))
    return redirect(url_for('billing.index'))


@resident_bp.route('/visitors')
@login_required
def visitors():
    resident = _get_current_resident()
    if not resident:
        flash('Only residents can view visitor requests. Please login with a resident account.', 'warning')
        return redirect(url_for('auth.login', role='resident'))

    visitors = Visitor.query.filter_by(resident_id=resident.id).order_by(Visitor.created_at.desc()).all()
    return render_template('resident/visitors.html', visitors=visitors)


@resident_bp.route('/visitors/<int:visitor_id>/approve', methods=['POST'])
@login_required
def approve_visitor(visitor_id):
    resident = Resident.query.filter_by(user_id=current_user.id).first()
    if not resident:
        flash('Please complete your resident profile before managing visitor requests.', 'warning')
        return redirect(url_for('resident.visitors'))

    visitor = Visitor.query.filter_by(id=visitor_id, resident_id=resident.id).first_or_404()
    visitor.status = 'Approved'
    _create_notification(
        resident.user_id,
        'Visitor approved',
        f'Visitor {visitor.full_name} was approved for your flat.',
    )
    for security_user in _get_security_users():
        _create_notification(security_user.id, 'Visitor approved', f'Visitor {visitor.full_name} has been approved for flat {visitor.flat_number or resident.flat.number if resident.flat else "your flat"}.')
    db.session.commit()
    email_user(resident.user, 'Visitor approved', f'Visitor {visitor.full_name} was approved for your flat.')
    email_admins('Visitor approved', f'Visitor {visitor.full_name} was approved for flat {visitor.flat_number or "your flat"}.')
    flash('Visitor request approved.', 'success')
    return redirect(url_for('resident.visitors'))


@resident_bp.route('/visitors/<int:visitor_id>/reject', methods=['POST'])
@login_required
def reject_visitor(visitor_id):
    resident = Resident.query.filter_by(user_id=current_user.id).first()
    if not resident:
        flash('Please complete your resident profile before managing visitor requests.', 'warning')
        return redirect(url_for('resident.visitors'))

    visitor = Visitor.query.filter_by(id=visitor_id, resident_id=resident.id).first_or_404()
    visitor.status = 'Rejected'
    for security_user in _get_security_users():
        _create_notification(security_user.id, 'Visitor request rejected', f'Visitor {visitor.full_name} was rejected for flat {visitor.flat_number or resident.flat.number if resident.flat else "your flat"}.')
    db.session.commit()
    email_admins('Visitor request rejected', f'Visitor {visitor.full_name} was rejected for flat {visitor.flat_number or "your flat"}.')
    flash('Visitor request rejected. Security has been notified.', 'warning')
    return redirect(url_for('resident.visitors'))


@resident_bp.route('/memos', methods=['GET', 'POST'])
@login_required
def memos():
    resident = _get_current_resident()
    if not resident:
        flash('Only residents can use memos. Please login with a resident account.', 'warning')
        return redirect(url_for('auth.login', role='resident'))

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        if not title or not content:
            flash('Please provide both a title and message for the memo.', 'warning')
            return redirect(url_for('resident.memos'))
        memo = Memo(resident_id=resident.id, title=title, content=content, status='Pending')
        db.session.add(memo)
        db.session.flush()
        for security_user in _get_security_users():
            _create_notification(security_user.id, 'New resident memo', f'{resident.user.first_name or resident.user.username} shared a memo: {title}')
        db.session.commit()
        flash('Memo sent to security.', 'success')
        return redirect(url_for('resident.memos'))

    memos = Memo.query.filter_by(resident_id=resident.id).order_by(Memo.created_at.desc()).all()
    return render_template('resident/memos.html', memos=memos)


@resident_bp.route('/maintenance/<int:request_id>')
@login_required
def maintenance_detail(request_id):
    resident = _get_current_resident()
    if not resident:
        flash('Only residents can view maintenance requests. Please login with a resident account.', 'warning')
        return redirect(url_for('auth.login', role='resident'))

    maintenance = MaintenanceRequest.query.filter_by(id=request_id, resident_id=resident.id).first_or_404()
    return render_template('resident/maintenance_detail.html', maintenance=maintenance)
