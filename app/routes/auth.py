import re
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from flask import Blueprint, current_app, redirect, render_template, request, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash

from app import db
from app.mail_service import send_app_email
from app.models import AuditLog, Building, Flat, Resident, Role, Setting, User
from app.notification_service import notify_pending_resident_registration

auth_bp = Blueprint('auth', __name__)


def _password_reset_serializer():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='password-reset')


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


def _validate_password(password):
    if len(password) < 8:
        raise ValueError('Password must be at least 8 characters long.')
    if not re.search(r'[A-Za-z]', password) or not re.search(r'\d', password):
        raise ValueError('Password must include both letters and numbers.')
    return password


def _validate_flat_number(flat_number):
    if len(flat_number) < 2 or len(flat_number) > 20:
        raise ValueError('Flat number must be between 2 and 20 characters long.')
    if not re.fullmatch(r'[A-Za-z0-9\-\/\s]+', flat_number):
        raise ValueError('Flat number contains invalid characters.')
    return flat_number


def _get_login_background_url():
    setting = Setting.query.filter_by(key='login_background_image').first()
    if setting and setting.value:
        return url_for('static', filename=setting.value)
    return None


@auth_bp.route('/role/<role_key>')
def select_role(role_key):
    if current_user.is_authenticated:
        logout_user()

    role_map = {
        'resident': 'Resident',
        'owner': 'Society Administrator',
        'security': 'Security Guard',
        'maintenance': 'Maintenance Staff'
    }
    selected_role = role_map.get(role_key.lower())
    if not selected_role:
        flash('Invalid role selected.', 'warning')
        return redirect(url_for('main.index'))

    allow_register = selected_role == 'Resident'
    return render_template('auth/role_auth.html', selected_role=selected_role, selected_key=role_key.lower(), allow_register=allow_register, background_image=_get_login_background_url())


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    selected_key = request.args.get('role') or request.form.get('role')
    # If no role is provided on GET, send the user to the role selection page
    if request.method == 'GET' and not selected_key:
        return redirect(url_for('auth.select_role', role_key='resident'))

    # If an admin role was requested, forward to the dedicated admin login
    if selected_key and str(selected_key).lower() == 'admin':
        return redirect(url_for('auth.admin_login'))

    role_map = {
        'resident': {'name': 'Resident', 'allowed': ['Resident']},
        'admin': {'name': 'Admin', 'allowed': ['Super Admin', 'Society Admin']},
        'owner': {'name': 'Society Administrator', 'allowed': ['Owner']},
        'security': {'name': 'Security Guard', 'allowed': ['Security Guard']},
        'maintenance': {'name': 'Maintenance Staff', 'allowed': ['Maintenance Staff']}
    }
    selected_role = None
    allowed_roles = None
    if selected_key and selected_key in role_map:
        selected_role = role_map[selected_key]['name']
        allowed_roles = role_map[selected_key]['allowed']

    if current_user.is_authenticated:
        logout_user()

    if request.method == 'POST':
        identifier = request.form.get('identifier', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter((User.email == identifier) | (User.username == identifier)).first()
        if user and check_password_hash(user.password_hash, password):
            if not user.is_active:
                flash('This account has been deactivated. Please contact the owner.', 'warning')
                return render_template('auth/login.html', background_image=_get_login_background_url(), selected_role=selected_role, selected_key=selected_key)
            if selected_role and user.role and allowed_roles and user.role.name not in allowed_roles:
                flash('The selected role does not match this account.', 'danger')
                return render_template('auth/login.html', background_image=_get_login_background_url(), selected_role=selected_role, selected_key=selected_key)
            role_name = user.role.name if user.role else None
            if user.role and user.role.name == 'Resident':
                resident = Resident.query.filter_by(user_id=user.id).first()
                if not resident or resident.approval_status != 'Approved':
                    flash('Your resident account is pending owner approval. Please wait for access.', 'warning')
                    return render_template('auth/login.html', background_image=_get_login_background_url(), selected_role=selected_role, selected_key=selected_key)
            if role_name not in {'Super Admin', 'Owner'} and not user.is_approved:
                flash('Your account is pending admin approval. Please wait for access.', 'warning')
                return render_template('auth/login.html', background_image=_get_login_background_url(), selected_role=selected_role, selected_key=selected_key)
            login_user(user, remember=request.form.get('remember_me') == 'on')
            user.last_login = db.func.now()
            db.session.add(AuditLog(user_id=user.id, action='Login', details='User logged in'))
            db.session.commit()
            flash('Login successful', 'success')
            if user.role and user.role.name in {'Super Admin', 'Society Admin'}:
                return redirect(url_for('admin.dashboard'))
            if user.role and user.role.name == 'Resident':
                return redirect(url_for('resident.index'))
            return redirect(url_for('main.dashboard'))
        flash('Invalid credentials', 'danger')
    return render_template('auth/login.html', background_image=_get_login_background_url(), selected_role=selected_role, selected_key=selected_key)


@auth_bp.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        identifier = request.form.get('identifier', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter((User.email == identifier) | (User.username == identifier)).first()
        if user and check_password_hash(user.password_hash, password):
            if not user.is_active:
                flash('This account has been deactivated. Please contact the owner.', 'warning')
                return render_template('auth/admin_login.html', background_image=_get_login_background_url())
            if not user.role or user.role.name not in {'Super Admin', 'Society Admin'}:
                flash('Only admin accounts can access this page.', 'warning')
                return render_template('auth/admin_login.html', background_image=_get_login_background_url())
            login_user(user, remember=request.form.get('remember_me') == 'on')
            user.last_login = db.func.now()
            db.session.add(AuditLog(user_id=user.id, action='Login', details='Admin logged in'))
            db.session.commit()
            flash('Login successful', 'success')
            return redirect(url_for('admin.dashboard'))
        flash('Invalid admin credentials', 'danger')
    return render_template('auth/admin_login.html', background_image=_get_login_background_url())


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    selected_key = request.args.get('role') or request.form.get('role') or 'resident'
    if request.method == 'GET' and not request.args.get('role'):
        return redirect(url_for('auth.select_role', role_key='resident'))
    if selected_key.lower() != 'resident':
        flash('Only residents can self-register. Please contact admin for other roles.', 'warning')
        return redirect(url_for('auth.select_role', role_key='resident'))

    selected_role = 'Resident'
    if current_user.is_authenticated:
        logout_user()
    if request.method == 'POST':
        try:
            email = _validate_email(request.form.get('email', '').strip())
            first_name = _normalize_text(request.form.get('first_name', ''))
            last_name = _normalize_text(request.form.get('last_name', '')) or None
            phone = _validate_phone(_normalize_text(request.form.get('phone', '')))
            flat_number = _validate_flat_number(_normalize_text(request.form.get('flat_number', '')))
            resident_type = _normalize_text(request.form.get('resident_type', ''))
            password = _validate_password(request.form.get('password', ''))
        except ValueError as exc:
            flash(str(exc), 'warning')
            return render_template('auth/register.html', selected_role=selected_role, selected_key=selected_key, background_image=_get_login_background_url())

        if not first_name:
            flash('First name is required.', 'warning')
            return render_template('auth/register.html', selected_role=selected_role, selected_key=selected_key, background_image=_get_login_background_url())
        if resident_type not in {'Flat Owner', 'Tenant'}:
            flash('Please select a resident type.', 'warning')
            return render_template('auth/register.html', selected_role=selected_role, selected_key=selected_key, background_image=_get_login_background_url())

        if User.query.filter_by(phone=phone).first():
            flash('Unable to register with this mobile number. Please check the details and try again.', 'warning')
            return render_template('auth/register.html', selected_role=selected_role, selected_key=selected_key, background_image=_get_login_background_url())

        if flat_number:
            existing_flat = Flat.query.filter(db.func.lower(Flat.number) == flat_number.lower()).first()
            if existing_flat:
                existing_resident = Resident.query.filter(
                    Resident.flat_id == existing_flat.id,
                    Resident.status != 'Inactive'
                ).first()
                if existing_resident:
                    flash('This flat number is already registered to another resident. Please choose a different flat number.', 'warning')
                    return render_template('auth/register.html', selected_role=selected_role, selected_key=selected_key, background_image=_get_login_background_url())

        role = Role.query.filter_by(name='Resident').first()
        if not role:
            flash('User role setup is incomplete. Please restart the app or contact support.', 'danger')
            return render_template('auth/register.html', selected_role=selected_role, selected_key=selected_key, background_image=_get_login_background_url())
        if User.query.filter_by(email=email).first():
            flash('An account with that email already exists. Please use a different email address.', 'warning')
            return render_template('auth/register.html', selected_role=selected_role, selected_key=selected_key, background_image=_get_login_background_url())

        try:
            username = email or f"resident-{first_name.lower() or 'user'}"
            user = User(username=username, email=email, first_name=first_name, last_name=last_name, phone=phone, password_hash=generate_password_hash(password), role_id=role.id, is_verified=True, is_approved=False, is_active=True)
            db.session.add(user)
            db.session.flush()

            resident = Resident(user_id=user.id, emergency_contact='', resident_type=resident_type, approval_status='Pending', status='Pending')
            if flat_number:
                existing_flat = Flat.query.filter(db.func.lower(Flat.number) == flat_number.lower()).first()
                if not existing_flat:
                    building = Building.query.order_by(Building.id).first()
                    if not building:
                        building = Building(name=current_app.config['SOCIETY_NAME'], address='Society')
                        db.session.add(building)
                        db.session.flush()
                    existing_flat = Flat(number=flat_number, flat_type='2BHK', building_id=building.id, occupied=True)
                    db.session.add(existing_flat)
                    db.session.flush()

                resident.flat_id = existing_flat.id
                resident.building_id = existing_flat.building_id

            db.session.add(resident)
            db.session.flush()
            db.session.add(AuditLog(user_id=user.id, action='Registration', details='New resident registered', owner_name='Self', resident_name=f'{first_name} {last_name or ""}'.strip(), flat_number=flat_number if flat_number else 'Unassigned', description='New resident registration submitted for approval'))
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            flash('We could not complete your registration. Please try again.', 'danger')
            return render_template('auth/register.html', selected_role=selected_role, selected_key=selected_key, background_image=_get_login_background_url())

        notify_pending_resident_registration(resident)
        email_sent = send_app_email(
            user.email,
            'Digital Society registration received',
            f'Hello {user.first_name}, your Digital Society registration was received and is pending society approval.',
            f'<p>Hello {user.first_name},</p><p>Your Digital Society registration was received and is pending society approval.</p>',
        )
        if email_sent:
            flash('Registration successful. A confirmation email was sent.', 'success')
        else:
            flash('Registration successful, but the confirmation email could not be sent. Please check SMTP settings.', 'warning')
        return redirect(url_for('auth.login', role='resident'))
    return render_template('auth/register.html', selected_role=selected_role, selected_key=selected_key, background_image=_get_login_background_url())


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out', 'info')
    return redirect(url_for('main.index'))


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        try:
            email = _validate_email(email)
        except ValueError as exc:
            flash(str(exc), 'warning')
            return render_template('auth/forgot_password.html')

        user = User.query.filter_by(email=email).first()
        if user:
            token = _password_reset_serializer().dumps(user.email)
            reset_url = url_for('auth.reset_password', token=token, _external=True)
            email_sent = send_app_email(
                user.email,
                'Digital Society password reset',
                f'Use this link to reset your password: {reset_url}\n\nThis link expires in 1 hour.',
                f'<p>Use the link below to reset your password:</p><p><a href="{reset_url}">Reset your password</a></p><p>This link expires in 1 hour.</p>',
            )
            if not email_sent:
                flash('We could not send the reset email. Please check the mail server settings.', 'danger')
            else:
                flash('Reset instructions have been sent to your registered email.', 'info')
        else:
            flash('No account found with that email.', 'warning')
    return render_template('auth/forgot_password.html')


@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        email = _password_reset_serializer().loads(token, max_age=3600)
    except (BadSignature, SignatureExpired):
        flash('This password reset link is invalid or has expired.', 'warning')
        return redirect(url_for('auth.forgot_password'))

    user = User.query.filter_by(email=email).first()
    if not user:
        flash('This password reset link is invalid or has expired.', 'warning')
        return redirect(url_for('auth.forgot_password'))

    if request.method == 'POST':
        password = request.form.get('password', '')
        confirmation = request.form.get('confirm_password', '')
        try:
            _validate_password(password)
        except ValueError as exc:
            flash(str(exc), 'warning')
        else:
            if password != confirmation:
                flash('Passwords do not match.', 'warning')
            else:
                user.password_hash = generate_password_hash(password)
                db.session.commit()
                flash('Your password has been reset. Please log in.', 'success')
                return redirect(url_for('auth.login', role='resident'))

    return render_template('auth/reset_password.html', token=token)


@auth_bp.route('/hidden-admin')
def hidden_admin():
    # Hidden convenience endpoint that redirects to the login page with admin role
    return redirect(url_for('auth.login', role='admin'))
