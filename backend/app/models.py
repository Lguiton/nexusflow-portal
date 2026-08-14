from sqlalchemy import Column, String, Float, DateTime, Integer
from datetime import datetime
from app.database import Base

class ClientModel(Base):
    __tablename__ = "clients"

    client_id = Column(String, primary_key=True, index=True)
    mrr = Column(Float, nullable=False, default=0.0)
    status = Column(String, default="active")
    signup_date = Column(String, default=lambda: datetime.utcnow().strftime("%Y-%m-%d"))

class AuditLogModel(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    task_type = Column(String, nullable=False)
    status = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)