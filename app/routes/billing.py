from datetime import datetime

import razorpay
from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for, send_file
from flask_login import current_user, login_required

from app import db
from app.billing_service import generate_current_month_bills
from app.notification_service import notify_admins, notify_user, process_bill_reminders
from app.notification_service import email_admins, email_user
from app.models import Bill, Payment, Resident
from app.pdf_service import build_pdf, preview_or_download

billing_bp = Blueprint('billing', __name__)


def get_razorpay_client():
    return razorpay.Client(
        auth=(
            current_app.config['RAZORPAY_KEY_ID'],
            current_app.config['RAZORPAY_KEY_SECRET'],
        )
    )


@billing_bp.route('/create-order/<int:bill_id>', methods=['POST'])
@login_required
def create_order(bill_id):
    resident = Resident.query.filter_by(user_id=current_user.id).first_or_404()
    bill = Bill.query.filter_by(id=bill_id, resident_id=resident.id).first_or_404()

    if bill.payment_status == 'Paid':
        return jsonify({'error': 'Bill is already paid'}), 400

    amount_paise = int(round(bill.amount * 100))
    if amount_paise <= 0:
        return jsonify({'error': 'Bill amount must be greater than zero'}), 400

    order = get_razorpay_client().order.create({
        'amount': amount_paise,
        'currency': 'INR',
        'receipt': f'bill_{bill.id}',
        'notes': {
            'bill_id': str(bill.id),
            'resident_id': str(resident.id),
        },
    })

    payment = Payment(
        bill_id=bill.id,
        resident_id=resident.id,
        amount=bill.amount,
        payment_method='Razorpay',
        status='Pending',
        razorpay_order_id=order['id'],
    )
    db.session.add(payment)
    db.session.commit()

    return jsonify({
        'order_id': order['id'],
        'amount': amount_paise,
        'currency': 'INR',
        'key_id': current_app.config['RAZORPAY_KEY_ID'],
    })


@billing_bp.route('/verify-payment', methods=['POST'])
@login_required
def verify_payment():
    data = request.get_json(silent=True) or {}
    required_fields = (
        'bill_id',
        'razorpay_order_id',
        'razorpay_payment_id',
        'razorpay_signature',
    )
    if not all(data.get(field) for field in required_fields):
        return jsonify({'error': 'Incomplete payment data'}), 400

    resident = Resident.query.filter_by(user_id=current_user.id).first_or_404()
    bill = Bill.query.filter_by(
        id=data['bill_id'],
        resident_id=resident.id,
    ).first_or_404()
    payment = Payment.query.filter_by(
        bill_id=bill.id,
        resident_id=resident.id,
        razorpay_order_id=data['razorpay_order_id'],
    ).first()

    if not payment:
        return jsonify({'error': 'Payment order not found'}), 400
    if bill.payment_status == 'Paid':
        return jsonify({'message': 'Payment already recorded'})

    try:
        get_razorpay_client().utility.verify_payment_signature({
            'razorpay_order_id': data['razorpay_order_id'],
            'razorpay_payment_id': data['razorpay_payment_id'],
            'razorpay_signature': data['razorpay_signature'],
        })
    except razorpay.errors.SignatureVerificationError:
        return jsonify({'error': 'Payment verification failed'}), 400

    payment.status = 'Paid'
    payment.transaction_id = data['razorpay_payment_id']
    payment.razorpay_payment_id = data['razorpay_payment_id']
    bill.status = 'Paid'
    bill.payment_status = 'Paid'
    bill.payment_date = datetime.utcnow().date()
    notify_user(
        resident.user_id,
        'Payment successful',
        f'Your Razorpay payment of Rs {bill.amount:,.2f} for {bill.bill_type} was successful.',
        url_for('resident.download_bill', bill_id=bill.id, preview=1),
    )
    notify_admins(
        'Payment successful',
        f'{resident.user.first_name or resident.user.username} paid Rs {bill.amount:,.2f} for {bill.bill_type}.',
        target_urls={
            'Super Admin': url_for('admin.dashboard'),
            'Society Admin': url_for('admin.dashboard'),
            'Owner': url_for('owner.report_bills', status='paid'),
        },
    )
    db.session.commit()
    receipt_url = url_for('billing.payment_receipt', payment_id=payment.id, _external=True)
    bill_url = url_for('resident.download_bill', bill_id=bill.id, _external=True)
    resident_name = resident.user.first_name or resident.user.username
    email_user(
        resident.user,
        f'Payment receipt: {bill.bill_type}',
        f'Hello {resident_name},\n\n'
        f'Your Razorpay payment of Rs {bill.amount:,.2f} for {bill.bill_type} was verified successfully.\n'
        f'Transaction ID: {payment.transaction_id}\n\n'
        f'Payment receipt (sign in required): {receipt_url}\n'
        f'Bill (sign in required): {bill_url}\n\n'
        'Digital Society',
    )
    email_admins(
        'Payment successful',
        f'{resident_name} paid Rs {bill.amount:,.2f} for {bill.bill_type}.',
    )

    return jsonify({'message': 'Payment successful'})


@billing_bp.route('/payment-failed', methods=['POST'])
@login_required
def payment_failed():
    data = request.get_json(silent=True) or {}
    resident = Resident.query.filter_by(user_id=current_user.id).first_or_404()
    bill = Bill.query.filter_by(
        id=data.get('bill_id'),
        resident_id=resident.id,
    ).first_or_404()
    notify_user(
        resident.user_id,
        'Razorpay payment failed',
        f'Your payment for {bill.bill_type} of Rs {bill.amount:,.2f} failed or was cancelled. The bill remains unpaid.',
        url_for('resident.download_bill', bill_id=bill.id, preview=1),
    )
    db.session.commit()
    return jsonify({'message': 'Payment failure recorded'})


@billing_bp.route('/')
@login_required
def index():
    generate_current_month_bills()
    resident = Resident.query.filter_by(user_id=current_user.id).first()
    if not resident:
        flash('No resident profile found.', 'warning')
        return redirect(url_for('main.dashboard'))
    process_bill_reminders(resident=resident)

    bills = Bill.query.filter_by(resident_id=resident.id).order_by(Bill.created_at.desc()).all()
    if resident.resident_type == 'Flat Owner':
        bill_heading = 'Maintenance Billing'
        bill_description = 'Maintenance and service charges for your flat.'
    else:
        bill_heading = 'Monthly Billing'
        bill_description = 'Utility and society bills for your residence.'

    payments = Payment.query.filter(
        Payment.resident_id == resident.id,
        Payment.razorpay_payment_id.isnot(None),
        Payment.status == 'Paid',
    ).order_by(Payment.created_at.desc()).all()
    paid_payments = {
        payment.bill_id: payment
        for payment in Payment.query.filter_by(
            resident_id=resident.id,
            status='Paid',
        ).all()
    }
    last_payment = payments[0] if payments else None
    return render_template(
        'billing/index.html',
        resident=resident,
        bills=bills,
        paid_payments=paid_payments,
        payments=payments,
        last_payment=last_payment,
        bill_heading=bill_heading,
        bill_description=bill_description,
    )


@billing_bp.route('/payment/<int:payment_id>/receipt')
@login_required
def payment_receipt(payment_id):
    resident = Resident.query.filter_by(user_id=current_user.id).first_or_404()
    payment = Payment.query.filter_by(id=payment_id, resident_id=resident.id, status='Paid').first_or_404()
    bill = Bill.query.get_or_404(payment.bill_id)
    pdf = build_pdf('Payment Receipt', [('Payment details', [
        ('Resident', resident.user.first_name or resident.user.username),
        ('Bill type', bill.bill_type),
        ('Amount', f'Rs {payment.amount:,.2f}'),
        ('Payment method', payment.payment_method),
        ('Transaction ID', payment.transaction_id or payment.razorpay_payment_id),
        ('Payment date', payment.created_at.strftime('%Y-%m-%d %H:%M') if payment.created_at else '-'),
        ('Status', payment.status),
    ])])
    return preview_or_download(pdf, f'payment-receipt-{payment.id}.pdf', 'Payment Receipt')


