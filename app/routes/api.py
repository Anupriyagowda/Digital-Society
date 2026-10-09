from flask import Blueprint, jsonify
from app.models import Resident, Visitor, Complaint, Bill, Payment, MaintenanceRequest, Notice, Event, Feedback

api_bp = Blueprint('api', __name__)


@api_bp.route('/residents')
def residents_api():
    data = [{'id': r.id, 'name': f'{r.user.first_name} {r.user.last_name}', 'status': r.status} for r in Resident.query.all()]
    return jsonify(data)


@api_bp.route('/visitors')
def visitors_api():
    data = [{'id': v.id, 'name': v.full_name, 'status': v.status} for v in Visitor.query.all()]
    return jsonify(data)


@api_bp.route('/complaints')
def complaints_api():
    data = [{'id': c.id, 'title': c.title, 'status': c.status} for c in Complaint.query.all()]
    return jsonify(data)


@api_bp.route('/bills')
def bills_api():
    data = [{'id': b.id, 'type': b.bill_type, 'amount': b.amount, 'status': b.status} for b in Bill.query.all()]
    return jsonify(data)
