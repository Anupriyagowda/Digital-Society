from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import current_user, login_required

from app import db
from app.notification_service import email_user, notify_admins
from app.models import MaintenanceRequest, MaintenanceRequestHistory, Notification

maintenance_bp = Blueprint('maintenance', __name__)


def _create_notification(user_id, title, message):
    if not user_id:
        return
    db.session.add(Notification(user_id=user_id, title=title, message=message))
    db.session.commit()


def _notify_admins_and_resident(maintenance, status, note):
    resident_user = maintenance.resident.user if maintenance.resident else None
    resident_name = (resident_user.first_name or resident_user.username) if resident_user else 'a resident'
    notify_admins(
        'Maintenance request updated',
        f'Maintenance request "{maintenance.title}" for {resident_name} is now {status}. {note}'.strip(),
    )
    if resident_user:
        _create_notification(
            resident_user.id,
            'Maintenance request updated',
            f'Your maintenance request "{maintenance.title}" is now {status}. {note}'.strip()
        )


@maintenance_bp.route('/')
@login_required
def index():
    if current_user.role and current_user.role.name != 'Maintenance Staff':
        flash('Only maintenance staff can access this area.', 'danger')
        return redirect(url_for('main.dashboard'))
    requests = MaintenanceRequest.query.filter_by(staff_id=current_user.id).order_by(MaintenanceRequest.created_at.desc()).all()
    return render_template('maintenance/index.html', requests=requests)


@maintenance_bp.route('/<int:request_id>')
@login_required
def maintenance_detail(request_id):
    if current_user.role and current_user.role.name != 'Maintenance Staff':
        flash('Only maintenance staff can access this area.', 'danger')
        return redirect(url_for('main.dashboard'))
    maintenance = MaintenanceRequest.query.filter_by(id=request_id, staff_id=current_user.id).first_or_404()
    status_options = ['Assigned', 'Pending', 'In Progress', 'Completed', 'Resolved']
    return render_template('maintenance/detail.html', maintenance=maintenance, status_options=status_options)


@maintenance_bp.route('/<int:request_id>/update', methods=['POST'])
@login_required
def update_maintenance_status(request_id):
    if current_user.role and current_user.role.name != 'Maintenance Staff':
        flash('Only maintenance staff can update maintenance requests.', 'danger')
        return redirect(url_for('main.dashboard'))

    maintenance = MaintenanceRequest.query.filter_by(id=request_id, staff_id=current_user.id).first_or_404()
    status = request.form.get('status')
    note = request.form.get('note', '').strip()

    valid_statuses = ['Assigned', 'Pending', 'In Progress', 'Completed', 'Resolved']
    if status not in valid_statuses:
        flash('Invalid status selected.', 'warning')
        return redirect(url_for('maintenance.maintenance_detail', request_id=request_id))

    maintenance.status = status
    history_note = note or f'Status updated to {status}'
    history = MaintenanceRequestHistory(
        maintenance_request_id=maintenance.id,
        updated_by_id=current_user.id,
        status=status,
        note=history_note
    )
    db.session.add(history)
    _notify_admins_and_resident(maintenance, status, history_note)
    db.session.commit()
    if maintenance.resident and maintenance.resident.user:
        email_user(maintenance.resident.user, 'Maintenance status updated', f'Your maintenance request "{maintenance.title}" is now {status}. {history_note}')

    flash('Maintenance status updated successfully.', 'success')
    return redirect(url_for('maintenance.maintenance_detail', request_id=request_id))
