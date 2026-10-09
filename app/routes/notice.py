from flask import Blueprint, render_template
from flask_login import login_required

from app.models import Notice

notice_bp = Blueprint('notice', __name__)


@notice_bp.route('/')
@login_required
def index():
    notices = Notice.query.order_by(Notice.created_at.desc()).all()
    return render_template('notice/index.html', notices=notices)
