from datetime import datetime, time
from pathlib import Path
from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload
from werkzeug.utils import secure_filename

from app import db
from app.mail_service import send_app_email
from app.billing_service import get_billing_schedule
from app.notification_service import email_user, notify_residents, notify_user
from app.models import Amenity, AmenityBooking, Bill, Building, Complaint, ComplaintMessage, Event, Feedback, Flat, Notice, Payment, Resident, Survey, SurveyResponse, User, Visitor, Setting, FamilyMember, EmergencyContact, AuthorizedPerson

admin_bp = Blueprint('admin', __name__)


@admin_bp.before_request
def ensure_admin_login_for_unauthenticated():
    # If the user is not authenticated, redirect to dedicated admin login
    from flask import request
    if not current_user.is_authenticated:
        # Allow access to static assets
        if request.endpoint and request.endpoint.startswith('static'):
            return None
        return redirect(url_for('auth.admin_login'))


def _require_admin_access(allowed_roles=None):
    if not current_user.is_authenticated:
        return redirect(url_for('auth.admin_login'))

    if not current_user.role:
        flash('You do not have access to the admin section.', 'warning')
        return redirect(url_for('auth.admin_login'))

    allowed = allowed_roles or {'Super Admin', 'Society Admin'}
    if current_user.role.name not in allowed:
        flash('You do not have access to the admin section.', 'warning')
        return redirect(url_for('auth.admin_login'))

    return None


def _get_login_background_url():
    setting = Setting.query.filter_by(key='login_background_image').first()
    if setting and setting.value:
        return url_for('static', filename=setting.value)
    return None


@admin_bp.route('/')
@admin_bp.route('/dashboard')
@login_required
def dashboard():
    access_check = _require_admin_access()
    if access_check is not None:
        return access_check
    return render_template('admin/index.html', background_image=_get_login_background_url())


@admin_bp.route('/amenities', methods=['GET', 'POST'])
@login_required
def amenities():
    access_check = _require_admin_access({'Super Admin', 'Society Admin', 'Owner'})
    if access_check is not None:
        return access_check

    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        if not name:
            flash('Amenity name is required.', 'warning')
            return redirect(url_for('admin.amenities'))
        try:
            opening_time = time.fromisoformat(request.form.get('opening_time')) if request.form.get('opening_time') else None
            closing_time = time.fromisoformat(request.form.get('closing_time')) if request.form.get('closing_time') else None
            capacity = request.form.get('capacity', 1, type=int)
            if capacity < 1 or (opening_time is None) != (closing_time is None) or (opening_time and closing_time and opening_time >= closing_time):
                raise ValueError
        except ValueError:
            flash('Enter a valid capacity and operating time range.', 'warning')
            return redirect(url_for('admin.amenities'))
        db.session.add(Amenity(
            name=name,
            description=(request.form.get('description') or '').strip() or None,
            location=(request.form.get('location') or '').strip() or None,
            capacity=capacity,
            opening_time=opening_time,
            closing_time=closing_time,
            created_by_id=current_user.id,
        ))
        db.session.commit()
        flash('Amenity created.', 'success')
        return redirect(url_for('admin.amenities'))

    amenities_list = Amenity.query.order_by(Amenity.name.asc()).all()
    bookings = AmenityBooking.query.order_by(AmenityBooking.booking_date.desc(), AmenityBooking.start_time.desc()).all()
    return render_template('admin/amenities.html', amenities=amenities_list, bookings=bookings)


@admin_bp.route('/amenities/<int:amenity_id>/toggle', methods=['POST'])
@login_required
def toggle_amenity(amenity_id):
    access_check = _require_admin_access({'Super Admin', 'Society Admin', 'Owner'})
    if access_check is not None:
        return access_check
    amenity = Amenity.query.get_or_404(amenity_id)
    amenity.is_active = not amenity.is_active
    db.session.commit()
    flash(f'{amenity.name} is now {"available" if amenity.is_active else "unavailable"}.', 'success')
    return redirect(url_for('admin.amenities'))


@admin_bp.route('/amenity-bookings/<int:booking_id>/status', methods=['POST'])
@login_required
def update_amenity_booking_status(booking_id):
    access_check = _require_admin_access({'Super Admin', 'Society Admin', 'Owner'})
    if access_check is not None:
        return access_check
    booking = AmenityBooking.query.get_or_404(booking_id)
    status = request.form.get('status')
    if status not in {'Approved', 'Rejected', 'Cancelled'}:
        flash('Invalid booking status.', 'warning')
        return redirect(url_for('admin.amenities'))
    if status == 'Approved':
        conflict = AmenityBooking.query.filter(
            AmenityBooking.id != booking.id,
            AmenityBooking.amenity_id == booking.amenity_id,
            AmenityBooking.booking_date == booking.booking_date,
            AmenityBooking.status == 'Approved',
            AmenityBooking.start_time < booking.end_time,
            AmenityBooking.end_time > booking.start_time,
        ).first()
        if conflict:
            flash('This slot overlaps an existing approved booking.', 'warning')
            return redirect(url_for('admin.amenities'))
    booking.status = status
    booking.reviewed_by_id = current_user.id
    booking.reviewed_at = datetime.utcnow()
    schedule = f'{booking.booking_date.strftime("%d %b %Y")} from {booking.start_time.strftime("%H:%M")} to {booking.end_time.strftime("%H:%M")}'
    if status in {'Approved', 'Rejected'}:
        result = status.lower()
        message = f'Your request for {booking.amenity.name} on {schedule} was {result} by the society administrator.'
        notify_user(booking.resident.user_id, f'Amenity booking {result}', message)
        email_user(
            booking.resident.user,
            f'Amenity booking {result}: {booking.amenity.name}',
            f'Hello {booking.resident.user.first_name or booking.resident.user.username},\n\n{message}\n\nDigital Society',
            f'<p>Hello {booking.resident.user.first_name or booking.resident.user.username},</p><p>{message}</p><p>Digital Society</p>',
        )
    db.session.commit()
    flash(f'Booking {status.lower()}.', 'success')
    return redirect(url_for('admin.amenities'))


@admin_bp.route('/residents', methods=['GET', 'POST'])
@login_required
def residents():
    access_check = _require_admin_access({'Super Admin', 'Society Admin', 'Owner'})
    if access_check is not None:
        return access_check
    if request.method == 'POST':
        try:
            generation_day = request.form.get('generation_day', type=int)
            due_day = request.form.get('due_day', type=int)
            generation_time = time.fromisoformat((request.form.get('generation_time') or '').strip())
            if not generation_day or not 1 <= generation_day <= 28 or not due_day or not 1 <= due_day <= 28:
                raise ValueError
        except (TypeError, ValueError):
            flash('Choose valid days from 1 to 28 and a valid generation time.', 'warning')
            return redirect(url_for('admin.residents'))

        values = {
            'auto_bill_generation_day': str(generation_day),
            'auto_bill_generation_time': generation_time.strftime('%H:%M'),
            'auto_bill_due_day': str(due_day),
        }
        for key, value in values.items():
            setting = Setting.query.filter_by(key=key).first()
            if setting:
                setting.value = value
            else:
                db.session.add(Setting(key=key, value=value))
        db.session.commit()
        flash('Automatic billing schedule saved.', 'success')
        return redirect(url_for('admin.residents'))

    residents = Resident.query.all()
    generation_day, generation_time, due_day = get_billing_schedule()
    return render_template(
        'admin/residents.html',
        residents=residents,
        billing_generation_day=generation_day,
        billing_generation_time=generation_time.strftime('%H:%M'),
        billing_due_day=due_day,
    )


@admin_bp.route('/residents/<int:resident_id>/household')
@login_required
def resident_household(resident_id):
    access_check = _require_admin_access({'Super Admin', 'Society Admin', 'Owner'})
    if access_check is not None:
        return access_check
    resident = Resident.query.get_or_404(resident_id)
    return render_template(
        'admin/resident_household.html',
        resident=resident,
        family_members=FamilyMember.query.filter_by(resident_id=resident.id).all(),
        emergency_contacts=EmergencyContact.query.filter_by(resident_id=resident.id).order_by(EmergencyContact.priority).all(),
        authorized_people=AuthorizedPerson.query.filter_by(resident_id=resident.id).all(),
    )


@admin_bp.route('/residents/<int:resident_id>/approve', methods=['POST'])
@login_required
def approve_resident(resident_id):
    # Society administrators and owners can approve residents.
    if not current_user.role or current_user.role.name not in {'Owner', 'Society Admin', 'Super Admin'}:
        flash('Only society administrators can approve users.', 'danger')
        return redirect(url_for('admin.residents'))
    resident = Resident.query.get_or_404(resident_id)
    user = resident.user
    user.is_approved = True
    resident.approval_status = 'Approved'
    resident.status = 'Active'
    resident.approved_by_id = current_user.id
    resident.approval_date = datetime.utcnow()
    db.session.commit()
    send_app_email(
        user.email,
        'Digital Society registration approved',
        f'Hello {user.first_name}, your society registration has been approved. You can now log in to the resident portal.',
        f'<p>Hello {user.first_name},</p><p>Your society registration has been approved. You can now log in to the resident portal.</p>',
    )
    flash(f'User {user.email} approved.', 'success')
    return redirect(url_for('admin.residents'))


@admin_bp.route('/residents/<int:resident_id>/reject', methods=['POST'])
@login_required
def reject_resident(resident_id):
    # Only Owners may reject/unapprove residents
    if not current_user.role or current_user.role.name != 'Owner':
        flash('Only owners can reject/unapprove users.', 'danger')
        return redirect(url_for('admin.residents'))
    resident = Resident.query.get_or_404(resident_id)
    user = resident.user
    user.is_approved = False
    db.session.commit()
    flash(f'User {user.email} rejected.', 'info')
    return redirect(url_for('admin.residents'))


@admin_bp.route('/notices', methods=['GET', 'POST'])
@login_required
def notices():
    access_check = _require_admin_access()
    if access_check is not None:
        return access_check
    if request.method == 'POST':
        title = request.form.get('title')
        content = request.form.get('content')
        notice_type = request.form.get('notice_type')
        is_pinned = request.form.get('is_pinned') == 'on'
        notice = Notice(title=title, content=content, notice_type=notice_type, is_pinned=is_pinned, created_by_id=current_user.id)
        db.session.add(notice)
        db.session.commit()
        notify_residents('New society notice', f'{title} has been posted. Open Notices to read it.')
        flash('Notice created successfully', 'success')
        return redirect(url_for('admin.notices'))
    notices = Notice.query.order_by(Notice.created_at.desc()).all()
    return render_template('admin/notices.html', notices=notices)


@admin_bp.route('/complaints')
@login_required
def complaints():
    access_check = _require_admin_access()
    if access_check is not None:
        return access_check
    complaints = Complaint.query.order_by(Complaint.created_at.desc()).all()
    return render_template('admin/complaints.html', complaints=complaints)


@admin_bp.route('/complaints/<int:complaint_id>')
@login_required
def view_complaint(complaint_id):
    access_check = _require_admin_access()
    if access_check is not None:
        return access_check
    complaint = Complaint.query.options(
        joinedload(Complaint.category),
        joinedload(Complaint.resident).joinedload(Resident.user)
    ).get_or_404(complaint_id)
    return render_template('admin/complaint_detail.html', complaint=complaint)


@admin_bp.route('/complaints/<int:complaint_id>/messages', methods=['POST'])
@login_required
def reply_to_complaint(complaint_id):
    access_check = _require_admin_access()
    if access_check is not None:
        return access_check
    complaint = Complaint.query.get_or_404(complaint_id)
    message = (request.form.get('message') or '').strip()
    if not message:
        flash('Reply cannot be empty.', 'warning')
        return redirect(url_for('admin.view_complaint', complaint_id=complaint.id))
    db.session.add(ComplaintMessage(complaint_id=complaint.id, sender_id=current_user.id, message=message))
    db.session.commit()
    notify_user(
        complaint.resident.user_id,
        'New complaint reply',
        f'An administrator replied to your complaint "{complaint.title}".',
        url_for('resident.complaint_detail', complaint_id=complaint.id),
    )
    flash('Reply sent.', 'success')
    return redirect(url_for('admin.view_complaint', complaint_id=complaint.id))


@admin_bp.route('/complaints/<int:complaint_id>/status', methods=['POST'])
@login_required
def update_complaint_status(complaint_id):
    access_check = _require_admin_access()
    if access_check is not None:
        return access_check
    complaint = Complaint.query.get_or_404(complaint_id)
    action = request.form.get('action')
    if action == 'resolved':
        complaint.status = 'Resolved'
        flash('Complaint marked as resolved.', 'success')
    elif action == 'processing':
        complaint.status = 'Processing'
        flash('Complaint marked as processing.', 'info')
    else:
        flash('Unknown action.', 'warning')
    db.session.commit()
    if action in {'resolved', 'processing'}:
        notify_user(
            complaint.resident.user_id,
            'Complaint status changed',
            f'Your complaint "{complaint.title}" is now {complaint.status}.',
            url_for('resident.complaint_detail', complaint_id=complaint.id),
        )
    return redirect(url_for('admin.complaints'))


@admin_bp.route('/settings/login-background', methods=['POST'])
@login_required
def update_login_background():
    access_check = _require_admin_access()
    if access_check is not None:
        return access_check
    action = request.form.get('action')
    if action == 'reset':
        setting = Setting.query.filter_by(key='login_background_image').first()
        if setting:
            db.session.delete(setting)
            db.session.commit()
        flash('Login background reset to default.', 'info')
        return redirect(url_for('admin.dashboard'))

    file = request.files.get('background_image')
    if not file or file.filename == '':
        flash('Please choose an image to upload.', 'warning')
        return redirect(url_for('admin.dashboard'))

    filename = secure_filename(file.filename)
    if not filename:
        flash('The selected file name was invalid.', 'warning')
        return redirect(url_for('admin.dashboard'))

    upload_dir = Path(current_app.root_path) / 'static' / 'uploads' / 'login'
    upload_dir.mkdir(parents=True, exist_ok=True)

    stem = Path(filename).stem or 'login-background'
    suffix = Path(filename).suffix.lower() or '.png'
    final_name = f'{stem}-{current_user.id}{suffix}'
    file_path = upload_dir / final_name
    file.save(file_path)

    relative_path = f'uploads/login/{final_name}'
    setting = Setting.query.filter_by(key='login_background_image').first()
    if not setting:
        setting = Setting(key='login_background_image', value=relative_path)
        db.session.add(setting)
    else:
        setting.value = relative_path

    db.session.commit()
    flash('Login background updated successfully.', 'success')
    return redirect(url_for('admin.dashboard'))
