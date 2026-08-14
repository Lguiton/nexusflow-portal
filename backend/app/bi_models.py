from sqlalchemy import Column, String, Float, Integer, DateTime
from datetime import datetime
from app.database import Base

class ExecutiveMetricModel(Base):
    __tablename__ = "executive_metrics"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    metric_name = Column(String, nullable=False)
    metric_value = Column(Float, nullable=False)
    leak_detected = Column(Float, default=0.0)
    updated_at = Column(DateTime, default=datetime.utcnow)