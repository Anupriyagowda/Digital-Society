import logging
from flask import Flask, Response, redirect, url_for, request
from flask_login import LoginManager, current_user
from flask_mail import Mail
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import inspect, text

from .config import Config


mail = Mail()
db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'auth.admin_login'
login_manager.login_message_category = 'info'
csrf = CSRFProtect()


def configure_request_logging():
    logging.basicConfig(level=logging.INFO)


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    configure_request_logging()

    @app.route('/favicon.ico')
    def favicon():
        return Response(status=204)

    mail.init_app(app)
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    csrf.init_app(app)

    from app.models import User, seed_data

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    @app.context_processor
    def inject_globals():
        emergency_alert = None
        if current_user.is_authenticated:
            from app.models import EmergencyAlert
            emergency_alert = EmergencyAlert.query.filter(
                ~EmergencyAlert.acknowledgements.any(user_id=current_user.id)
            ).order_by(EmergencyAlert.created_at.desc()).first()
        return {'current_user': current_user, 'emergency_alert': emergency_alert}

    @app.after_request
    def log_response(response):
        if response.mimetype == 'text/html' and (
            current_user.is_authenticated or request.endpoint == 'auth.logout'
        ):
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
        app.logger.info('%s %s %s %s', request.remote_addr, request.method, request.path, response.status)
        return response

    @app.before_request
    def create_bill_reminders():
        if not current_user.is_authenticated or not current_user.role or current_user.role.name != 'Resident':
            return
        from app.models import Resident
        from app.notification_service import process_bill_reminders

        resident = Resident.query.filter_by(user_id=current_user.id).first()
        if resident:
            process_bill_reminders(resident=resident)

    from app.routes.auth import auth_bp
    from app.routes.main import main_bp
    from app.routes.admin import admin_bp
    from app.routes.owner import owner_bp
    from app.routes.resident import resident_bp

    csrf.exempt(auth_bp)
    from app.routes.security import security_bp
    from app.routes.maintenance import maintenance_bp
    from app.routes.billing import billing_bp
    from app.routes.complaint import complaint_bp
    from app.routes.notice import notice_bp
    from app.routes.event import event_bp
    from app.routes.feedback import feedback_bp
    from app.routes.api import api_bp
    from app.routes.chatbot import chatbot_bp
    from app.routes.notifications import notifications_bp
    from app.routes.emergency import emergency_bp
    from app.routes.meetings import meetings_bp
    from app.routes.marketplace import marketplace_bp

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp, url_prefix='/admin')
    # Ensure Flask-Login uses the admin-specific login view for the admin blueprint
    try:
        login_manager.blueprint_login_views['admin'] = 'auth.admin_login'
    except Exception:
        pass
    app.register_blueprint(owner_bp, url_prefix='/owner')
    app.register_blueprint(resident_bp, url_prefix='/resident')
    app.register_blueprint(security_bp, url_prefix='/security')
    app.register_blueprint(maintenance_bp, url_prefix='/maintenance')
    app.register_blueprint(billing_bp, url_prefix='/billing')
    app.register_blueprint(complaint_bp, url_prefix='/complaints')
    app.register_blueprint(notice_bp, url_prefix='/notices')
    app.register_blueprint(event_bp, url_prefix='/events')
    app.register_blueprint(feedback_bp, url_prefix='/feedback')
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(chatbot_bp, url_prefix='/api')
    app.register_blueprint(notifications_bp, url_prefix='/notifications')
    app.register_blueprint(emergency_bp, url_prefix='/emergency')
    app.register_blueprint(meetings_bp, url_prefix='/meetings')
    app.register_blueprint(marketplace_bp, url_prefix='/marketplace')

    with app.app_context():
        db.create_all()
        inspector = inspect(db.engine)

        user_columns = {column['name'] for column in inspector.get_columns('users')}
        if 'avatar_url' not in user_columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE users ADD COLUMN avatar_url VARCHAR(255)"))
        if 'is_approved' not in user_columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE users ADD COLUMN is_approved BOOLEAN NOT NULL DEFAULT 0"))
            with db.engine.begin() as connection:
                connection.execute(text("UPDATE users SET is_approved = 1 WHERE username = 'admin'"))
        if 'is_active' not in user_columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE users ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1"))
            with db.engine.begin() as connection:
                connection.execute(text("UPDATE users SET is_active = 1 WHERE username = 'admin'"))

        notification_columns = {column['name'] for column in inspector.get_columns('notifications')}
        if 'target_url' not in notification_columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE notifications ADD COLUMN target_url VARCHAR(500)"))

        resident_columns = {column['name'] for column in inspector.get_columns('residents')}
        if 'approval_status' not in resident_columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE residents ADD COLUMN approval_status VARCHAR(20) DEFAULT 'Pending'"))
        if 'approved_by_id' not in resident_columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE residents ADD COLUMN approved_by_id INTEGER"))
        if 'approval_date' not in resident_columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE residents ADD COLUMN approval_date DATETIME"))
        if 'resident_type' not in resident_columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE residents ADD COLUMN resident_type VARCHAR(20)"))

        event_columns = {column['name'] for column in inspector.get_columns('events')}
        if 'created_by_id' not in event_columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE events ADD COLUMN created_by_id INTEGER NOT NULL DEFAULT 1"))
        if 'max_capacity' not in event_columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE events ADD COLUMN max_capacity INTEGER DEFAULT 100"))
        if 'event_type' not in event_columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE events ADD COLUMN event_type VARCHAR(50) DEFAULT 'General'"))
        if 'status' not in event_columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE events ADD COLUMN status VARCHAR(20) DEFAULT 'Active'"))

        activity_columns = {column['name'] for column in inspector.get_columns('activities')}
        if 'event_id' not in activity_columns:
            with db.engine.begin() as connection:
                connection.execute(text('ALTER TABLE activities ADD COLUMN event_id INTEGER'))
        if 'cancel_reason' not in activity_columns:
            # no-op for activities, preserve schema if missing participant reasons.
            pass

        participant_columns = {column['name'] for column in inspector.get_columns('participants')}
        if 'cancel_reason' not in participant_columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE participants ADD COLUMN cancel_reason VARCHAR(255)"))
        if 'cancelled_at' not in participant_columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE participants ADD COLUMN cancelled_at DATETIME"))

        complaint_columns = {column['name'] for column in inspector.get_columns('complaints')}
        if 'category_id' in complaint_columns:
            complaint_info = next(column for column in inspector.get_columns('complaints') if column['name'] == 'category_id')
            if complaint_info.get('nullable') is False:
                with db.engine.begin() as connection:
                    connection.execute(text("ALTER TABLE complaints RENAME TO complaints_old"))
                    connection.execute(text("""
                        CREATE TABLE complaints (
                            id INTEGER NOT NULL,
                            title VARCHAR(120) NOT NULL,
                            description TEXT NOT NULL,
                            category_id INTEGER,
                            resident_id INTEGER NOT NULL,
                            assigned_to_id INTEGER,
                            status VARCHAR(20),
                            priority VARCHAR(20),
                            created_at DATETIME,
                            PRIMARY KEY (id),
                            FOREIGN KEY(category_id) REFERENCES complaint_categories(id),
                            FOREIGN KEY(resident_id) REFERENCES residents(id),
                            FOREIGN KEY(assigned_to_id) REFERENCES users(id)
                        )
                    """))
                    connection.execute(text("""
                        INSERT INTO complaints (id, title, description, category_id, resident_id, assigned_to_id, status, priority, created_at)
                        SELECT id, title, description, category_id, resident_id, assigned_to_id, status, priority, created_at
                        FROM complaints_old
                    """))
                    connection.execute(text("DROP TABLE complaints_old"))

        notice_columns = {column['name'] for column in inspector.get_columns('notices')}
        if 'priority' not in notice_columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE notices ADD COLUMN priority VARCHAR(20) DEFAULT 'Normal'"))
        if 'expires_at' not in notice_columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE notices ADD COLUMN expires_at DATETIME"))

        visitor_columns = {column['name'] for column in inspector.get_columns('visitors')}
        if 'flat_number' not in visitor_columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE visitors ADD COLUMN flat_number VARCHAR(40)"))
        if 'entry_time' not in visitor_columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE visitors ADD COLUMN entry_time DATETIME"))

        bill_columns = {column['name'] for column in inspector.get_columns('bills')}
        if 'resident_name' not in bill_columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE bills ADD COLUMN resident_name VARCHAR(120)"))
        if 'flat_number' not in bill_columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE bills ADD COLUMN flat_number VARCHAR(40)"))
        if 'payment_status' not in bill_columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE bills ADD COLUMN payment_status VARCHAR(20) DEFAULT 'Pending'"))
        if 'payment_date' not in bill_columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE bills ADD COLUMN payment_date DATE"))
        if 'billing_period' not in bill_columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE bills ADD COLUMN billing_period VARCHAR(7)"))
        if 'is_automatic' not in bill_columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE bills ADD COLUMN is_automatic BOOLEAN NOT NULL DEFAULT 0"))

        payment_columns = {column['name'] for column in inspector.get_columns('payments')}
        if 'razorpay_order_id' not in payment_columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE payments ADD COLUMN razorpay_order_id VARCHAR(80)"))
        if 'razorpay_payment_id' not in payment_columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE payments ADD COLUMN razorpay_payment_id VARCHAR(80)"))

        audit_columns = {column['name'] for column in inspector.get_columns('audit_logs')}
        if 'owner_name' not in audit_columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE audit_logs ADD COLUMN owner_name VARCHAR(120)"))
        if 'resident_name' not in audit_columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE audit_logs ADD COLUMN resident_name VARCHAR(120)"))
        if 'flat_number' not in audit_columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE audit_logs ADD COLUMN flat_number VARCHAR(40)"))
        if 'description' not in audit_columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE audit_logs ADD COLUMN description TEXT"))

        seed_data()
    return app

