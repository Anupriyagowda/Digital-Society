import re
from pathlib import Path

from flask import Blueprint, current_app, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user, logout_user
from werkzeug.utils import secure_filename

from app import db
from app.models import Resident, Complaint, MaintenanceRequest, Bill, Payment, Visitor, Notice, Event, Feedback, SurveyResponse, User, Setting


def _get_login_background_url():
    setting = Setting.query.filter_by(key='login_background_image').first()
    if setting and setting.value:
        return url_for('static', filename=setting.value)
    return None

main_bp = Blueprint('main', __name__)


def _normalize_text(value):
    return (value or '').strip()


def _validate_email(email):
    pattern = r'^[^\s@]+@[^\s@]+\.[^\s@]+$'
    if not re.match(pattern, email):
        raise ValueError('Please enter a valid email address.')
    return email.lower()


def _validate_phone(phone):
    if not re.fullmatch(r'\d{10}', phone):
        raise ValueError('Please enter a 10-digit phone number.')
    return phone


@main_bp.route('/')
def index():
    return render_template('index.html', background_image=_get_login_background_url())


@main_bp.route('/account')
@login_required
def account():
    return render_template('account.html')


@main_bp.route('/account/edit', methods=['POST'])
@login_required
def edit_account():
    first_name = _normalize_text(request.form.get('first_name'))
    last_name = _normalize_text(request.form.get('last_name'))
    email = _normalize_text(request.form.get('email'))
    phone = _normalize_text(request.form.get('phone'))

    if not first_name:
        flash('First name is required.', 'warning')
        return redirect(url_for('main.account'))

    try:
        email = _validate_email(email)
        phone = _validate_phone(phone) if phone else ''
    except ValueError as exc:
        flash(str(exc), 'warning')
        return redirect(url_for('main.account'))

    if User.query.filter(User.email == email, User.id != current_user.id).first():
        flash('A different account already uses that email address.', 'warning')
        return redirect(url_for('main.account'))

    current_user.first_name = first_name
    current_user.last_name = last_name
    current_user.email = email
    current_user.phone = phone
    db.session.commit()
    flash('Profile updated successfully.', 'success')
    return redirect(url_for('main.account'))


@main_bp.route('/account/avatar', methods=['POST'])
@login_required
def upload_avatar():
    image = request.files.get('profile_picture')
    allowed_extensions = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
    filename = secure_filename(image.filename) if image else ''
    extension = Path(filename).suffix.lower().lstrip('.')

    if not image or not filename:
        flash('Please choose an image to upload.', 'warning')
        return redirect(url_for('main.account'))
    if extension not in allowed_extensions:
        flash('Please upload a JPG, JPEG, PNG, GIF, or WEBP image.', 'warning')
        return redirect(url_for('main.account'))

    upload_dir = Path(current_app.root_path) / 'static' / 'uploads' / 'profiles'
    upload_dir.mkdir(parents=True, exist_ok=True)
    final_name = f'profile-{current_user.id}.{extension}'
    image.save(upload_dir / final_name)
    current_user.avatar_url = f'uploads/profiles/{final_name}'
    db.session.commit()
    flash('Profile picture updated successfully.', 'success')
    return redirect(url_for('main.account'))


@main_bp.route('/dashboard')
@login_required
def dashboard():
    if current_user.role and current_user.role.name in {'Super Admin', 'Society Admin'}:
        return redirect(url_for('admin.dashboard'))
    if current_user.role and current_user.role.name == 'Owner':
        return redirect(url_for('owner.dashboard'))
    if current_user.role and current_user.role.name == 'Resident':
        return redirect(url_for('resident.index'))
    if current_user.role and current_user.role.name in {'Security Guard'}:
        return redirect(url_for('security.index'))
    if current_user.role and current_user.role.name in {'Maintenance Staff'}:
        return redirect(url_for('maintenance.index'))

    resident_count = Resident.query.count()
    pending_complaints = Complaint.query.filter_by(status='Pending').count()
    solved_complaints = Complaint.query.filter_by(status='Resolved').count()
    today_visitors = Visitor.query.count()
    maintenance_requests = MaintenanceRequest.query.count()
    pending_payments = Bill.query.filter_by(status='Pending').count()
    collected_revenue = sum(p.amount for p in Payment.query.all())
    notices = Notice.query.order_by(Notice.created_at.desc()).limit(5).all()
    events = Event.query.order_by(Event.start_date.asc()).limit(5).all()
    surveys = SurveyResponse.query.count()
    feedback = Feedback.query.count()

    return render_template('dashboard.html', resident_count=resident_count, pending_complaints=pending_complaints, solved_complaints=solved_complaints, today_visitors=today_visitors, maintenance_requests=maintenance_requests, pending_payments=pending_payments, collected_revenue=collected_revenue, notices=notices, events=events, surveys=surveys, feedback=feedback)
