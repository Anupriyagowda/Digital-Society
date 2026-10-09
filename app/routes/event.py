from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from datetime import datetime

from app import db
from app.models import Activity, ActivityParticipant, Event, Participant, Resident, AuditLog
from app.notification_service import notify_residents, notify_user

event_bp = Blueprint('event', __name__)


@event_bp.route('/')
@login_required
def index():
    events = Event.query.order_by(Event.start_date.asc()).all()
    resident = Resident.query.filter_by(user_id=current_user.id).first()
    registrations = set()
    if resident:
        registrations = {participant.event_id for participant in Participant.query.filter_by(resident_id=resident.id, status='Registered').all()}
    return render_template('event/index.html', events=events, registrations=registrations, resident=resident)


@event_bp.route('/<int:event_id>')
@login_required
def detail(event_id):
    event = Event.query.get_or_404(event_id)
    participant_count = Participant.query.filter_by(event_id=event.id, status='Registered').count()
    activities = Activity.query.filter_by(event_id=event.id).all()
    resident = Resident.query.filter_by(user_id=current_user.id).first()
    registered = False
    activity_registrations = set()
    if resident:
        registered = Participant.query.filter_by(event_id=event.id, resident_id=resident.id, status='Registered').first() is not None
        activity_registrations = {participant.activity_id for participant in ActivityParticipant.query.filter_by(resident_id=resident.id).all()}
    return render_template(
        'event/detail.html',
        event=event,
        participant_count=participant_count,
        registered=registered,
        resident=resident,
        activities=activities,
        activity_registrations=activity_registrations
    )


@event_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    if not current_user.role or current_user.role.name != 'Owner':
        flash('Only owners can create events.', 'danger')
        return redirect(url_for('event.index'))
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        start_date = request.form.get('start_date')
        end_date = request.form.get('end_date')
        location = request.form.get('location')
        event_type = request.form.get('event_type', 'General')
        max_capacity = int(request.form.get('max_capacity', 100) or 100)
        try:
            sd = datetime.fromisoformat(start_date)
            ed = datetime.fromisoformat(end_date)
        except Exception:
            flash('Invalid date format. Use YYYY-MM-DD or YYYY-MM-DDTHH:MM.', 'warning')
            return render_template('event/create.html')
        event = Event(
            title=title,
            description=description,
            start_date=sd,
            end_date=ed,
            location=location,
            event_type=event_type,
            max_capacity=max_capacity,
            created_by_id=current_user.id
        )
        db.session.add(event)
        db.session.commit()
        notify_residents(
            'New society event',
            f'{event.title} is scheduled for {event.start_date.strftime("%d %b %Y")} at {event.location or "the society"}.',
        )
        audit = AuditLog(user_id=current_user.id, action='Created event', details=f'Event: {title}')
        db.session.add(audit)
        db.session.commit()
        flash('Event created.', 'success')
        return redirect(url_for('event.index'))
    return render_template('event/create.html')


@event_bp.route('/<int:event_id>/register', methods=['POST'])
@login_required
def register(event_id):
    event = Event.query.get_or_404(event_id)
    if event.status != 'Active':
        flash('Registration is closed for this event.', 'warning')
        return redirect(url_for('event.detail', event_id=event.id))

    resident = Resident.query.filter_by(user_id=current_user.id).first()
    if not resident:
        if not current_user.role or current_user.role.name != 'Resident':
            flash('Only residents can register for events.', 'warning')
            return redirect(url_for('event.detail', event_id=event.id))
        resident = Resident(user_id=current_user.id, emergency_contact='', resident_type='Tenant', approval_status='Approved', status='Active')
        db.session.add(resident)
        db.session.flush()

    selected_activity_ids = request.form.getlist('activity_ids')
    selected_activity_ids = [int(activity_id) for activity_id in selected_activity_ids if activity_id.isdigit()]

    participant = Participant.query.filter_by(event_id=event.id, resident_id=resident.id).first()
    event_registered = False
    if participant is None:
        registered_count = Participant.query.filter_by(event_id=event.id, status='Registered').count()
        if registered_count >= event.max_capacity:
            flash('This event has reached maximum capacity.', 'warning')
            return redirect(url_for('event.detail', event_id=event.id))
        participant = Participant(event_id=event.id, resident_id=resident.id, status='Registered')
        db.session.add(participant)
        event_registered = True
    elif participant.status == 'Cancelled':
        if Participant.query.filter_by(event_id=event.id, status='Registered').count() >= event.max_capacity:
            flash('This event has reached maximum capacity.', 'warning')
            return redirect(url_for('event.detail', event_id=event.id))
        participant.status = 'Registered'
        participant.cancel_reason = None
        participant.cancelled_at = None
        event_registered = True
    else:
        event_registered = False

    activity_messages = []
    registered_activity_titles = []
    if selected_activity_ids:
        for activity_id in selected_activity_ids:
            activity = Activity.query.filter_by(id=activity_id, event_id=event.id, status='Active').first()
            if not activity:
                continue
            if ActivityParticipant.query.filter_by(activity_id=activity.id, resident_id=resident.id).first():
                continue
            activity_count = ActivityParticipant.query.filter_by(activity_id=activity.id).count()
            if activity_count >= activity.max_participants:
                activity_messages.append(f'{activity.title} is full.')
                continue
            db.session.add(ActivityParticipant(activity_id=activity.id, resident_id=resident.id))
            activity_messages.append(f'Registered for {activity.title}.')
            registered_activity_titles.append(activity.title)

    if event_registered:
        db.session.commit()
        audit = AuditLog(user_id=current_user.id, action='Registered for event', details=f'Event ID: {event.id}')
        db.session.add(audit)
        db.session.commit()
        if event.created_by_id != current_user.id:
            details = [f'{current_user.first_name or current_user.username} registered for "{event.title}"']
            if registered_activity_titles:
                details.append(f'and activities: {", ".join(registered_activity_titles)}')
            notify_user(event.created_by_id, 'New event registration', ' '.join(details) + '.')
        flash_message = 'Registration Successful'
        if activity_messages:
            flash_message += ': ' + ' '.join(activity_messages)
        flash(flash_message, 'success')
        return redirect(url_for('event.detail', event_id=event.id))

    db.session.commit()
    if registered_activity_titles and event.created_by_id != current_user.id:
        notify_user(
            event.created_by_id,
            'New activity registration',
            f'{current_user.first_name or current_user.username} registered for {", ".join(registered_activity_titles)} in "{event.title}".',
        )
    if selected_activity_ids:
        flash_message = 'Already Registered'
        if activity_messages:
            flash_message += ': ' + ' '.join(activity_messages)
        flash(flash_message, 'info')
        return redirect(url_for('event.detail', event_id=event.id))

    flash('Already Registered', 'info')
    return redirect(url_for('event.detail', event_id=event.id))


@event_bp.route('/<int:event_id>/cancel', methods=['POST'])
@login_required
def cancel_registration(event_id):
    event = Event.query.get_or_404(event_id)
    resident = Resident.query.filter_by(user_id=current_user.id).first()
    if not resident:
        flash('Only residents can cancel event registrations.', 'warning')
        return redirect(url_for('event.detail', event_id=event.id))

    participant = Participant.query.filter_by(event_id=event.id, resident_id=resident.id, status='Registered').first()
    if not participant:
        flash('You are not registered for this event.', 'warning')
        return redirect(url_for('event.detail', event_id=event.id))

    reason = request.form.get('reason', '').strip()
    if not reason:
        flash('Please provide a reason for cancellation.', 'warning')
        return redirect(url_for('event.detail', event_id=event.id))

    participant.status = 'Cancelled'
    participant.cancel_reason = reason
    participant.cancelled_at = datetime.utcnow()
    db.session.commit()
    if event.created_by_id != current_user.id:
        notify_user(
            event.created_by_id,
            'Event registration cancelled',
            f'{current_user.first_name or current_user.username} cancelled registration for "{event.title}".',
        )

    audit = AuditLog(user_id=current_user.id, action='Cancelled event registration', details=f'Event ID: {event.id}. Reason: {reason}')
    db.session.add(audit)
    db.session.commit()
    flash('Your event registration has been cancelled.', 'success')
    return redirect(url_for('event.detail', event_id=event.id))
