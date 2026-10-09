from app import create_app

app = create_app()
print(app.config['SQLALCHEMY_DATABASE_URI'])
print(app.extensions['sqlalchemy'].db.engine.url)
with app.app_context():
    from app import db
    print('tables', sorted(db.engine.table_names()))
