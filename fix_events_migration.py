from app import create_app, db
from sqlalchemy import inspect, text

app = create_app()
with app.app_context():
    inspector = inspect(db.engine)
    event_columns = {c['name'] for c in inspector.get_columns('events')}
    stmts = []
    if 'created_by_id' not in event_columns:
        stmts.append("ALTER TABLE events ADD COLUMN created_by_id INTEGER NOT NULL DEFAULT 1")
    if 'max_capacity' not in event_columns:
        stmts.append("ALTER TABLE events ADD COLUMN max_capacity INTEGER DEFAULT 100")
    if 'event_type' not in event_columns:
        stmts.append("ALTER TABLE events ADD COLUMN event_type VARCHAR(50) DEFAULT 'General'")
    if 'status' not in event_columns:
        stmts.append("ALTER TABLE events ADD COLUMN status VARCHAR(20) DEFAULT 'Active'")

    if not stmts:
        print('No migration needed')
    else:
        with db.engine.begin() as conn:
            for s in stmts:
                print('Executing:', s)
                conn.execute(text(s))
        inspector = inspect(db.engine)
        print('Now events columns:', sorted({c['name'] for c in inspector.get_columns('events')}))
