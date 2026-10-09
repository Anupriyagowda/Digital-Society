from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app import db
from app.models import MarketplaceListing


marketplace_bp = Blueprint('marketplace', __name__)
CATEGORIES = ('Sale', 'Rent', 'Service', 'Free', 'Other')


def can_moderate():
    return current_user.role and current_user.role.name in {'Super Admin', 'Society Admin', 'Owner'}


@marketplace_bp.route('/')
@login_required
def index():
    query = MarketplaceListing.query.filter_by(status='Available')
    category = request.args.get('category', '').strip()
    if category in CATEGORIES:
        query = query.filter_by(category=category)
    listings = query.order_by(MarketplaceListing.created_at.desc()).all()
    return render_template('marketplace/index.html', listings=listings, categories=CATEGORIES, selected_category=category, can_moderate=can_moderate())


@marketplace_bp.route('/create', methods=['POST'])
@login_required
def create():
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    category = request.form.get('category', '').strip()
    price_text = request.form.get('price', '').strip()
    if not title or not description or category not in CATEGORIES:
        flash('Title, description, and a valid category are required.', 'warning')
        return redirect(url_for('marketplace.index'))
    try:
        price = float(price_text) if price_text else None
        if price is not None and price < 0:
            raise ValueError
    except ValueError:
        flash('Enter a valid non-negative price.', 'warning')
        return redirect(url_for('marketplace.index'))
    db.session.add(MarketplaceListing(title=title, description=description, category=category, price=price, contact_note=request.form.get('contact_note', '').strip() or None, seller_id=current_user.id))
    db.session.commit()
    flash('Marketplace listing published.', 'success')
    return redirect(url_for('marketplace.index'))


@marketplace_bp.route('/<int:listing_id>/status', methods=['POST'])
@login_required
def update_status(listing_id):
    listing = MarketplaceListing.query.get_or_404(listing_id)
    if listing.seller_id != current_user.id and not can_moderate():
        flash('You can only update your own listings.', 'danger')
        return redirect(url_for('marketplace.index'))
    status = request.form.get('status')
    if status not in {'Available', 'Sold', 'Removed'}:
        flash('Invalid listing status.', 'warning')
    else:
        listing.status = status
        db.session.commit()
        flash('Listing status updated.', 'success')
    return redirect(url_for('marketplace.index'))