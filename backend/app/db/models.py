from sqlalchemy import Column, String, DateTime, Boolean, Enum
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
import enum
from app.db.session import Base

class ClientTier(str, enum.Enum):
    CORE_PORTAL = "CORE_PORTAL"
    GROWTH_OPTIMIZATION = "GROWTH_OPTIMIZATION"
    ENTERPRISE_OPS = "ENTERPRISE_OPS"

class ClientOrg(Base):
    __tablename__ = "client_orgs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_name = Column(String(255), nullable=False)
    contact_email = Column(String(255), unique=True, nullable=False)
    tier = Column(Enum(ClientTier), default=ClientTier.CORE_PORTAL, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
