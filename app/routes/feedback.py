from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from app import db
from app.notification_service import notify_admins
from app.models import Feedback, Resident

feedback_bp = Blueprint('feedback', __name__)


@feedback_bp.route('/')
@login_required
def index():
    feedbacks = Feedback.query.order_by(Feedback.created_at.desc()).all()
    return render_template('feedback/index.html', feedbacks=feedbacks)


@feedback_bp.route('/submit', methods=['GET', 'POST'])
@login_required
def submit_feedback():
    if request.method == 'POST':
        resident = Resident.query.filter_by(user_id=current_user.id).first()
        feedback = Feedback(resident_id=resident.id, rating=request.form.get('rating', 5, type=int), comment=request.form.get('comment'), category=request.form.get('category'))
        db.session.add(feedback)
        db.session.commit()
        notify_admins(
            'New resident feedback',
            f'{current_user.first_name or current_user.username} submitted {feedback.category or "general"} feedback ({feedback.rating}/5).',
        )
        flash('Feedback submitted', 'success')
        return redirect(url_for('feedback.index'))
    return render_template('feedback/submit.html')
