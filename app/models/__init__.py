from datetime import datetime
from flask_login import UserMixin
from sqlalchemy import func

from app import db


class Role(db.Model):
    __tablename__ = 'roles'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.String(255), nullable=True)
    users = db.relationship('User', backref='role', lazy=True)


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(80), nullable=True)
    last_name = db.Column(db.String(80), nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    avatar_url = db.Column(db.String(255), nullable=True)
    role_id = db.Column(db.Integer, db.ForeignKey('roles.id'), nullable=False)
    is_verified = db.Column(db.Boolean, default=False)
    is_approved = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    otp_code = db.Column(db.String(10), nullable=True)
    remember_me = db.Column(db.Boolean, default=False)
    last_login = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    resident = db.relationship(
        'Resident',
        back_populates='user',
        uselist=False,
        foreign_keys='Resident.user_id',
        primaryjoin='User.id == Resident.user_id'
    )


class Building(db.Model):
    __tablename__ = 'buildings'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    address = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    flats = db.relationship('Flat', backref='building', lazy=True)


class Flat(db.Model):
    __tablename__ = 'flats'
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(20), nullable=False)
    flat_type = db.Column(db.String(50), default='2BHK')
    building_id = db.Column(db.Integer, db.ForeignKey('buildings.id'), nullable=False)
    occupied = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    residents = db.relationship('Resident', backref='flat', lazy=True)


class Resident(db.Model):
    __tablename__ = 'residents'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    flat_id = db.Column(db.Integer, db.ForeignKey('flats.id'), nullable=True)
    building_id = db.Column(db.Integer, db.ForeignKey('buildings.id'), nullable=True)
    emergency_contact = db.Column(db.String(20), nullable=True)
    avatar_url = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(20), default='Active')
    approval_status = db.Column(db.String(20), default='Pending')  # Pending, Approved, Rejected
    resident_type = db.Column(db.String(20), nullable=True)
    approved_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    approval_date = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship(
        'User',
        back_populates='resident',
        foreign_keys=[user_id],
        uselist=False,
        primaryjoin='Resident.user_id == User.id'
    )
    complaints = db.relationship('Complaint', backref='resident', lazy=True)
    maintenance_requests = db.relationship('MaintenanceRequest', backref='resident', lazy=True)
    bills = db.relationship('Bill', backref='resident', lazy=True)
    participants = db.relationship('Participant', back_populates='resident', lazy=True)
    activity_participants = db.relationship('ActivityParticipant', back_populates='resident', lazy=True)
    family_members = db.relationship('FamilyMember', backref='resident', lazy=True, cascade='all, delete-orphan')
    emergency_contacts = db.relationship('EmergencyContact', backref='resident', lazy=True, cascade='all, delete-orphan')
    authorized_people = db.relationship('AuthorizedPerson', backref='resident', lazy=True, cascade='all, delete-orphan')
    amenity_bookings = db.relationship('AmenityBooking', back_populates='resident', lazy=True, cascade='all, delete-orphan')
    feedbacks = db.relationship('Feedback', back_populates='resident', lazy=True, cascade='all, delete-orphan')


class FamilyMember(db.Model):
    __tablename__ = 'family_members'
    id = db.Column(db.Integer, primary_key=True)
    resident_id = db.Column(db.Integer, db.ForeignKey('residents.id'), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    relationship = db.Column(db.String(50), nullable=False)
    phone = db.Column(db.String(20), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    is_dependent = db.Column(db.Boolean, default=False, nullable=False)
    notes = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class EmergencyContact(db.Model):
    __tablename__ = 'emergency_contacts'
    id = db.Column(db.Integer, primary_key=True)
    resident_id = db.Column(db.Integer, db.ForeignKey('residents.id'), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    relationship = db.Column(db.String(50), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    priority = db.Column(db.Integer, default=1, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class AuthorizedPerson(db.Model):
    __tablename__ = 'authorized_people'
    id = db.Column(db.Integer, primary_key=True)
    resident_id = db.Column(db.Integer, db.ForeignKey('residents.id'), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    relationship = db.Column(db.String(50), nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    vehicle_number = db.Column(db.String(20), nullable=True)
    valid_from = db.Column(db.Date, nullable=True)
    valid_until = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), default='Active', nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Visitor(db.Model):
    __tablename__ = 'visitors'
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20), nullable=True)
    vehicle_number = db.Column(db.String(20), nullable=True)
    purpose = db.Column(db.String(120), nullable=True)
    resident_id = db.Column(db.Integer, db.ForeignKey('residents.id'), nullable=True)
    flat_number = db.Column(db.String(40), nullable=True)
    entry_time = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), default='Pending Approval')
    check_in = db.Column(db.DateTime, nullable=True)
    check_out = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    resident = db.relationship('Resident', backref=db.backref('visitors', lazy=True), lazy=True)
    logs = db.relationship('VisitorLog', backref='visitor', lazy=True)


class Memo(db.Model):
    __tablename__ = 'memos'
    id = db.Column(db.Integer, primary_key=True)
    resident_id = db.Column(db.Integer, db.ForeignKey('residents.id'), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    content = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default='Pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    resident = db.relationship('Resident', backref='memos', lazy=True)


class VisitorLog(db.Model):
    __tablename__ = 'visitor_logs'
    id = db.Column(db.Integer, primary_key=True)
    visitor_id = db.Column(db.Integer, db.ForeignKey('visitors.id'), nullable=False)
    action = db.Column(db.String(50), nullable=False)
    note = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ComplaintCategory(db.Model):
    __tablename__ = 'complaint_categories'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False, unique=True)
    complaints = db.relationship('Complaint', backref='category', lazy=True)


class Complaint(db.Model):
    __tablename__ = 'complaints'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('complaint_categories.id'), nullable=True)
    resident_id = db.Column(db.Integer, db.ForeignKey('residents.id'), nullable=False)
    assigned_to_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    status = db.Column(db.String(20), default='Pending')
    priority = db.Column(db.String(20), default='Medium')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    assigned_to = db.relationship('User', foreign_keys=[assigned_to_id], backref='assigned_complaints', lazy=True)
    messages = db.relationship(
        'ComplaintMessage',
        backref='complaint',
        lazy=True,
        cascade='all, delete-orphan',
        order_by='ComplaintMessage.created_at'
    )


class ComplaintMessage(db.Model):
    __tablename__ = 'complaint_messages'
    id = db.Column(db.Integer, primary_key=True)
    complaint_id = db.Column(db.Integer, db.ForeignKey('complaints.id'), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    sender = db.relationship('User', foreign_keys=[sender_id], lazy=True)


class MaintenanceRequest(db.Model):
    __tablename__ = 'maintenance_requests'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=False)
    resident_id = db.Column(db.Integer, db.ForeignKey('residents.id'), nullable=False)
    staff_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    priority = db.Column(db.String(20), default='Medium')
    status = db.Column(db.String(20), default='Pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    staff = db.relationship('User', foreign_keys=[staff_id], backref='maintenance_assignments', lazy=True)
    histories = db.relationship(
        'MaintenanceRequestHistory',
        backref='maintenance_request',
        lazy=True,
        cascade='all, delete-orphan',
        order_by='MaintenanceRequestHistory.created_at'
    )


class MaintenanceRequestHistory(db.Model):
    __tablename__ = 'maintenance_request_histories'
    id = db.Column(db.Integer, primary_key=True)
    maintenance_request_id = db.Column(db.Integer, db.ForeignKey('maintenance_requests.id'), nullable=False)
    updated_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    status = db.Column(db.String(30), nullable=False)
    note = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    updated_by = db.relationship('User', foreign_keys=[updated_by_id], lazy=True)


class Bill(db.Model):
    __tablename__ = 'bills'
    id = db.Column(db.Integer, primary_key=True)
    bill_type = db.Column(db.String(50), nullable=False)
    description = db.Column(db.String(255), nullable=True)
    amount = db.Column(db.Float, nullable=False)
    due_date = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), default='Pending')
    resident_name = db.Column(db.String(120), nullable=True)
    flat_number = db.Column(db.String(40), nullable=True)
    payment_status = db.Column(db.String(20), default='Pending')
    payment_date = db.Column(db.Date, nullable=True)
    billing_period = db.Column(db.String(7), nullable=True)
    is_automatic = db.Column(db.Boolean, default=False, nullable=False)
    resident_id = db.Column(db.Integer, db.ForeignKey('residents.id'), nullable=False)
    flat_id = db.Column(db.Integer, db.ForeignKey('flats.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Payment(db.Model):
    __tablename__ = 'payments'
    id = db.Column(db.Integer, primary_key=True)
    bill_id = db.Column(db.Integer, db.ForeignKey('bills.id'), nullable=False)
    resident_id = db.Column(db.Integer, db.ForeignKey('residents.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    payment_method = db.Column(db.String(30), default='Online')
    status = db.Column(db.String(20), default='Paid')
    transaction_id = db.Column(db.String(80), nullable=True)
    razorpay_order_id = db.Column(db.String(80), nullable=True, unique=True)
    razorpay_payment_id = db.Column(db.String(80), nullable=True, unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Event(db.Model):
    __tablename__ = 'events'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=True)
    start_date = db.Column(db.DateTime, nullable=False)
    end_date = db.Column(db.DateTime, nullable=False)
    location = db.Column(db.String(120), nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    max_capacity = db.Column(db.Integer, default=100)
    event_type = db.Column(db.String(50), default='General')  # General, Sports, Festival, Meeting, etc.
    status = db.Column(db.String(20), default='Active')  # Active, Cancelled, Completed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    participants = db.relationship('Participant', backref='event', lazy=True, cascade='all, delete-orphan')
    activities = db.relationship('Activity', backref='event', lazy=True, cascade='all, delete-orphan')


class Participant(db.Model):
    __tablename__ = 'participants'
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'), nullable=False)
    resident_id = db.Column(db.Integer, db.ForeignKey('residents.id'), nullable=False)
    status = db.Column(db.String(20), default='Registered')
    cancel_reason = db.Column(db.String(255), nullable=True)
    cancelled_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    resident = db.relationship('Resident', foreign_keys=[resident_id], back_populates='participants', lazy=True)


class Activity(db.Model):
    __tablename__ = 'activities'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=True)
    max_participants = db.Column(db.Integer, default=20)
    status = db.Column(db.String(20), default='Active')
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    participants = db.relationship('ActivityParticipant', backref='activity', lazy=True, cascade='all, delete-orphan')


class ActivityParticipant(db.Model):
    __tablename__ = 'activity_participants'
    id = db.Column(db.Integer, primary_key=True)
    activity_id = db.Column(db.Integer, db.ForeignKey('activities.id'), nullable=False)
    resident_id = db.Column(db.Integer, db.ForeignKey('residents.id'), nullable=False)
    status = db.Column(db.String(20), default='Registered')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    resident = db.relationship('Resident', foreign_keys=[resident_id], back_populates='activity_participants', lazy=True)


class SocietyMeeting(db.Model):
    __tablename__ = 'society_meetings'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)
    meeting_date = db.Column(db.DateTime, nullable=False)
    location = db.Column(db.String(150), nullable=True)
    meeting_link = db.Column(db.String(500), nullable=True)
    status = db.Column(db.String(20), default='Scheduled', nullable=False)
    minutes = db.Column(db.Text, nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    agenda_items = db.relationship('MeetingAgendaItem', backref='meeting', lazy=True, cascade='all, delete-orphan', order_by='MeetingAgendaItem.position')
    attendance = db.relationship('MeetingAttendance', backref='meeting', lazy=True, cascade='all, delete-orphan')
    votes = db.relationship('MeetingVote', backref='meeting', lazy=True, cascade='all, delete-orphan')
    created_by = db.relationship('User', foreign_keys=[created_by_id], lazy=True)


class MeetingAgendaItem(db.Model):
    __tablename__ = 'meeting_agenda_items'
    id = db.Column(db.Integer, primary_key=True)
    meeting_id = db.Column(db.Integer, db.ForeignKey('society_meetings.id'), nullable=False)
    title = db.Column(db.String(180), nullable=False)
    details = db.Column(db.Text, nullable=True)
    position = db.Column(db.Integer, default=1, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class MeetingAttendance(db.Model):
    __tablename__ = 'meeting_attendance'
    id = db.Column(db.Integer, primary_key=True)
    meeting_id = db.Column(db.Integer, db.ForeignKey('society_meetings.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    attended_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', foreign_keys=[user_id], lazy=True)
    __table_args__ = (db.UniqueConstraint('meeting_id', 'user_id', name='uq_meeting_attendance_user'),)


class MeetingVote(db.Model):
    __tablename__ = 'meeting_votes'
    id = db.Column(db.Integer, primary_key=True)
    meeting_id = db.Column(db.Integer, db.ForeignKey('society_meetings.id'), nullable=False)
    motion = db.Column(db.String(255), nullable=False)
    choice = db.Column(db.String(20), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', foreign_keys=[user_id], lazy=True)
    __table_args__ = (db.UniqueConstraint('meeting_id', 'motion', 'user_id', name='uq_meeting_vote_user'),)


class MarketplaceListing(db.Model):
    __tablename__ = 'marketplace_listings'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(60), default='Other', nullable=False)
    price = db.Column(db.Float, nullable=True)
    contact_note = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(20), default='Available', nullable=False)
    seller_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    seller = db.relationship('User', foreign_keys=[seller_id], lazy=True)


class Amenity(db.Model):
    __tablename__ = 'amenities'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=True)
    location = db.Column(db.String(120), nullable=True)
    capacity = db.Column(db.Integer, default=1, nullable=False)
    opening_time = db.Column(db.Time, nullable=True)
    closing_time = db.Column(db.Time, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    bookings = db.relationship('AmenityBooking', back_populates='amenity', lazy=True, cascade='all, delete-orphan')


class AmenityBooking(db.Model):
    __tablename__ = 'amenity_bookings'
    id = db.Column(db.Integer, primary_key=True)
    amenity_id = db.Column(db.Integer, db.ForeignKey('amenities.id'), nullable=False)
    resident_id = db.Column(db.Integer, db.ForeignKey('residents.id'), nullable=False)
    booking_date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    purpose = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(20), default='Pending', nullable=False)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    amenity = db.relationship('Amenity', back_populates='bookings')
    resident = db.relationship('Resident', back_populates='amenity_bookings')
    reviewed_by = db.relationship('User', foreign_keys=[reviewed_by_id], lazy=True)


class Notice(db.Model):
    __tablename__ = 'notices'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    content = db.Column(db.Text, nullable=False)
    notice_type = db.Column(db.String(50), default='General')  # General, Urgent, Maintenance, Billing, etc.
    is_pinned = db.Column(db.Boolean, default=False)
    priority = db.Column(db.String(20), default='Normal')  # Normal, High, Urgent
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Feedback(db.Model):
    __tablename__ = 'feedback'
    id = db.Column(db.Integer, primary_key=True)
    resident_id = db.Column(db.Integer, db.ForeignKey('residents.id'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text, nullable=True)
    category = db.Column(db.String(50), default='General')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    resident = db.relationship('Resident', back_populates='feedbacks', lazy=True)


class Survey(db.Model):
    __tablename__ = 'surveys'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class SurveyResponse(db.Model):
    __tablename__ = 'survey_responses'
    id = db.Column(db.Integer, primary_key=True)
    survey_id = db.Column(db.Integer, db.ForeignKey('surveys.id'), nullable=False)
    resident_id = db.Column(db.Integer, db.ForeignKey('residents.id'), nullable=False)
    response = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class EmergencyAlert(db.Model):
    __tablename__ = 'emergency_alerts'
    id = db.Column(db.Integer, primary_key=True)
    alert_type = db.Column(db.String(50), default='Emergency')
    message = db.Column(db.Text, nullable=False)
    severity = db.Column(db.String(20), default='High')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    acknowledgements = db.relationship('EmergencyAlertAcknowledgement', backref='alert', lazy=True, cascade='all, delete-orphan')


class EmergencyAlertAcknowledgement(db.Model):
    __tablename__ = 'emergency_alert_acknowledgements'
    id = db.Column(db.Integer, primary_key=True)
    alert_id = db.Column(db.Integer, db.ForeignKey('emergency_alerts.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    acknowledged_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref=db.backref('emergency_acknowledgements', lazy=True))
    __table_args__ = (db.UniqueConstraint('alert_id', 'user_id', name='uq_emergency_alert_user'),)


class Notification(db.Model):
    __tablename__ = 'notifications'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    message = db.Column(db.Text, nullable=False)
    target_url = db.Column(db.String(500), nullable=True)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref=db.backref('notifications', lazy=True))


class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    action = db.Column(db.String(120), nullable=False)
    details = db.Column(db.Text, nullable=True)
    owner_name = db.Column(db.String(120), nullable=True)
    resident_name = db.Column(db.String(120), nullable=True)
    flat_number = db.Column(db.String(40), nullable=True)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Setting(db.Model):
    __tablename__ = 'settings'
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(80), unique=True, nullable=False)
    value = db.Column(db.String(255), nullable=False)


def seed_data():
    # Ensure essential roles exist (idempotent)
    existing = {r.name for r in Role.query.all()}
    required = {
        'Super Admin': 'Platform owner',
        'Society Admin': 'Society administrator',
        'Owner': 'Property owner',
        'Resident': 'Society resident',
        'Security Guard': 'Security coverage',
        'Maintenance Staff': 'Maintenance team',
    }
    for name, desc in required.items():
        if name not in existing:
            db.session.add(Role(name=name, description=desc))
    db.session.commit()

    from werkzeug.security import generate_password_hash
    admin_role = Role.query.filter_by(name='Super Admin').first()
    admin_user = User.query.filter((User.username == 'admin') | (User.email == 'admin') | (User.email == 'admin@digitalsociety.local')).first()

    if admin_user is None:
        admin_user = User(username='admin', email='admin', password_hash=generate_password_hash('admin123'), first_name='System', last_name='Admin', phone='9999999999', role_id=admin_role.id, is_verified=True, is_approved=True, is_active=True)
        db.session.add(admin_user)
    else:
        admin_user.username = 'admin'
        admin_user.email = 'admin'
        if not admin_user.password_hash:
            admin_user.password_hash = generate_password_hash('admin123')
        admin_user.first_name = 'System'
        admin_user.last_name = 'Admin'
        admin_user.phone = '9999999999'
        admin_user.role_id = admin_role.id
        admin_user.is_verified = True
        admin_user.is_approved = True
        admin_user.is_active = True
        db.session.add(admin_user)
    db.session.commit()

    if Amenity.query.count() == 0:
        db.session.add_all([
            Amenity(name='Gym', description='Fitness room for society residents.', location='Clubhouse', capacity=20, opening_time=datetime.strptime('06:00', '%H:%M').time(), closing_time=datetime.strptime('22:00', '%H:%M').time(), created_by_id=admin_user.id),
            Amenity(name='Community Hall', description='Multi-purpose space for meetings and gatherings.', location='Ground Floor', capacity=100, opening_time=datetime.strptime('08:00', '%H:%M').time(), closing_time=datetime.strptime('22:00', '%H:%M').time(), created_by_id=admin_user.id),
            Amenity(name='Event Hall', description='Reserve the main hall for society events.', location='Main Building', capacity=150, opening_time=datetime.strptime('09:00', '%H:%M').time(), closing_time=datetime.strptime('23:00', '%H:%M').time(), created_by_id=admin_user.id),
        ])
        db.session.commit()

    if ComplaintCategory.query.count() == 0:
        categories = [ComplaintCategory(name='Electrical'), ComplaintCategory(name='Water'), ComplaintCategory(name='Security'), ComplaintCategory(name='Cleaning'), ComplaintCategory(name='Parking'), ComplaintCategory(name='Lift'), ComplaintCategory(name='Others')]
        db.session.add_all(categories)
        db.session.commit()

    # No sample buildings, flats, residents, or surveys are created by default.
    # Resident data is only created when a real user registers.

    if Notice.query.count() == 0:
        notice = Notice(title='Welcome to Digital Society', content='Please keep the premises clean and report issues promptly.', notice_type='General', is_pinned=True, created_by_id=1)
        db.session.add(notice)
        db.session.commit()
