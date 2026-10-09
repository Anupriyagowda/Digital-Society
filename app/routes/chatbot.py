from difflib import get_close_matches

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from app.models import Bill, Resident


chatbot_bp = Blueprint('chatbot', __name__)


FAQ_RESPONSES = {
    'maintenance': 'Open Maintenance from the sidebar, describe the issue, and submit the request. You can track its status there.',
    'complaint': 'Open Complaints from the sidebar, enter the subject and details, then submit your complaint to the society team.',
    'visitor': 'Open Visitor Requests to review visitor requests. You can approve or reject a request from that page.',
    'notice': 'Open Notices from the sidebar to read society announcements and service updates.',
    'event': 'Open Events to view upcoming society events and register when registration is available.',
}

CHATBOT_VOCABULARY = {
    'amount', 'assistant', 'bill', 'bills', 'cancel', 'cancellation',
    'charge', 'charged', 'complaint', 'event', 'events', 'failed', 'fee',
    'generate', 'generated', 'help', 'maintenance', 'monthly', 'notice',
    'notices', 'payment', 'pay', 'razorpay', 'register', 'registered',
    'registration', 'rent', 'support', 'unable', 'visitor', 'visitors',
    'what', 'when', 'where', 'why', 'how', 'much', 'wrong', 'incorrect',
    'overcharged', 'cannot', 'cant', 'again', 'manage', 'review', 'reply',
    'respond', 'resolve', 'status', 'assign', 'approve', 'reject', 'profile',
    'account', 'login', 'password', 'register', 'create', 'delete', 'edit',
}


def _resident():
    if getattr(current_user, 'role', None) and current_user.role.name == 'Resident':
        return Resident.query.filter_by(user_id=current_user.id).first()
    return None


def _billing_response(resident):
    if not resident:
        return 'I can explain the billing process, but I could not find a resident profile for this account.'

    bills = Bill.query.filter_by(
        resident_id=resident.id,
        payment_status='Pending',
    ).order_by(Bill.due_date.asc()).all()
    if not bills:
        return 'You have no pending bills. Open Billing to view your completed Razorpay payment history.'

    bill_lines = [
        f'{bill.bill_type}: Rs {bill.amount:,.2f} (due {bill.due_date.strftime("%d %b %Y") if bill.due_date else "date not set"})'
        for bill in bills[:5]
    ]
    return 'Your pending bills are: ' + '; '.join(bill_lines) + '. Open Billing and choose Pay with Razorpay.'


def _manual_billing_response():
    if _is_admin():
        return 'To create a manual bill, open Residents, select the resident, open their billing section, choose Monthly Rent for a tenant or Maintenance Charges for a flat owner, enter the exact amount and due date, then save. A manual maintenance charge appears immediately and remains separate from the monthly bill.'
    return 'Manual bills are created by the society administrator. If you have a question about a charge, submit a complaint so the administrator can review it.'


def _automatic_billing_response():
    if _is_admin():
        return 'Automatic billing creates one bill each month on the configured day. Tenants receive Monthly Rent and flat owners receive Maintenance Charges. The default tenant rent is configured in .env. Use manual billing when a separate maintenance charge has a different amount.'
    return 'Your monthly bill is generated automatically by the society system. Open Billing after the configured date to view it and choose Pay with Razorpay.'


def _topic_response(topic):
    admin_responses = {
        'complaint': 'To manage complaints, open Complaints from the administrator sidebar. Open a complaint to read the resident details, assign it to staff, update its status, and add the resolution or response.',
        'maintenance': 'To manage maintenance requests, open Maintenance from the administrator sidebar. Review the request, open its details, assign staff, update the status, and add progress notes for the resident.',
        'visitor': 'To manage visitor requests, open Visitor Management. Review visitor details, allow or reject entry when appropriate, and check visitors in or out.',
        'notice': 'To manage notices, open Notices from the administrator sidebar. You can create, edit, publish, pin, and remove society announcements.',
        'event': 'To manage events, open Events from the administrator sidebar. You can create, edit, cancel, delete events, manage capacity, and review registrations.',
        'resident': 'To manage residents, open Residents. You can approve or reject registrations, edit resident details, manage billing, and view resident activity.',
        'feedback': 'To review resident feedback, open Feedback from the administrator dashboard. Use the submitted rating and comment to follow up with residents.',
        'profile': 'Open Profile to update the signed-in account details. Account access and password problems should be handled through the login or password-reset pages.',
    }
    resident_responses = {
        'complaint': 'Open Complaints, enter the subject and details, and submit it to the society team. The administrator can review and update its status.',
        'maintenance': 'Open Maintenance, describe the issue, and submit the request. You can track its status there.',
        'visitor': 'Open Visitor Requests to review visitor requests. You can approve or reject a request from that page.',
        'notice': 'Open Notices to read society announcements and service updates.',
        'event': 'Open Events to view upcoming society events and register when registration is available.',
        'resident': 'Open Profile to view or update your account details. Residents can view only their own private information.',
        'feedback': 'Open Feedback to view feedback options and submit your rating or comment to the society team.',
        'profile': 'Open Profile to view or update your account details. Use the password-reset option if you cannot log in.',
    }
    return (admin_responses if _is_admin() else resident_responses).get(topic)


def _is_admin():
    role = getattr(current_user, 'role', None)
    return role and role.name in {'Super Admin', 'Society Admin', 'Owner'}


def _normalize_message(message):
    words = message.lower().split()
    corrected_words = []
    for word in words:
        stripped_word = word.strip('.,!?;:')
        stripped_word = {
            "can't": 'cant',
            "cannot": 'cannot',
        }.get(stripped_word, stripped_word)
        match = get_close_matches(stripped_word, CHATBOT_VOCABULARY, n=1, cutoff=0.78)
        corrected_words.append(match[0] if match else stripped_word)
    return ' '.join(corrected_words)


def _answer(message):
    normalized = _normalize_message(message)
    words = set(normalized.split())
    has_bill_topic = bool(words.intersection({'bill', 'bills', 'rent', 'payment', 'pay', 'razorpay'}))
    has_manual_topic = bool(words.intersection({'manual', 'manually', 'administrator', 'admin'}))
    has_generate_topic = bool(words.intersection({'generate', 'generated', 'create', 'monthly', 'automatic', 'auto'}))

    if words.intersection({'hello', 'hi', 'hey', 'help'}):
        return 'Hello. I can help with bills, Razorpay payments, maintenance, complaints, visitors, notices, and events.'
    if 'assistant' in words or 'what is this' in normalized:
        return 'I am the Society Assistant. I answer common society questions and guide residents and administrators to the correct portal feature.'
    if has_manual_topic and has_bill_topic and (has_generate_topic or 'manual' in words or 'manually' in words):
        return _manual_billing_response()
    if (has_generate_topic and has_bill_topic) or 'how are bills generated' in normalized:
        return _automatic_billing_response()
    if ('my' in words or 'pending' in words) and has_bill_topic:
        if _is_admin():
            return 'To view a resident bill, open Residents, select the resident, and open their billing details. Residents can view their own pending bills in Billing.'
        return _billing_response(_resident())
    if (words.intersection({'why', 'wrong', 'incorrect', 'overcharged'})
            and any(term in normalized for term in ('charg', 'amount', 'fee', 'rent', 'bill'))):
        if _resident():
            return 'This is a personal billing question. The society administrator must review the bill details and explain the amount. Please submit a complaint with the bill amount and your question.'
        return 'This is an account-specific billing question. Review the resident bill record and reply through the society support process.'
    if ('cancel' in words or 'cancellation' in words) and any(term in normalized for term in ('event', 'registration', 'registered')):
        if _is_admin():
            return 'To cancel an event as an administrator, open Events, select the event, choose Edit Event, change its status to Cancelled, and save. Review registrations and notify residents about the cancellation.'
        return 'Open Events, select the event you joined, and click Cancel Registration. Enter a cancellation reason and submit it. The society will record the cancellation.'
    if ('register' in words and words.intersection({'cannot', 'cant', 'unable', 'failed'})) or 'not able to register' in normalized or "can't able to register" in normalized:
        return 'Open Events and select the event. If registration is open and capacity is available, click Register for Event. If it is full or closed, contact the society administrator.'
    if ('register' in words or 'registration' in words) and 'event' in words:
        if _is_admin():
            return 'To manage event registrations, open Events, select the event, and review its registered residents and capacity. Residents register from the event details page.'
        return 'Open Events, select an active event, choose any available activity, and click Register for Event.'
    if 'how' in normalized and ('pay' in normalized or 'payment' in normalized):
        return 'Open Billing, click Pay with Razorpay, then choose UPI, card, or net banking. The bill changes to Paid only after payment verification.'
    if any(word in normalized for word in ('bill', 'rent', 'payment', 'pay', 'razorpay')):
        return _billing_response(_resident())
    topic_aliases = {
        'complaint': {'complaint', 'complaints', 'issue', 'issues', 'grievance'},
        'maintenance': {'maintenance', 'repair', 'repairs', 'plumber', 'leak', 'broken'},
        'visitor': {'visitor', 'visitors', 'guest', 'guests', 'entry'},
        'notice': {'notice', 'notices', 'announcement', 'announcements', 'circular'},
        'event': {'event', 'events', 'activity', 'activities', 'function'},
        'resident': {'resident', 'residents', 'tenant', 'tenants', 'owner', 'owners'},
        'feedback': {'feedback', 'rating', 'ratings', 'review', 'reviews'},
        'profile': {'profile', 'account', 'password', 'login', 'signin'},
    }
    topic_scores = {
        topic: len(words.intersection(aliases))
        for topic, aliases in topic_aliases.items()
    }
    best_topic = max(topic_scores, key=topic_scores.get)
    if topic_scores[best_topic]:
        return _topic_response(best_topic)
    if any(word in normalized for word in ('admin', 'administrator', 'human', 'support', 'problem')):
        return 'This needs the society administrator. Please submit a complaint or maintenance request with the details so the team can respond.'
    return 'I do not have an answer for that yet. Please ask about bills, payments, maintenance, complaints, visitors, notices, or events. For a personal issue, submit a complaint for the administrator.'


@chatbot_bp.route('/chatbot', methods=['POST'])
@login_required
def chatbot_message():
    data = request.get_json(silent=True) or {}
    message = (data.get('message') or '').strip()
    if not message:
        return jsonify({'error': 'Please enter a question.'}), 400
    if len(message) > 500:
        return jsonify({'error': 'Please keep your question under 500 characters.'}), 400
    return jsonify({'reply': _answer(message)})
