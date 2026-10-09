from datetime import datetime

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from itsdangerous import BadSignature, SignatureExpired, URLSafeSerializer, URLSafeTimedSerializer
from markupsafe import escape

from app import db
from app.notification_service import email_user, email_admins
from app.models import AuthorizedPerson, Building, Complaint, Flat, Memo, Notification, Resident, Role, User, Visitor

security_bp = Blueprint('security', __name__)


@security_bp.after_request
def prevent_visitor_approval_cache(response):
    if request.endpoint == 'security.email_visitor_approval':
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response


def _get_security_users():
    security_role = Role.query.filter_by(name='Security Guard').first()
    if not security_role:
        return []
    return User.query.filter_by(role_id=security_role.id).all()


def _get_visitor_resident(visitor):
    return db.session.get(Resident, visitor.resident_id) if visitor.resident_id else None


def _visitor_approval_serializer():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='visitor-approval')


def _create_notification(user_id, title, message):
    if not user_id:
        return
    db.session.add(Notification(user_id=user_id, title=title, message=message))
    db.session.commit()


def _security_access():
    if not getattr(current_user, 'role', None) or current_user.role.name != 'Security Guard':
        flash('Only security staff can access this area.', 'danger')
        return redirect(url_for('main.dashboard'))
    return None


@security_bp.route('/digital-pass/scanner')
@login_required
def digital_pass_scanner():
    access_check = _security_access()
    if access_check is not None:
        return access_check
    return render_template('security/digital_pass_scanner.html')


@security_bp.route('/authorized-people')
@login_required
def authorized_people():
    access_check = _security_access()
    if access_check is not None:
        return access_check
    flat_number = request.args.get('flat_number', '').strip()
    people = []
    if flat_number:
        residents = Resident.query.join(Resident.flat).filter(Flat.number.ilike(flat_number)).all()
        resident_ids = [resident.id for resident in residents]
        if resident_ids:
            people = AuthorizedPerson.query.filter(AuthorizedPerson.resident_id.in_(resident_ids), AuthorizedPerson.status == 'Active').all()
    return render_template('security/authorized_people.html', people=people, flat_number=flat_number)


@security_bp.route('/digital-pass/<token>')
@login_required
def verify_digital_pass(token):
    access_check = _security_access()
    if access_check is not None:
        return access_check

    try:
        pass_data = URLSafeSerializer(current_app.config['SECRET_KEY']).loads(token)
        resident_id = pass_data['resident_id']
    except (BadSignature, KeyError, TypeError):
        flash('This digital pass is invalid.', 'danger')
        return redirect(url_for('security.digital_pass_scanner'))

    resident = Resident.query.get_or_404(resident_id)
    building = Building.query.get(resident.building_id) if resident.building_id else None
    flat_number = resident.flat.number if resident.flat else 'Not assigned'
    society_name = building.name if building else current_app.config['SOCIETY_NAME']
    is_active = bool(resident.user and resident.user.is_active and resident.status == 'Active' and resident.approval_status == 'Approved')
    return render_template(
        'security/digital_pass_result.html',
        resident=resident,
        flat_number=flat_number,
        society_name=society_name,
        is_active=is_active,
    )


@security_bp.route('/')
@login_required
def index():
    if not current_user.is_authenticated:
        flash('Please log in to continue.', 'info')
        return redirect(url_for('auth.login'))

    if not getattr(current_user, 'role', None) or current_user.role.name != 'Security Guard':
        flash('Only security staff can access this area.', 'danger')
        return redirect(url_for('main.dashboard'))

    visitors = Visitor.query.order_by(Visitor.created_at.desc()).all()
    memos = Memo.query.order_by(Memo.created_at.desc()).all()
    complaints = Complaint.query.order_by(Complaint.created_at.desc()).all()
    return render_template('security/index.html', visitors=visitors, memos=memos, complaints=complaints)


@security_bp.route('/visitor-management')
@login_required
def visitor_management():
    if not getattr(current_user, 'role', None) or current_user.role.name != 'Security Guard':
        flash('Only security staff can access this area.', 'danger')
        return redirect(url_for('main.dashboard'))

    visitors = Visitor.query.order_by(Visitor.created_at.desc()).all()
    return render_template('security/visitor_management.html', visitors=visitors)


@security_bp.route('/visitor-requests')
@login_required
def visitor_requests():
    if not getattr(current_user, 'role', None) or current_user.role.name != 'Security Guard':
        flash('Only security staff can access this area.', 'danger')
        return redirect(url_for('main.dashboard'))

    visitors = Visitor.query.order_by(Visitor.created_at.desc()).all()
    return render_template('security/visitor_requests.html', visitors=visitors)


@security_bp.route('/resident-memos')
@login_required
def resident_memos():
    if not getattr(current_user, 'role', None) or current_user.role.name != 'Security Guard':
        flash('Only security staff can access this area.', 'danger')
        return redirect(url_for('main.dashboard'))

    memos = Memo.query.order_by(Memo.created_at.desc()).all()
    return render_template('security/resident_memos.html', memos=memos)


@security_bp.route('/visitor/new', methods=['POST'])
@login_required
def create_visitor_request():
    if not getattr(current_user, 'role', None) or current_user.role.name != 'Security Guard':
        flash('Only security staff can access this area.', 'danger')
        return redirect(url_for('main.dashboard'))

    full_name = request.form.get('full_name', '').strip()
    phone = request.form.get('phone', '').strip()
    purpose = request.form.get('purpose', '').strip()
    entry_time_text = request.form.get('entry_time', '').strip()
    flat_number = request.form.get('flat_number', '').strip()

    if not full_name or not phone or not purpose or not flat_number:
        flash('Please complete all visitor request fields.', 'warning')
        return redirect(url_for('security.index'))

    try:
        entry_time = datetime.strptime(entry_time_text, '%Y-%m-%dT%H:%M') if entry_time_text else None
    except ValueError:
        flash('Please enter a valid entry time.', 'warning')
        return redirect(url_for('security.index'))

    flat = Flat.query.filter_by(number=flat_number).first()
    resident = None
    if flat:
        resident = Resident.query.filter_by(flat_id=flat.id).first()
    if not resident:
        flash('No resident was found for that flat number.', 'warning')
        return redirect(url_for('security.index'))

    visitor = Visitor(
        full_name=full_name,
        phone=phone,
        purpose=purpose,
        entry_time=entry_time,
        flat_number=flat_number,
        resident_id=resident.id,
        status='Pending Approval',
    )
    db.session.add(visitor)
    db.session.flush()

    resident_user_id = resident.user_id if resident else None
    if resident_user_id:
        _create_notification(resident_user_id, 'Visitor request pending approval', f'A new visitor request for {full_name} is awaiting your approval for flat {flat_number}.')
    for security_user in _get_security_users():
        if security_user.id != current_user.id:
            _create_notification(security_user.id, 'Visitor request submitted', f'Visitor request for {full_name} has been submitted for flat {flat_number}.')
    db.session.commit()
    approval_token = _visitor_approval_serializer().dumps({
        'visitor_id': visitor.id,
        'resident_id': resident.id,
    })
    approval_url = url_for('security.email_visitor_approval', token=approval_token, _external=True)
    entry_time = visitor.entry_time.strftime('%d %b %Y, %I:%M %p') if visitor.entry_time else 'Not specified'
    resident_name = resident.user.first_name or resident.user.username
    email_body = (
        f'Hello {resident_name},\n\n'
        'A visitor request is waiting for your approval.\n\n'
        f'Visitor: {visitor.full_name}\n'
        f'Contact number: {visitor.phone or "Not provided"}\n'
        f'Flat: {visitor.flat_number or "Not specified"}\n'
        f'Purpose: {visitor.purpose or "Not provided"}\n'
        f'Visit time: {entry_time}\n\n'
        f'Review visitor request: {approval_url}\n\n'
        'The approval link expires in 7 days.\n\n'
        'Digital Society'
    )
    email_html = (
        f'<p>Hello {escape(resident_name)},</p>'
        '<p>A visitor request is waiting for your approval.</p>'
        '<ul>'
        f'<li><strong>Visitor:</strong> {escape(visitor.full_name)}</li>'
        f'<li><strong>Contact number:</strong> {escape(visitor.phone or "Not provided")}</li>'
        f'<li><strong>Flat:</strong> {escape(visitor.flat_number or "Not specified")}</li>'
        f'<li><strong>Purpose:</strong> {escape(visitor.purpose or "Not provided")}</li>'
        f'<li><strong>Visit time:</strong> {escape(entry_time)}</li>'
        '</ul>'
        f'<p><a href="{escape(approval_url)}">Review visitor request</a></p>'
        '<p>This approval link expires in 7 days.</p>'
        '<p>Digital Society</p>'
    )
    email_user(resident.user, 'Visitor request pending approval', email_body, email_html)
    flash('Visitor request sent to the resident for approval.', 'success')
    return redirect(url_for('security.index'))


@security_bp.route('/visitor/approval/<token>', methods=['GET', 'POST'])
def email_visitor_approval(token):
    try:
        approval_data = _visitor_approval_serializer().loads(token, max_age=7 * 24 * 60 * 60)
        visitor_id = approval_data['visitor_id']
        resident_id = approval_data['resident_id']
        if not isinstance(visitor_id, int) or not isinstance(resident_id, int):
            raise BadSignature('Invalid visitor approval token')
    except (BadSignature, SignatureExpired, KeyError, TypeError):
        return render_template(
            'security/visitor_approval.html',
            visitor=None,
            token=None,
            error_message='This visitor approval link is invalid or has expired.',
        ), 400

    visitor = Visitor.query.filter_by(id=visitor_id, resident_id=resident_id).first()
    if not visitor:
        return render_template(
            'security/visitor_approval.html',
            visitor=None,
            token=None,
            error_message='This visitor request could not be found.',
        ), 404

    if visitor.status not in {'Pending Approval', 'Approved'}:
        return render_template(
            'security/visitor_approval.html',
            visitor=visitor,
            token=None,
            error_message=f'This visitor request is already {visitor.status.lower()}.',
        )

    if visitor.status == 'Approved' and request.method == 'GET':
        return render_template(
            'security/visitor_approval.html',
            visitor=visitor,
            token=token,
            error_message='This visitor is approved. You can reject the approval until security checks them in.',
        )

    if request.method == 'POST':
        decision = request.form.get('decision')
        if decision not in {'allow', 'reject'}:
            return render_template(
                'security/visitor_approval.html',
                visitor=visitor,
                token=token,
                error_message='Choose whether to allow or reject this visitor.',
            ), 400

        if visitor.status == 'Approved' and decision == 'allow':
            return render_template(
                'security/visitor_approval.html',
                visitor=visitor,
                token=token,
                error_message='This visitor is already approved. You can reject the approval until security checks them in.',
            )

        approved = decision == 'allow'
        visitor.status = 'Approved' if approved else 'Rejected'
        notification_title = 'Visitor approved' if approved else 'Visitor request rejected'
        notification_message = (
            f'Visitor {visitor.full_name} has been approved for flat {visitor.flat_number or "your flat"}.'
            if approved else
            f'Visitor {visitor.full_name} was rejected for flat {visitor.flat_number or "your flat"}.'
        )
        for security_user in _get_security_users():
            db.session.add(Notification(
                user_id=security_user.id,
                title=notification_title,
                message=notification_message,
            ))
        db.session.commit()
        email_admins(
            notification_title,
            notification_message,
        )
        flash(
            'Visitor approved. Security has been notified.' if approved else 'Visitor request rejected. Security has been notified.',
            'success' if approved else 'warning',
        )
        return redirect(url_for('security.email_visitor_approval', token=token))

    return render_template(
        'security/visitor_approval.html',
        visitor=visitor,
        token=token,
        error_message=None,
    )


@security_bp.route('/visitor/<int:visitor_id>/allow-entry', methods=['POST'])
@login_required
def allow_entry(visitor_id):
    if not getattr(current_user, 'role', None) or current_user.role.name != 'Security Guard':
        flash('Only security staff can access this area.', 'danger')
        return redirect(url_for('main.dashboard'))

    visitor = Visitor.query.get_or_404(visitor_id)
    if visitor.status != 'Approved':
        flash('Entry can only be allowed after the resident approves the visitor.', 'warning')
        return redirect(url_for('security.index'))

    visitor.status = 'Checked In'
    visitor.check_in = datetime.utcnow()
    resident = _get_visitor_resident(visitor)
    if resident and resident.user_id:
        _create_notification(resident.user_id, 'Visitor admitted', f'{visitor.full_name} has been admitted to flat {visitor.flat_number or "your flat"}.')
    db.session.commit()
    if resident and resident.user:
        email_user(resident.user, 'Visitor admitted', f'{visitor.full_name} has been admitted to flat {visitor.flat_number or "your flat"}.')
    flash('Visitor entry allowed.', 'success')
    return redirect(url_for('security.index'))


@security_bp.route('/visitor/<int:visitor_id>/check-out', methods=['POST'])
@login_required
def check_out(visitor_id):
    if not getattr(current_user, 'role', None) or current_user.role.name != 'Security Guard':
        flash('Only security staff can access this area.', 'danger')
        return redirect(url_for('main.dashboard'))

    visitor = Visitor.query.get_or_404(visitor_id)
    if visitor.status != 'Checked In':
        flash('Only checked-in visitors can be marked as checked out.', 'warning')
        return redirect(url_for('security.index'))

    visitor.status = 'Checked Out'
    visitor.check_out = datetime.utcnow()
    resident = _get_visitor_resident(visitor)
    db.session.commit()
    if resident and resident.user:
        email_user(resident.user, 'Visitor checked out', f'{visitor.full_name} has checked out from flat {visitor.flat_number or "your flat"}.')
    flash('Visitor checked out successfully.', 'success')
    return redirect(url_for('security.index'))


@security_bp.route('/memo/<int:memo_id>/follow', methods=['POST'])
@login_required
def follow_memo(memo_id):
    if not getattr(current_user, 'role', None) or current_user.role.name != 'Security Guard':
        flash('Only security staff can access this area.', 'danger')
        return redirect(url_for('main.dashboard'))

    memo = Memo.query.get_or_404(memo_id)
    memo.status = 'Followed'
    db.session.commit()
    flash('Memo marked as followed.', 'success')
    return redirect(url_for('security.index'))
