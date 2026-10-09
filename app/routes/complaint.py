from flask import Blueprint, render_template
from flask_login import login_required

from app.models import Complaint

complaint_bp = Blueprint('complaint', __name__)


@complaint_bp.route('/')
@login_required
def index():
    complaints = Complaint.query.order_by(Complaint.created_at.desc()).all()
    return render_template('complaint/index.html', complaints=complaints)
