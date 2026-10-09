from flask import Blueprint, redirect, render_template, url_for
from flask_login import current_user, login_required

from app import db
from app.models import Notification
from app.notification_service import (
    sync_paid_payment_notifications,
    sync_pending_resident_registration_notifications,
)


notifications_bp = Blueprint('notifications', __name__)


def _fallback_notification_target(role_name, title):
    title = (title or '').lower()
    if any(keyword in title for keyword in ('registration', 'resident approval')):
        if role_name == 'Owner':
            return url_for('owner.residents')
        if role_name in {'Super Admin', 'Society Admin'}:
            return url_for('admin.residents')
        return url_for('resident.index')
    if any(keyword in title for keyword in ('bill', 'payment', 'razorpay')):
        if role_name == 'Resident':
            return url_for('billing.index')
        if role_name == 'Owner':
            return url_for('owner.report_bills', status='all')
        return url_for('admin.dashboard')
    if 'complaint' in title:
        if role_name == 'Resident':
            return url_for('resident.complaints')
        if role_name == 'Owner':
            return url_for('owner.complaints')
        if role_name in {'Super Admin', 'Society Admin'}:
            return url_for('admin.complaints')
        if role_name == 'Maintenance Staff':
            return url_for('maintenance.index')
        return url_for('security.index')
    if 'maintenance' in title:
        if role_name == 'Resident':
            return url_for('resident.maintenance')
        if role_name == 'Maintenance Staff':
            return url_for('maintenance.index')
        if role_name == 'Owner':
            return url_for('owner.maintenance_requests')
        return url_for('admin.dashboard')
    if 'amenity' in title:
        return url_for('resident.amenities') if role_name == 'Resident' else url_for('admin.amenities')
    if 'visitor' in title:
        if role_name == 'Resident':
            return url_for('resident.visitors')
        if role_name == 'Security Guard':
            return url_for('security.visitor_requests')
        return url_for('security.index')
    if 'memo' in title:
        return url_for('resident.memos') if role_name == 'Resident' else url_for('security.resident_memos')
    if 'activity' in title:
        return url_for('owner.activities') if role_name == 'Owner' else url_for('resident.activities')
    if 'event' in title:
        return url_for('owner.events') if role_name == 'Owner' else url_for('event.index')
    if 'meeting' in title:
        return url_for('meetings.index')
    if 'notice' in title:
        if role_name == 'Owner':
            return url_for('owner.notices')
        if role_name in {'Super Admin', 'Society Admin'}:
            return url_for('admin.notices')
        return url_for('notice.index')
    if 'feedback' in title:
        return url_for('feedback.index')
    if 'emergency' in title:
        return url_for('emergency.index')
    return {
        'Resident': url_for('resident.index'),
        'Owner': url_for('owner.dashboard'),
        'Super Admin': url_for('admin.dashboard'),
        'Society Admin': url_for('admin.dashboard'),
        'Security Guard': url_for('security.index'),
        'Maintenance Staff': url_for('maintenance.index'),
    }.get(role_name, url_for('main.dashboard'))


@notifications_bp.route('/')
@login_required
def index():
    if current_user.role and current_user.role.name in {'Super Admin', 'Society Admin', 'Owner'}:
        sync_paid_payment_notifications()
        sync_pending_resident_registration_notifications()
    notifications = Notification.query.filter_by(
        user_id=current_user.id,
    ).order_by(Notification.created_at.desc()).limit(50).all()
    updated_targets = False
    role_name = current_user.role.name if current_user.role else None
    for notification in notifications:
        if not notification.target_url:
            notification.target_url = _fallback_notification_target(role_name, notification.title)
            updated_targets = True
    if updated_targets:
        db.session.commit()
    return render_template('notifications/index.html', notifications=notifications)


@notifications_bp.route('/<int:notification_id>/read', methods=['POST'])
@login_required
def mark_read(notification_id):
    notification = Notification.query.filter_by(
        id=notification_id,
        user_id=current_user.id,
    ).first_or_404()
    notification.is_read = True
    db.session.commit()
    return redirect(url_for('notifications.index'))


@notifications_bp.route('/<int:notification_id>/delete', methods=['POST'])
@login_required
def delete_notification(notification_id):
    notification = Notification.query.filter_by(
        id=notification_id,
        user_id=current_user.id,
    ).first_or_404()
    db.session.delete(notification)
    db.session.commit()
    return redirect(url_for('notifications.index'))


@notifications_bp.route('/read-all', methods=['POST'])
@login_required
def mark_all_read():
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update(
        {'is_read': True},
        synchronize_session=False,
    )
    db.session.commit()
    return redirect(url_for('notifications.index'))
