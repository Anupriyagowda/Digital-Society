from datetime import datetime
from functools import wraps

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app import db
from app.models import MeetingAgendaItem, MeetingAttendance, MeetingVote, SocietyMeeting
from app.notification_service import notify_residents, notify_user


def meeting_attendance_open(meeting):
    return (
        meeting is not None
        and meeting.status != 'Completed'
        and meeting.meeting_date
        and meeting.meeting_date > datetime.utcnow()
    )


meetings_bp = Blueprint('meetings', __name__)
ORGANIZER_ROLES = {'Super Admin', 'Society Admin', 'Owner'}


def organizer_required(function):
    @wraps(function)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.role or current_user.role.name not in ORGANIZER_ROLES:
            flash('Only society administrators and owners can manage meetings.', 'danger')
            return redirect(url_for('meetings.index'))
        return function(*args, **kwargs)
    return wrapped


@meetings_bp.route('/')
@login_required
def index():
    meetings = SocietyMeeting.query.order_by(SocietyMeeting.meeting_date.desc()).all()
    return render_template('meetings/index.html', meetings=meetings, can_manage=bool(current_user.role and current_user.role.name in ORGANIZER_ROLES))


@meetings_bp.route('/create', methods=['POST'])
@organizer_required
def create():
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    date_text = request.form.get('meeting_date', '').strip()
    location = request.form.get('location', '').strip()
    meeting_link = request.form.get('meeting_link', '').strip()
    if meeting_link and not meeting_link.startswith(('http://', 'https://')):
        meeting_link = f'https://{meeting_link}'
    try:
        meeting_date = datetime.strptime(date_text, '%Y-%m-%dT%H:%M')
    except ValueError:
        meeting_date = None
    if not title or not meeting_date:
        flash('Meeting title and a valid date are required.', 'warning')
        return redirect(url_for('meetings.index'))
    meeting = SocietyMeeting(title=title, description=description or None, meeting_date=meeting_date, location=location or None, meeting_link=meeting_link or None, created_by_id=current_user.id)
    db.session.add(meeting)
    db.session.commit()
    notify_residents(
        'New society meeting',
        f'{meeting.title} is scheduled for {meeting.meeting_date.strftime("%d %b %Y, %H:%M")}.',
    )
    flash('Meeting scheduled.', 'success')
    return redirect(url_for('meetings.index'))


@meetings_bp.route('/<int:meeting_id>')
@login_required
def detail(meeting_id):
    meeting = SocietyMeeting.query.get_or_404(meeting_id)
    attendance = MeetingAttendance.query.filter_by(meeting_id=meeting.id).all()
    attendance_open = meeting_attendance_open(meeting)
    return render_template(
        'meetings/detail.html',
        meeting=meeting,
        attendance=attendance,
        attendance_open=attendance_open,
        is_attending=any(item.user_id == current_user.id for item in attendance),
        can_manage=bool(current_user.role and current_user.role.name in ORGANIZER_ROLES),
    )


@meetings_bp.route('/<int:meeting_id>/attendance', methods=['POST'])
@login_required
def mark_attendance(meeting_id):
    meeting = SocietyMeeting.query.get_or_404(meeting_id)
    if not meeting_attendance_open(meeting):
        flash('Attendance is closed for past meetings.', 'warning')
        return redirect(url_for('meetings.detail', meeting_id=meeting.id))

    record = MeetingAttendance.query.filter_by(meeting_id=meeting.id, user_id=current_user.id).first()
    if record:
        db.session.delete(record)
        flash('Attendance withdrawn.', 'info')
    else:
        db.session.add(MeetingAttendance(meeting_id=meeting.id, user_id=current_user.id))
        flash('Attendance recorded.', 'success')
    db.session.commit()
    if meeting.created_by_id != current_user.id:
        attendance_action = 'will attend' if record is None else 'withdrew from'
        notify_user(
            meeting.created_by_id,
            'Meeting attendance updated',
            f'{current_user.first_name or current_user.username} {attendance_action} "{meeting.title}".',
        )
    return redirect(url_for('meetings.detail', meeting_id=meeting.id))


@meetings_bp.route('/<int:meeting_id>/agenda', methods=['POST'])
@organizer_required
def add_agenda(meeting_id):
    meeting = SocietyMeeting.query.get_or_404(meeting_id)
    title = request.form.get('title', '').strip()
    if not title:
        flash('Agenda item title is required.', 'warning')
    else:
        position = len(meeting.agenda_items) + 1
        db.session.add(MeetingAgendaItem(meeting_id=meeting.id, title=title, details=request.form.get('details', '').strip() or None, position=position))
        db.session.commit()
        flash('Agenda item published.', 'success')
    return redirect(url_for('meetings.detail', meeting_id=meeting.id))


@meetings_bp.route('/<int:meeting_id>/minutes', methods=['POST'])
@organizer_required
def save_minutes(meeting_id):
    meeting = SocietyMeeting.query.get_or_404(meeting_id)
    meeting.minutes = request.form.get('minutes', '').strip() or None
    meeting.status = 'Completed'
    db.session.commit()
    flash('Meeting minutes saved.', 'success')
    return redirect(url_for('meetings.detail', meeting_id=meeting.id))


@meetings_bp.route('/<int:meeting_id>/vote', methods=['POST'])
@login_required
def vote(meeting_id):
    meeting = SocietyMeeting.query.get_or_404(meeting_id)
    motion = request.form.get('motion', '').strip()
    choice = request.form.get('choice', '').strip()
    if not motion or choice not in {'For', 'Against', 'Abstain'}:
        flash('Enter a motion and choose a valid vote.', 'warning')
        return redirect(url_for('meetings.detail', meeting_id=meeting.id))
    existing = MeetingVote.query.filter_by(meeting_id=meeting.id, motion=motion, user_id=current_user.id).first()
    if existing:
        existing.choice = choice
    else:
        db.session.add(MeetingVote(meeting_id=meeting.id, motion=motion, choice=choice, user_id=current_user.id))
    db.session.commit()
    flash('Your vote was recorded.', 'success')
    return redirect(url_for('meetings.detail', meeting_id=meeting.id))