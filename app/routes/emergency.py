from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app import db
from app.notification_service import email_user
from app.models import EmergencyAlert, EmergencyAlertAcknowledgement, Notification, User


emergency_bp = Blueprint('emergency', __name__)

ALERT_TYPES = ('Fire', 'Theft', 'Medical', 'Water', 'Power')
SEVERITIES = ('Critical', 'High', 'Medium')
CREATOR_ROLES = {'Super Admin', 'Society Admin', 'Owner', 'Security Guard'}


def _has_creator_access():
    return current_user.role and current_user.role.name in CREATOR_ROLES


@emergency_bp.route('/')
@login_required
def index():
    alerts = EmergencyAlert.query.order_by(EmergencyAlert.created_at.desc()).limit(50).all()
    acknowledged_ids = {
        acknowledgement.alert_id
        for acknowledgement in EmergencyAlertAcknowledgement.query.filter_by(user_id=current_user.id).all()
    }
    return render_template(
        'emergency/index.html',
        alerts=alerts,
        acknowledged_ids=acknowledged_ids,
        alert_types=ALERT_TYPES,
        severities=SEVERITIES,
        can_create=_has_creator_access(),
    )


@emergency_bp.route('/create', methods=['POST'])
@login_required
def create():
    if not _has_creator_access():
        flash('Only administrators, owners, and security staff can send emergency alerts.', 'danger')
        return redirect(url_for('emergency.index'))

    alert_type = request.form.get('alert_type', '').strip()
    severity = request.form.get('severity', '').strip()
    message = request.form.get('message', '').strip()
    if alert_type not in ALERT_TYPES or severity not in SEVERITIES or not message:
        flash('Choose a valid alert type, severity, and message.', 'warning')
        return redirect(url_for('emergency.index'))

    alert = EmergencyAlert(alert_type=alert_type, severity=severity, message=message)
    db.session.add(alert)
    title = f'{severity} emergency: {alert_type}'
    users = User.query.filter(User.is_active.is_(True)).all()
    for user in users:
        db.session.add(Notification(user_id=user.id, title=title, message=message))
    db.session.commit()
    email_body = (
        f'{title}\n\n{message}\n\n'
        'Please sign in to the Digital Society portal to view the alert and acknowledge it.'
    )
    for user in users:
        email_user(user, title, email_body)
    flash('Emergency alert sent to the society.', 'success')
    return redirect(url_for('emergency.index'))


@emergency_bp.route('/<int:alert_id>/acknowledge', methods=['POST'])
@login_required
def acknowledge(alert_id):
    EmergencyAlert.query.get_or_404(alert_id)
    existing = EmergencyAlertAcknowledgement.query.filter_by(
        alert_id=alert_id,
        user_id=current_user.id,
    ).first()
    if not existing:
        db.session.add(EmergencyAlertAcknowledgement(alert_id=alert_id, user_id=current_user.id))
        db.session.commit()
        flash('Emergency alert acknowledged.', 'success')
    return redirect(url_for('emergency.index'))