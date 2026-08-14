from app.database import engine, Base
from app.models import ClientModel, AuditLogModel

def init_db():
    print("Initializing NexusFlow local SQLite database...")
    Base.metadata.create_all(bind=engine)
    print("Database tables created successfully: clients, audit_logs.")

if __name__ == "__main__":
    init_db()