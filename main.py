# =============================================================================
# MK Underwood — Project Settlement Platform  (single-file backend)
# Stack: FastAPI · SQLAlchemy · PostgreSQL · Redis/RQ · Stripe · OpenAI · S3
# =============================================================================
import enum, json, os, time, uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional

import boto3, redis as redis_lib, stripe
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from openai import OpenAI
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from rq import Queue
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String,
    Text, UniqueConstraint, Enum as E, select, text,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession, async_sessionmaker, create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func
from starlette.middleware.base import BaseHTTPMiddleware


# ── Config ────────────────────────────────────────────────────────────────────
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    ENV: str = "development"
    PORT: int = 3000
    FRONTEND_URL: str = "http://localhost:5173"
    DATABASE_URL: str = "postgresql://localhost/mku"
    REDIS_URL: str = "redis://localhost:6379"
    JWT_SECRET: str = "dev_secret_change_me"
    JWT_REFRESH_SECRET: str = "dev_refresh_secret_change_me"
    JWT_EXPIRES_MINUTES: int = 15
    JWT_REFRESH_EXPIRES_DAYS: int = 30
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    PLATFORM_FEE_PERCENT: float = 1.5
    AWS_REGION: str = "us-east-1"
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_S3_BUCKET: str = ""
    OPENAI_API_KEY: str = ""
    SENDGRID_API_KEY: str = ""
    SENDGRID_FROM_EMAIL: str = "noreply@mkunderwood.com"
    SENDGRID_FROM_NAME: str = "MK Underwood"
    RATE_LIMIT_REQUESTS: int = 100
    RATE_LIMIT_WINDOW: int = 60

cfg = Settings()


# ── DB ────────────────────────────────────────────────────────────────────────
_db_url = cfg.DATABASE_URL.replace("postgres://","postgresql+asyncpg://").replace("postgresql://","postgresql+asyncpg://")
engine = create_async_engine(_db_url, pool_size=10, max_overflow=20, pool_pre_ping=True)
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

class Base(DeclarativeBase): pass

async def get_db():
    async with async_session() as s:
        try: yield s; await s.commit()
        except: await s.rollback(); raise

def uid(): return str(uuid.uuid4())


# ── Enums ─────────────────────────────────────────────────────────────────────
class UserRole(str, enum.Enum):
    HOMEOWNER="HOMEOWNER"; CONTRACTOR="CONTRACTOR"; ADMIN="ADMIN"
class UserStatus(str, enum.Enum):
    ACTIVE="ACTIVE"; SUSPENDED="SUSPENDED"; BANNED="BANNED"
class ProjectCategory(str, enum.Enum):
    ROOFING="ROOFING"; HVAC="HVAC"; KITCHEN_REMODEL="KITCHEN_REMODEL"
    BATHROOM_REMODEL="BATHROOM_REMODEL"; POOL_INSTALLATION="POOL_INSTALLATION"
    LANDSCAPING="LANDSCAPING"; ELECTRICAL="ELECTRICAL"; PLUMBING="PLUMBING"
    FLOORING="FLOORING"; PAINTING="PAINTING"; GENERAL_CONSTRUCTION="GENERAL_CONSTRUCTION"; OTHER="OTHER"
class ProjectStatus(str, enum.Enum):
    DRAFT="DRAFT"; AWAITING_FUNDING="AWAITING_FUNDING"; FUNDED="FUNDED"
    IN_PROGRESS="IN_PROGRESS"; COMPLETED="COMPLETED"; DISPUTED="DISPUTED"
    CANCELLED="CANCELLED"; REFUNDED="REFUNDED"
class MilestoneStatus(str, enum.Enum):
    PENDING="PENDING"; IN_PROGRESS="IN_PROGRESS"; SUBMITTED="SUBMITTED"
    AI_REVIEWING="AI_REVIEWING"; HOMEOWNER_REVIEW="HOMEOWNER_REVIEW"
    APPROVED="APPROVED"; DISPUTED="DISPUTED"; PAYMENT_RELEASED="PAYMENT_RELEASED"
class LedgerType(str, enum.Enum):
    ESCROW_FUNDED="ESCROW_FUNDED"; PLATFORM_FEE="PLATFORM_FEE"
    MILESTONE_RELEASED="MILESTONE_RELEASED"; PARTIAL_REFUND="PARTIAL_REFUND"
    FULL_REFUND="FULL_REFUND"; ADJUSTMENT="ADJUSTMENT"
class LedgerDir(str, enum.Enum):
    CREDIT="CREDIT"; DEBIT="DEBIT"
class EventType(str, enum.Enum):
    PROJECT_CREATED="PROJECT_CREATED"; CONTRACTOR_ASSIGNED="CONTRACTOR_ASSIGNED"
    ESCROW_FUNDED="ESCROW_FUNDED"; MILESTONE_SUBMITTED="MILESTONE_SUBMITTED"
    AI_DONE="AI_DONE"; MILESTONE_APPROVED="MILESTONE_APPROVED"
    PAYMENT_RELEASED="PAYMENT_RELEASED"; DISPUTE_OPENED="DISPUTE_OPENED"
    DISPUTE_RESOLVED="DISPUTE_RESOLVED"; PROJECT_COMPLETED="PROJECT_COMPLETED"
    PROJECT_CANCELLED="PROJECT_CANCELLED"; COMPANY_AUTO_LINKED="COMPANY_AUTO_LINKED"
class DisputeStatus(str, enum.Enum):
    OPEN="OPEN"; UNDER_REVIEW="UNDER_REVIEW"; RESOLVED="RESOLVED"
class DisputeOutcome(str, enum.Enum):
    FULL_RELEASE="FULL_RELEASE"; PARTIAL_RELEASE="PARTIAL_RELEASE"
    FULL_REFUND="FULL_REFUND"; PARTIAL_REFUND="PARTIAL_REFUND"
class NotifType(str, enum.Enum):
    PROJECT_FUNDED="PROJECT_FUNDED"; MILESTONE_SUBMITTED="MILESTONE_SUBMITTED"
    MILESTONE_APPROVED="MILESTONE_APPROVED"; PAYMENT_RELEASED="PAYMENT_RELEASED"
    DISPUTE_OPENED="DISPUTE_OPENED"; DISPUTE_RESOLVED="DISPUTE_RESOLVED"
    COMPANY_DETECTED="COMPANY_DETECTED"; GENERAL="GENERAL"
class ProofType(str, enum.Enum):
    PHOTO="PHOTO"; VIDEO="VIDEO"; DOCUMENT="DOCUMENT"
class AiStatus(str, enum.Enum):
    PENDING="PENDING"; PROCESSING="PROCESSING"; COMPLETED="COMPLETED"; FAILED="FAILED"
class AiRec(str, enum.Enum):
    APPROVE="APPROVE"; REJECT="REJECT"; HUMAN_REVIEW="HUMAN_REVIEW"
class ReceiptStatus(str, enum.Enum):
    PENDING="PENDING"; PROCESSING="PROCESSING"; COMPLETED="COMPLETED"; FAILED="FAILED"
class UploadPurpose(str, enum.Enum):
    MILESTONE_PROOF="MILESTONE_PROOF"; DISPUTE_EVIDENCE="DISPUTE_EVIDENCE"; DOCUMENT="DOCUMENT"; RECEIPT="RECEIPT"
class JobStatus(str, enum.Enum):
    PENDING="PENDING"; RUNNING="RUNNING"; COMPLETED="COMPLETED"; FAILED="FAILED"; DEAD="DEAD"


# ── Models ────────────────────────────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String, unique=True)
    password_hash: Mapped[str] = mapped_column(String)
    role: Mapped[UserRole] = mapped_column(E(UserRole), default=UserRole.HOMEOWNER)
    status: Mapped[UserStatus] = mapped_column(E(UserStatus), default=UserStatus.ACTIVE)
    first_name: Mapped[str] = mapped_column(String)
    last_name: Mapped[str] = mapped_column(String)
    phone: Mapped[Optional[str]] = mapped_column(String)
    stripe_account_id: Mapped[Optional[str]] = mapped_column(String, unique=True)
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(String, unique=True)
    identity_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    __table_args__ = (Index("ix_users_email","email"),)

class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"))
    token: Mapped[str] = mapped_column(String, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"))
    token: Mapped[str] = mapped_column(String, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class Company(Base):
    __tablename__ = "companies"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String)
    email: Mapped[str] = mapped_column(String, unique=True)
    phone: Mapped[Optional[str]] = mapped_column(String)
    license_number: Mapped[Optional[str]] = mapped_column(String)
    owner_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), unique=True)
    stripe_account_id: Mapped[Optional[str]] = mapped_column(String, unique=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    __table_args__ = (Index("ix_companies_email","email"),)

class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    title: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(Text)
    category: Mapped[ProjectCategory] = mapped_column(E(ProjectCategory))
    status: Mapped[ProjectStatus] = mapped_column(E(ProjectStatus), default=ProjectStatus.DRAFT)
    homeowner_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"))
    contractor_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("users.id"))
    company_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("companies.id"))
    address_line1: Mapped[str] = mapped_column(String)
    city: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String(2))
    zip_code: Mapped[str] = mapped_column(String)
    total_amount: Mapped[int] = mapped_column(Integer)
    platform_fee_percent: Mapped[float] = mapped_column(Float, default=1.5)
    platform_fee: Mapped[int] = mapped_column(Integer)
    contractor_payout: Mapped[int] = mapped_column(Integer)
    external_payment_id: Mapped[Optional[str]] = mapped_column(String, unique=True)
    escrow_funded: Mapped[bool] = mapped_column(Boolean, default=False)
    escrow_funded_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    __table_args__ = (Index("ix_projects_homeowner","homeowner_id"), Index("ix_projects_status","status"))

class Milestone(Base):
    __tablename__ = "milestones"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(Text)
    order: Mapped[int] = mapped_column(Integer)
    amount: Mapped[int] = mapped_column(Integer)
    status: Mapped[MilestoneStatus] = mapped_column(E(MilestoneStatus), default=MilestoneStatus.PENDING)
    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    released_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    __table_args__ = (Index("ix_milestones_project","project_id"),)

class MilestoneProof(Base):
    __tablename__ = "milestone_proofs"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    milestone_id: Mapped[str] = mapped_column(String, ForeignKey("milestones.id", ondelete="CASCADE"))
    uploaded_by_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"))
    type: Mapped[ProofType] = mapped_column(E(ProofType))
    file_url: Mapped[str] = mapped_column(String)
    file_key: Mapped[str] = mapped_column(String)
    mime_type: Mapped[str] = mapped_column(String)
    size_bytes: Mapped[int] = mapped_column(Integer)
    caption: Mapped[Optional[str]] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class AiVerification(Base):
    __tablename__ = "ai_verifications"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    milestone_id: Mapped[str] = mapped_column(String, ForeignKey("milestones.id", ondelete="CASCADE"), unique=True)
    status: Mapped[AiStatus] = mapped_column(E(AiStatus), default=AiStatus.PENDING)
    confidence_score: Mapped[Optional[float]] = mapped_column(Float)
    summary: Mapped[Optional[str]] = mapped_column(Text)
    issues: Mapped[Optional[list]] = mapped_column(JSON)
    recommendation: Mapped[Optional[AiRec]] = mapped_column(E(AiRec))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_reason: Mapped[Optional[str]] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

class PaymentLedger(Base):
    __tablename__ = "payment_ledger"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id"))
    milestone_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("milestones.id"))
    type: Mapped[LedgerType] = mapped_column(E(LedgerType))
    direction: Mapped[LedgerDir] = mapped_column(E(LedgerDir))
    amount_cents: Mapped[int] = mapped_column(Integer)
    balance_cents: Mapped[int] = mapped_column(Integer)
    external_ref: Mapped[Optional[str]] = mapped_column(String)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String, unique=True)
    description: Mapped[str] = mapped_column(String)
    actor_id: Mapped[Optional[str]] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    __table_args__ = (Index("ix_ledger_project","project_id"),)

class ProjectEvent(Base):
    __tablename__ = "project_events"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id", ondelete="CASCADE"))
    event_type: Mapped[EventType] = mapped_column(E(EventType))
    actor_id: Mapped[Optional[str]] = mapped_column(String)
    from_status: Mapped[Optional[ProjectStatus]] = mapped_column(E(ProjectStatus))
    to_status: Mapped[Optional[ProjectStatus]] = mapped_column(E(ProjectStatus))
    milestone_id: Mapped[Optional[str]] = mapped_column(String)
    payload: Mapped[Optional[dict]] = mapped_column(JSON)
    source: Mapped[Optional[str]] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    __table_args__ = (Index("ix_events_project","project_id"),)

class Dispute(Base):
    __tablename__ = "disputes"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id"))
    initiated_by: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[DisputeStatus] = mapped_column(E(DisputeStatus), default=DisputeStatus.OPEN)
    resolution: Mapped[Optional[str]] = mapped_column(Text)
    resolved_by: Mapped[Optional[str]] = mapped_column(String)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    outcome: Mapped[Optional[DisputeOutcome]] = mapped_column(E(DisputeOutcome))
    refund_amount: Mapped[Optional[int]] = mapped_column(Integer)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    __table_args__ = (Index("ix_disputes_project","project_id"),)

class DisputeComment(Base):
    __tablename__ = "dispute_comments"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    dispute_id: Mapped[str] = mapped_column(String, ForeignKey("disputes.id", ondelete="CASCADE"))
    author_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"))
    content: Mapped[str] = mapped_column(Text)
    file_urls: Mapped[Optional[list]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class Receipt(Base):
    __tablename__ = "receipts"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id"))
    raw_text: Mapped[Optional[str]] = mapped_column(Text)
    file_url: Mapped[Optional[str]] = mapped_column(String)
    vendor_email: Mapped[Optional[str]] = mapped_column(String)
    vendor_name: Mapped[Optional[str]] = mapped_column(String)
    amount: Mapped[Optional[int]] = mapped_column(Integer)
    receipt_date: Mapped[Optional[datetime]] = mapped_column(DateTime)
    items: Mapped[Optional[list]] = mapped_column(JSON)
    auto_linked_company_id: Mapped[Optional[str]] = mapped_column(String)
    auto_linked: Mapped[bool] = mapped_column(Boolean, default=False)
    processing_status: Mapped[ReceiptStatus] = mapped_column(E(ReceiptStatus), default=ReceiptStatus.PENDING)
    processing_error: Mapped[Optional[str]] = mapped_column(String)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    __table_args__ = (Index("ix_receipts_vendor_email","vendor_email"),)

class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id", ondelete="CASCADE"))
    uploaded_by_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String)
    file_url: Mapped[str] = mapped_column(String)
    file_key: Mapped[str] = mapped_column(String)
    mime_type: Mapped[str] = mapped_column(String)
    size_bytes: Mapped[int] = mapped_column(Integer)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class ProofOfFundsCert(Base):
    __tablename__ = "proof_of_funds_certs"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id"), unique=True)
    cert_number: Mapped[str] = mapped_column(String, unique=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"))
    project_id: Mapped[Optional[str]] = mapped_column(String)
    type: Mapped[NotifType] = mapped_column(E(NotifType))
    title: Mapped[str] = mapped_column(String)
    body: Mapped[str] = mapped_column(String)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    __table_args__ = (Index("ix_notifs_user","user_id","read"),)

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    actor_id: Mapped[Optional[str]] = mapped_column(String)
    actor_role: Mapped[Optional[str]] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    entity: Mapped[str] = mapped_column(String)
    entity_id: Mapped[str] = mapped_column(String)
    before: Mapped[Optional[dict]] = mapped_column(JSON)
    after: Mapped[Optional[dict]] = mapped_column(JSON)
    diff: Mapped[Optional[dict]] = mapped_column(JSON)
    project_id: Mapped[Optional[str]] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    __table_args__ = (Index("ix_audit_entity","entity","entity_id"),)

class UploadToken(Base):
    __tablename__ = "upload_tokens"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"))
    purpose: Mapped[UploadPurpose] = mapped_column(E(UploadPurpose))
    entity_id: Mapped[str] = mapped_column(String)
    entity_type: Mapped[str] = mapped_column(String)
    presigned_url: Mapped[str] = mapped_column(String)
    presigned_fields: Mapped[dict] = mapped_column(JSON)
    s3_key: Mapped[str] = mapped_column(String)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    provider: Mapped[str] = mapped_column(String)
    event_id: Mapped[str] = mapped_column(String, unique=True)
    event_type: Mapped[str] = mapped_column(String)
    payload: Mapped[dict] = mapped_column(JSON)
    processed: Mapped[bool] = mapped_column(Boolean, default=False)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    error: Mapped[Optional[str]] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    __table_args__ = (Index("ix_webhook_event_id","event_id"),)


# ── Auth helpers ──────────────────────────────────────────────────────────────
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer = HTTPBearer()

def hash_pw(p): return pwd_ctx.hash(p)
def check_pw(p, h): return pwd_ctx.verify(p, h)

def make_token(user_id, email, role):
    exp = datetime.now(timezone.utc) + timedelta(minutes=cfg.JWT_EXPIRES_MINUTES)
    return jwt.encode({"sub": user_id, "email": email, "role": role, "exp": exp}, cfg.JWT_SECRET, "HS256")

def make_refresh(user_id):
    exp = datetime.now(timezone.utc) + timedelta(days=cfg.JWT_REFRESH_EXPIRES_DAYS)
    return jwt.encode({"sub": user_id, "exp": exp}, cfg.JWT_REFRESH_SECRET, "HS256")

class CurrentUser:
    def __init__(self, user_id, email, role): self.user_id=user_id; self.email=email; self.role=role

async def get_user(creds: HTTPAuthorizationCredentials = Depends(bearer), db: AsyncSession = Depends(get_db)):
    try: payload = jwt.decode(creds.credentials, cfg.JWT_SECRET, ["HS256"]); uid_ = payload["sub"]
    except JWTError: raise HTTPException(401, "Invalid token")
    r = await db.execute(select(Session).where(Session.token==creds.credentials, Session.expires_at>datetime.now(timezone.utc)))
    if not r.scalar_one_or_none(): raise HTTPException(401, "Session expired")
    r = await db.execute(select(User).where(User.id==uid_))
    u = r.scalar_one_or_none()
    if not u or u.status in (UserStatus.SUSPENDED, UserStatus.BANNED): raise HTTPException(403, "Account unavailable")
    return CurrentUser(u.id, u.email, u.role)

def role_guard(*roles):
    async def _guard(cur: CurrentUser = Depends(get_user)):
        if cur.role not in roles: raise HTTPException(403, "Insufficient role")
        return cur
    return _guard


# ── External clients ──────────────────────────────────────────────────────────
stripe.api_key = cfg.STRIPE_SECRET_KEY
stripe.max_network_retries = 3
ai_client = OpenAI(api_key=cfg.OPENAI_API_KEY) if cfg.OPENAI_API_KEY else None
sg_client = SendGridAPIClient(cfg.SENDGRID_API_KEY) if cfg.SENDGRID_API_KEY else None
s3_client = boto3.client("s3", region_name=cfg.AWS_REGION,
    aws_access_key_id=cfg.AWS_ACCESS_KEY_ID, aws_secret_access_key=cfg.AWS_SECRET_ACCESS_KEY) if cfg.AWS_ACCESS_KEY_ID else None

_redis = None
def get_redis():
    global _redis
    if not _redis: _redis = redis_lib.from_url(cfg.REDIS_URL, decode_responses=False)
    return _redis

q_milestone = Queue("milestone_verification", connection=get_redis())
q_receipt   = Queue("receipt_processing",     connection=get_redis())
q_payment   = Queue("payment_release",        connection=get_redis())


# ── Service helpers ───────────────────────────────────────────────────────────
async def write_ledger(db, *, project_id, type, direction, amount_cents, description,
    milestone_id=None, external_ref=None, ikey=None, actor_id=None):
    if ikey:
        r = await db.execute(select(PaymentLedger).where(PaymentLedger.idempotency_key==ikey))
        if r.scalar_one_or_none(): return
    r = await db.execute(select(PaymentLedger).where(PaymentLedger.project_id==project_id).order_by(PaymentLedger.created_at.desc()).limit(1))
    last = r.scalar_one_or_none()
    prev = last.balance_cents if last else 0
    new_bal = prev + amount_cents if direction == LedgerDir.CREDIT else prev - amount_cents
    db.add(PaymentLedger(project_id=project_id, milestone_id=milestone_id, type=type, direction=direction,
        amount_cents=amount_cents, balance_cents=new_bal, external_ref=external_ref,
        idempotency_key=ikey, description=description, actor_id=actor_id))
    await db.flush()

async def emit_event(db, *, project_id, event_type, actor_id=None, from_status=None, to_status=None, milestone_id=None, payload=None, source="api"):
    try:
        db.add(ProjectEvent(project_id=project_id, event_type=event_type, actor_id=actor_id,
            from_status=from_status, to_status=to_status, milestone_id=milestone_id, payload=payload, source=source))
        await db.flush()
    except: pass

async def add_notif(db, *, user_id, type, title, body, project_id=None):
    db.add(Notification(user_id=user_id, type=type, title=title, body=body, project_id=project_id))
    await db.flush()
    if sg_client:
        try:
            r = await db.execute(select(User).where(User.id==user_id))
            u = r.scalar_one_or_none()
            if u:
                sg_client.send(Mail(from_email=(cfg.SENDGRID_FROM_EMAIL, cfg.SENDGRID_FROM_NAME),
                    to_emails=u.email, subject=title,
                    html_content=f"<p>Hi {u.first_name},</p><h3>{title}</h3><p>{body}</p>"))
        except: pass

async def guard_project(project_id, cur, db) -> Project:
    r = await db.execute(select(Project).where(Project.id==project_id, Project.deleted_at==None))
    p = r.scalar_one_or_none()
    if not p: raise HTTPException(404, "Project not found")
    if cur.role != UserRole.ADMIN and cur.user_id not in (p.homeowner_id, p.contractor_id): raise HTTPException(403)
    return p

def s3_key(purpose, filename):
    folders = {"MILESTONE_PROOF":"milestone-proofs","DISPUTE_EVIDENCE":"dispute-evidence","DOCUMENT":"documents","RECEIPT":"receipts"}
    ext = os.path.splitext(filename)[1].lower() or ".bin"
    return f"{folders.get(purpose,'misc')}/{uuid.uuid4()}{ext}"

def s3_url(key): return f"https://{cfg.AWS_S3_BUCKET}.s3.{cfg.AWS_REGION}.amazonaws.com/{key}"


# ── Background tasks (run in RQ worker) ──────────────────────────────────────
def _sync_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    url = cfg.DATABASE_URL.replace("postgresql+asyncpg://","postgresql://").replace("postgres://","postgresql://")
    return sessionmaker(create_engine(url, pool_pre_ping=True))()

def task_verify_milestone(milestone_id: str):
    db = _sync_db()
    try:
        from sqlalchemy import select as s_
        m = db.query(Milestone).filter_by(id=milestone_id).first()
        p = db.query(Project).filter_by(id=m.project_id).first()
        ai = db.query(AiVerification).filter_by(milestone_id=milestone_id).first()
        if not ai: ai = AiVerification(milestone_id=milestone_id); db.add(ai)
        ai.status = AiStatus.PROCESSING; ai.attempt_count = (ai.attempt_count or 0) + 1
        m.status = MilestoneStatus.AI_REVIEWING; db.commit()
        proofs = db.query(MilestoneProof).filter_by(milestone_id=milestone_id).all()
        urls = [x.file_url for x in proofs if x.type in (ProofType.PHOTO, ProofType.VIDEO)]
        if ai_client and urls:
            imgs = [{"type":"image_url","image_url":{"url":u,"detail":"high"}} for u in urls[:8]]
            resp = ai_client.chat.completions.create(model="gpt-4o",
                messages=[{"role":"system","content":"You are a construction inspector. Return ONLY JSON."},
                    {"role":"user","content":[{"type":"text","text":f"MILESTONE: {m.title}\nCATEGORY: {p.category.value}\nAnalyze photos. Return: {{\"status\":\"APPROVE\"|\"REJECT\"|\"HUMAN_REVIEW\",\"confidenceScore\":0.0,\"summary\":\"\",\"issues\":[]}}"},*imgs]}],
                max_tokens=600, temperature=0, response_format={"type":"json_object"})
            d = json.loads(resp.choices[0].message.content)
            ai.status = AiStatus.COMPLETED; ai.confidence_score = float(d.get("confidenceScore",0))
            ai.summary = d.get("summary",""); ai.issues = d.get("issues",[])
            ai.recommendation = AiRec(d.get("status","HUMAN_REVIEW"))
        else:
            ai.status = AiStatus.COMPLETED; ai.recommendation = AiRec.HUMAN_REVIEW
            ai.summary = "No photos — manual review required"; ai.confidence_score = 0
        m.status = MilestoneStatus.HOMEOWNER_REVIEW
        for uid_ in [p.homeowner_id, p.contractor_id]:
            if uid_: db.add(Notification(user_id=uid_, project_id=m.project_id, type=NotifType.MILESTONE_SUBMITTED,
                title=f"Milestone ready for review: {m.title}", body="AI analysis complete. Please review."))
        db.commit()
    except Exception as e:
        db.rollback()
        ai_err = db.query(AiVerification).filter_by(milestone_id=milestone_id).first()
        if ai_err: ai_err.status = AiStatus.FAILED; ai_err.failure_reason = str(e); db.commit()
        raise
    finally: db.close()

def task_process_receipt(receipt_id: str):
    db = _sync_db()
    try:
        r = db.query(Receipt).filter_by(id=receipt_id).first()
        if not r: return
        r.processing_status = ReceiptStatus.PROCESSING; db.commit()
        extracted = {}
        if ai_client and r.raw_text:
            resp = ai_client.chat.completions.create(model="gpt-4o",
                messages=[{"role":"user","content":f"Extract: vendorName, vendorEmail, amount (cents int), receiptDate (ISO). JSON only.\n{r.raw_text[:4000]}"}],
                max_tokens=400, temperature=0, response_format={"type":"json_object"})
            extracted = json.loads(resp.choices[0].message.content)
        r.vendor_name = extracted.get("vendorName"); r.vendor_email = (extracted.get("vendorEmail") or "").lower().strip() or None
        r.amount = extracted.get("amount"); r.processing_status = ReceiptStatus.COMPLETED; db.commit()
        if r.vendor_email:
            co = db.query(Company).filter_by(email=r.vendor_email).first()
            if co:
                r.auto_linked_company_id = co.id; r.auto_linked = True
                p = db.query(Project).filter_by(id=r.project_id).first()
                if p and not p.company_id: p.company_id = co.id
                for uid_ in [p.homeowner_id, p.contractor_id]:
                    if uid_: db.add(Notification(user_id=uid_, project_id=r.project_id, type=NotifType.COMPANY_DETECTED,
                        title="Company auto-detected", body=f"{co.name} linked via receipt."))
                db.commit()
    except Exception as e:
        db.rollback()
        rec = db.query(Receipt).filter_by(id=receipt_id).first()
        if rec: rec.processing_status = ReceiptStatus.FAILED; rec.processing_error = str(e); db.commit()
        raise
    finally: db.close()

def task_release_payment(milestone_id: str):
    db = _sync_db()
    try:
        m = db.query(Milestone).filter_by(id=milestone_id).first()
        p = db.query(Project).filter_by(id=m.project_id).first()
        contractor = db.query(User).filter_by(id=p.contractor_id).first()
        if not contractor or not contractor.stripe_account_id: raise ValueError("No Stripe account")
        ikey = f"payout:milestone:{milestone_id}"
        if not db.query(PaymentLedger).filter_by(idempotency_key=ikey).first():
            transfer = stripe.Transfer.create(amount=m.amount, currency="usd",
                destination=contractor.stripe_account_id,
                metadata={"project_id": m.project_id, "milestone_id": milestone_id})
            last = db.query(PaymentLedger).filter_by(project_id=m.project_id).order_by(PaymentLedger.created_at.desc()).first()
            prev = last.balance_cents if last else 0
            db.add(PaymentLedger(project_id=m.project_id, milestone_id=milestone_id,
                type=LedgerType.MILESTONE_RELEASED, direction=LedgerDir.DEBIT,
                amount_cents=m.amount, balance_cents=prev-m.amount,
                external_ref=transfer["id"], idempotency_key=ikey, description=f"Milestone: {m.title}"))
        m.status = MilestoneStatus.PAYMENT_RELEASED; m.released_at = datetime.utcnow()
        remaining = db.query(Milestone).filter(
            Milestone.project_id==m.project_id, Milestone.status!=MilestoneStatus.PAYMENT_RELEASED, Milestone.deleted_at==None).count()
        if remaining == 0: p.status = ProjectStatus.COMPLETED; p.completed_at = datetime.utcnow()
        for uid_ in [p.homeowner_id, p.contractor_id]:
            if uid_: db.add(Notification(user_id=uid_, project_id=m.project_id, type=NotifType.PAYMENT_RELEASED,
                title=f"Payment released: {m.title}", body=f"${m.amount/100:.2f} transferred."))
        db.commit()
    except Exception as e: db.rollback(); raise
    finally: db.close()


# ── Pydantic schemas ──────────────────────────────────────────────────────────
class RegisterIn(BaseModel):
    email: EmailStr; password: str; first_name: str; last_name: str
    role: UserRole; phone: Optional[str]=None; company_name: Optional[str]=None

class LoginIn(BaseModel):
    email: EmailStr; password: str

class ProjectIn(BaseModel):
    title: str; description: Optional[str]=None; category: ProjectCategory
    address_line1: str; city: str; state: str; zip_code: str
    total_amount: int

class MilestoneIn(BaseModel):
    title: str; description: Optional[str]=None; order: int; amount: int; due_date: Optional[datetime]=None

class CompanyIn(BaseModel):
    name: str; email: EmailStr; phone: Optional[str]=None; license_number: Optional[str]=None

class UploadTokenIn(BaseModel):
    purpose: UploadPurpose; entity_id: str; entity_type: str; filename: str; content_type: str


# ── App + middleware ──────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app):
    yield
    await engine.dispose()

app = FastAPI(title="MK Underwood", version="2.0.0",
    docs_url="/docs" if cfg.ENV != "production" else None, lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=[cfg.FRONTEND_URL,"http://localhost:5173"],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*","Idempotency-Key"])

class RateLimit(BaseHTTPMiddleware):
    async def dispatch(self, req, call_next):
        if not req.url.path.startswith("/api"): return await call_next(req)
        ip = req.client.host or "x"
        limit = 10 if any(x in req.url.path for x in ["/login","/register"]) else cfg.RATE_LIMIT_REQUESTS
        win = 900 if limit == 10 else cfg.RATE_LIMIT_WINDOW
        key = f"rl:{ip}:{int(time.time()//win)}"
        try:
            r = get_redis(); c = r.incr(key)
            if c == 1: r.expire(key, win)
            if c > limit: return JSONResponse({"error":"Too many requests"}, 429)
        except: pass
        return await call_next(req)

app.add_middleware(RateLimit)


# ── Routes ────────────────────────────────────────────────────────────────────
V = "/api/v1"

@app.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    await db.execute(text("SELECT 1"))
    return {"status": "healthy"}

# Auth
@app.post(f"{V}/auth/register", status_code=201)
async def register(body: RegisterIn, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(User).where(User.email==body.email.lower()))
    if r.scalar_one_or_none(): raise HTTPException(409, "Email taken")
    u = User(email=body.email.lower(), password_hash=hash_pw(body.password),
        first_name=body.first_name, last_name=body.last_name, phone=body.phone, role=body.role)
    db.add(u); await db.flush()
    if body.role == UserRole.HOMEOWNER and cfg.STRIPE_SECRET_KEY:
        c = stripe.Customer.create(email=u.email, name=f"{u.first_name} {u.last_name}")
        u.stripe_customer_id = c["id"]
    if body.role == UserRole.CONTRACTOR and cfg.STRIPE_SECRET_KEY:
        a = stripe.Account.create(type="express", email=u.email,
            capabilities={"card_payments":{"requested":True},"transfers":{"requested":True}})
        u.stripe_account_id = a["id"]
    access = make_token(u.id, u.email, u.role.value); refresh = make_refresh(u.id)
    db.add(Session(user_id=u.id, token=access, expires_at=datetime.now(timezone.utc)+timedelta(minutes=cfg.JWT_EXPIRES_MINUTES)))
    db.add(RefreshToken(user_id=u.id, token=refresh, expires_at=datetime.now(timezone.utc)+timedelta(days=cfg.JWT_REFRESH_EXPIRES_DAYS)))
    await db.commit()
    return {"user":{"id":u.id,"email":u.email,"role":u.role}, "access_token":access, "refresh_token":refresh}

@app.post(f"{V}/auth/login")
async def login(body: LoginIn, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(User).where(User.email==body.email.lower()))
    u = r.scalar_one_or_none()
    if not u or not check_pw(body.password, u.password_hash): raise HTTPException(401, "Invalid credentials")
    if u.status in (UserStatus.SUSPENDED, UserStatus.BANNED): raise HTTPException(403, "Suspended")
    access = make_token(u.id, u.email, u.role.value); refresh = make_refresh(u.id)
    db.add(Session(user_id=u.id, token=access, expires_at=datetime.now(timezone.utc)+timedelta(minutes=cfg.JWT_EXPIRES_MINUTES)))
    db.add(RefreshToken(user_id=u.id, token=refresh, expires_at=datetime.now(timezone.utc)+timedelta(days=cfg.JWT_REFRESH_EXPIRES_DAYS)))
    await db.commit()
    return {"user":{"id":u.id,"email":u.email,"role":u.role,"stripe_account_id":u.stripe_account_id}, "access_token":access, "refresh_token":refresh}

@app.post(f"{V}/auth/logout")
async def logout(cur: CurrentUser = Depends(get_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(Session).where(Session.user_id==cur.user_id))
    for s in r.scalars(): await db.delete(s)
    await db.commit(); return {"ok":True}

@app.get(f"{V}/auth/me")
async def me(cur: CurrentUser = Depends(get_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(User).where(User.id==cur.user_id))
    u = r.scalar_one_or_none()
    return {"id":u.id,"email":u.email,"first_name":u.first_name,"last_name":u.last_name,"role":u.role,"stripe_account_id":u.stripe_account_id}

# Projects
@app.post(f"{V}/projects", status_code=201)
async def create_project(body: ProjectIn, cur: CurrentUser = Depends(role_guard(UserRole.HOMEOWNER)), db: AsyncSession = Depends(get_db)):
    fee = int(body.total_amount * cfg.PLATFORM_FEE_PERCENT / 100)
    p = Project(homeowner_id=cur.user_id, title=body.title, description=body.description,
        category=body.category, address_line1=body.address_line1, city=body.city,
        state=body.state, zip_code=body.zip_code, total_amount=body.total_amount,
        platform_fee_percent=cfg.PLATFORM_FEE_PERCENT, platform_fee=fee, contractor_payout=body.total_amount-fee)
    db.add(p); await db.flush()
    await emit_event(db, project_id=p.id, event_type=EventType.PROJECT_CREATED, actor_id=cur.user_id, to_status=ProjectStatus.DRAFT)
    await db.commit()
    return {"id":p.id,"status":p.status,"total_amount":p.total_amount}

@app.get(f"{V}/projects")
async def list_projects(cur: CurrentUser = Depends(get_user), db: AsyncSession = Depends(get_db)):
    q = select(Project).where(Project.deleted_at==None)
    if cur.role == UserRole.HOMEOWNER: q = q.where(Project.homeowner_id==cur.user_id)
    elif cur.role == UserRole.CONTRACTOR: q = q.where(Project.contractor_id==cur.user_id)
    r = await db.execute(q)
    return [{"id":p.id,"title":p.title,"status":p.status,"total_amount":p.total_amount,"category":p.category} for p in r.scalars()]

@app.get(f"{V}/projects/{{pid}}")
async def get_project(pid: str, cur: CurrentUser = Depends(get_user), db: AsyncSession = Depends(get_db)):
    p = await guard_project(pid, cur, db)
    return {"id":p.id,"title":p.title,"description":p.description,"status":p.status,
            "category":p.category,"total_amount":p.total_amount,"platform_fee":p.platform_fee,
            "contractor_payout":p.contractor_payout,"escrow_funded":p.escrow_funded,
            "homeowner_id":p.homeowner_id,"contractor_id":p.contractor_id,"company_id":p.company_id}

@app.post(f"{V}/projects/{{pid}}/assign-contractor")
async def assign_contractor(pid: str, body: dict, cur: CurrentUser = Depends(role_guard(UserRole.HOMEOWNER)), db: AsyncSession = Depends(get_db)):
    p = await guard_project(pid, cur, db)
    if p.status != ProjectStatus.DRAFT: raise HTTPException(400, "Must be DRAFT")
    r = await db.execute(select(User).where(User.id==body.get("contractor_id"), User.role==UserRole.CONTRACTOR))
    c = r.scalar_one_or_none()
    if not c: raise HTTPException(404, "Contractor not found")
    p.contractor_id = c.id; p.status = ProjectStatus.AWAITING_FUNDING
    await emit_event(db, project_id=pid, event_type=EventType.CONTRACTOR_ASSIGNED, actor_id=cur.user_id,
        from_status=ProjectStatus.DRAFT, to_status=ProjectStatus.AWAITING_FUNDING, payload={"contractor_id":c.id})
    await db.commit(); return {"status":p.status}

@app.post(f"{V}/projects/{{pid}}/fund")
async def fund_project(pid: str, cur: CurrentUser = Depends(role_guard(UserRole.HOMEOWNER)), db: AsyncSession = Depends(get_db)):
    p = await guard_project(pid, cur, db)
    if p.status != ProjectStatus.AWAITING_FUNDING: raise HTTPException(400, "Not awaiting funding")
    r = await db.execute(select(User).where(User.id==cur.user_id)); hw = r.scalar_one_or_none()
    r = await db.execute(select(User).where(User.id==p.contractor_id)); ct = r.scalar_one_or_none()
    if not hw.stripe_customer_id or not ct.stripe_account_id: raise HTTPException(400, "Stripe not configured")
    intent = stripe.PaymentIntent.create(amount=p.total_amount, currency="usd", customer=hw.stripe_customer_id,
        capture_method="manual", on_behalf_of=ct.stripe_account_id,
        transfer_data={"destination":ct.stripe_account_id}, application_fee_amount=p.platform_fee,
        description=f"MK Underwood - {p.title}", metadata={"project_id":pid})
    p.external_payment_id = intent["id"]; p.status = ProjectStatus.FUNDED
    p.escrow_funded = True; p.escrow_funded_at = datetime.utcnow()
    await write_ledger(db, project_id=pid, type=LedgerType.ESCROW_FUNDED, direction=LedgerDir.CREDIT,
        amount_cents=p.total_amount, description="Escrow funded", external_ref=intent["id"],
        ikey=f"fund:{pid}", actor_id=cur.user_id)
    await write_ledger(db, project_id=pid, type=LedgerType.PLATFORM_FEE, direction=LedgerDir.DEBIT,
        amount_cents=p.platform_fee, description="Platform fee", actor_id=cur.user_id)
    await emit_event(db, project_id=pid, event_type=EventType.ESCROW_FUNDED, actor_id=cur.user_id,
        from_status=ProjectStatus.AWAITING_FUNDING, to_status=ProjectStatus.FUNDED)
    await add_notif(db, user_id=p.homeowner_id, type=NotifType.PROJECT_FUNDED,
        title="Escrow funded!", body=f"${p.total_amount/100:.2f} held in escrow.", project_id=pid)
    await db.commit()
    return {"status":p.status,"client_secret":intent["client_secret"]}

@app.post(f"{V}/projects/{{pid}}/cancel")
async def cancel_project(pid: str, cur: CurrentUser = Depends(get_user), db: AsyncSession = Depends(get_db)):
    p = await guard_project(pid, cur, db)
    if p.status not in (ProjectStatus.DRAFT, ProjectStatus.AWAITING_FUNDING, ProjectStatus.FUNDED):
        raise HTTPException(400, f"Cannot cancel in {p.status}")
    if p.external_payment_id:
        try: stripe.PaymentIntent.cancel(p.external_payment_id)
        except: pass
    p.status = ProjectStatus.CANCELLED; p.cancelled_at = datetime.utcnow()
    await emit_event(db, project_id=pid, event_type=EventType.PROJECT_CANCELLED, actor_id=cur.user_id)
    await db.commit(); return {"status":p.status}

@app.get(f"{V}/projects/{{pid}}/ledger")
async def get_ledger(pid: str, cur: CurrentUser = Depends(get_user), db: AsyncSession = Depends(get_db)):
    await guard_project(pid, cur, db)
    r = await db.execute(select(PaymentLedger).where(PaymentLedger.project_id==pid).order_by(PaymentLedger.created_at.asc()))
    entries = r.scalars().all()
    balance = entries[-1].balance_cents if entries else 0
    return {"entries":[{"id":e.id,"type":e.type,"direction":e.direction,"amount_cents":e.amount_cents,
        "balance_cents":e.balance_cents,"description":e.description,"created_at":e.created_at} for e in entries], "balance_cents":balance}

@app.get(f"{V}/projects/{{pid}}/events")
async def get_events(pid: str, cur: CurrentUser = Depends(get_user), db: AsyncSession = Depends(get_db)):
    await guard_project(pid, cur, db)
    r = await db.execute(select(ProjectEvent).where(ProjectEvent.project_id==pid).order_by(ProjectEvent.created_at.asc()))
    return [{"id":e.id,"event_type":e.event_type,"actor_id":e.actor_id,"from_status":e.from_status,
        "to_status":e.to_status,"payload":e.payload,"created_at":e.created_at} for e in r.scalars()]

# Milestones
@app.post(f"{V}/projects/{{pid}}/milestones", status_code=201)
async def create_milestone(pid: str, body: MilestoneIn, cur: CurrentUser = Depends(get_user), db: AsyncSession = Depends(get_db)):
    await guard_project(pid, cur, db)
    m = Milestone(project_id=pid, title=body.title, description=body.description, order=body.order, amount=body.amount, due_date=body.due_date)
    db.add(m); await db.commit()
    return {"id":m.id,"title":m.title,"amount":m.amount,"status":m.status}

@app.get(f"{V}/projects/{{pid}}/milestones")
async def list_milestones(pid: str, cur: CurrentUser = Depends(get_user), db: AsyncSession = Depends(get_db)):
    await guard_project(pid, cur, db)
    r = await db.execute(select(Milestone).where(Milestone.project_id==pid, Milestone.deleted_at==None).order_by(Milestone.order))
    return [{"id":m.id,"title":m.title,"order":m.order,"amount":m.amount,"status":m.status,"due_date":m.due_date} for m in r.scalars()]

@app.post(f"{V}/projects/{{pid}}/milestones/{{mid}}/submit")
async def submit_milestone(pid: str, mid: str, cur: CurrentUser = Depends(role_guard(UserRole.CONTRACTOR)), db: AsyncSession = Depends(get_db)):
    await guard_project(pid, cur, db)
    r = await db.execute(select(Milestone).where(Milestone.id==mid, Milestone.project_id==pid))
    m = r.scalar_one_or_none()
    if not m: raise HTTPException(404)
    if m.status not in (MilestoneStatus.PENDING, MilestoneStatus.IN_PROGRESS): raise HTTPException(400, "Cannot submit")
    m.status = MilestoneStatus.SUBMITTED
    await emit_event(db, project_id=pid, event_type=EventType.MILESTONE_SUBMITTED, actor_id=cur.user_id, milestone_id=mid)
    await db.commit()
    q_milestone.enqueue(task_verify_milestone, mid)
    return {"status":m.status}

@app.post(f"{V}/projects/{{pid}}/milestones/{{mid}}/approve")
async def approve_milestone(pid: str, mid: str, cur: CurrentUser = Depends(role_guard(UserRole.HOMEOWNER)), db: AsyncSession = Depends(get_db)):
    await guard_project(pid, cur, db)
    r = await db.execute(select(Milestone).where(Milestone.id==mid, Milestone.project_id==pid))
    m = r.scalar_one_or_none()
    if not m or m.status != MilestoneStatus.HOMEOWNER_REVIEW: raise HTTPException(400, "Not ready for approval")
    m.status = MilestoneStatus.APPROVED; m.approved_at = datetime.utcnow()
    await emit_event(db, project_id=pid, event_type=EventType.MILESTONE_APPROVED, actor_id=cur.user_id, milestone_id=mid)
    await db.commit()
    q_payment.enqueue(task_release_payment, mid)
    return {"status":m.status}

@app.post(f"{V}/projects/{{pid}}/milestones/{{mid}}/dispute")
async def dispute_milestone(pid: str, mid: str, body: dict, cur: CurrentUser = Depends(role_guard(UserRole.HOMEOWNER)), db: AsyncSession = Depends(get_db)):
    p = await guard_project(pid, cur, db)
    r = await db.execute(select(Milestone).where(Milestone.id==mid, Milestone.project_id==pid))
    m = r.scalar_one_or_none()
    if not m or m.status != MilestoneStatus.HOMEOWNER_REVIEW: raise HTTPException(400, "Not in review")
    reason = body.get("reason","")
    if not reason: raise HTTPException(400, "reason required")
    m.status = MilestoneStatus.DISPUTED
    d = Dispute(project_id=pid, initiated_by=cur.user_id, reason=reason)
    db.add(d); p.status = ProjectStatus.DISPUTED
    await emit_event(db, project_id=pid, event_type=EventType.DISPUTE_OPENED, actor_id=cur.user_id, milestone_id=mid)
    await db.commit(); return {"dispute_id":d.id}

# Receipts
@app.post(f"{V}/projects/{{pid}}/receipts", status_code=201)
async def add_receipt(pid: str, body: dict, cur: CurrentUser = Depends(get_user), db: AsyncSession = Depends(get_db)):
    await guard_project(pid, cur, db)
    r = Receipt(project_id=pid, raw_text=body.get("raw_text"), file_url=body.get("file_url"))
    db.add(r); await db.commit()
    q_receipt.enqueue(task_process_receipt, r.id)
    return {"id":r.id,"status":r.processing_status}

@app.get(f"{V}/projects/{{pid}}/receipts")
async def list_receipts(pid: str, cur: CurrentUser = Depends(get_user), db: AsyncSession = Depends(get_db)):
    await guard_project(pid, cur, db)
    r = await db.execute(select(Receipt).where(Receipt.project_id==pid, Receipt.deleted_at==None))
    return [{"id":x.id,"vendor_name":x.vendor_name,"vendor_email":x.vendor_email,"amount":x.amount,"auto_linked":x.auto_linked,"status":x.processing_status} for x in r.scalars()]

# Companies
@app.post(f"{V}/companies", status_code=201)
async def create_company(body: CompanyIn, cur: CurrentUser = Depends(role_guard(UserRole.CONTRACTOR)), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(Company).where(Company.email==body.email.lower()))
    if r.scalar_one_or_none(): raise HTTPException(409, "Email taken")
    c = Company(name=body.name, email=body.email.lower(), phone=body.phone, license_number=body.license_number, owner_id=cur.user_id)
    db.add(c); await db.flush()
    r2 = await db.execute(select(Receipt).where(Receipt.vendor_email==body.email.lower(), Receipt.auto_linked==False))
    for rec in r2.scalars(): rec.auto_linked_company_id = c.id; rec.auto_linked = True
    await db.commit(); return {"id":c.id,"name":c.name,"email":c.email}

@app.get(f"{V}/companies/lookup")
async def lookup_company(email: str, cur: CurrentUser = Depends(get_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(Company).where(Company.email==email.lower()))
    c = r.scalar_one_or_none()
    if not c: raise HTTPException(404)
    return {"id":c.id,"name":c.name,"email":c.email,"verified":c.verified}

# Disputes
@app.get(f"{V}/disputes/{{did}}")
async def get_dispute(did: str, cur: CurrentUser = Depends(get_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(Dispute).where(Dispute.id==did))
    d = r.scalar_one_or_none()
    if not d: raise HTTPException(404)
    p = await guard_project(d.project_id, cur, db)
    r2 = await db.execute(select(DisputeComment).where(DisputeComment.dispute_id==did).order_by(DisputeComment.created_at))
    return {"id":d.id,"status":d.status,"reason":d.reason,"resolution":d.resolution,"outcome":d.outcome,
            "comments":[{"id":c.id,"author_id":c.author_id,"content":c.content,"created_at":c.created_at} for c in r2.scalars()]}

@app.post(f"{V}/disputes/{{did}}/comment")
async def comment_dispute(did: str, body: dict, cur: CurrentUser = Depends(get_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(Dispute).where(Dispute.id==did))
    d = r.scalar_one_or_none()
    if not d: raise HTTPException(404)
    await guard_project(d.project_id, cur, db)
    content = body.get("content","")
    if not content: raise HTTPException(400, "content required")
    c = DisputeComment(dispute_id=did, author_id=cur.user_id, content=content, file_urls=body.get("file_urls",[]))
    db.add(c); await db.commit(); return {"id":c.id}

@app.post(f"{V}/disputes/{{did}}/resolve")
async def resolve_dispute(did: str, body: dict, cur: CurrentUser = Depends(role_guard(UserRole.ADMIN)), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(Dispute).where(Dispute.id==did))
    d = r.scalar_one_or_none()
    if not d: raise HTTPException(404)
    p = await db.get(Project, d.project_id)
    outcome = body.get("outcome")
    if not outcome: raise HTTPException(400, "outcome required")
    d.status = DisputeStatus.RESOLVED; d.outcome = DisputeOutcome(outcome)
    d.resolved_by = cur.user_id; d.resolved_at = datetime.utcnow(); d.resolution = body.get("resolution","")
    if outcome == "FULL_REFUND":
        stripe.Refund.create(payment_intent=p.external_payment_id)
        p.status = ProjectStatus.REFUNDED
    elif outcome == "PARTIAL_REFUND":
        amt = body.get("refund_amount",0); d.refund_amount = amt
        stripe.Refund.create(payment_intent=p.external_payment_id, amount=amt)
    await emit_event(db, project_id=d.project_id, event_type=EventType.DISPUTE_RESOLVED, actor_id=cur.user_id, payload={"outcome":outcome})
    await db.commit(); return {"status":d.status,"outcome":d.outcome}

# Uploads (S3 signed URL flow)
@app.post(f"{V}/files/upload-tokens", status_code=201)
async def request_upload_token(body: UploadTokenIn, cur: CurrentUser = Depends(get_user), db: AsyncSession = Depends(get_db)):
    if not s3_client: raise HTTPException(503, "S3 not configured")
    key = s3_key(body.purpose.value, body.filename)
    max_size = {"MILESTONE_PROOF":50*1024*1024,"DISPUTE_EVIDENCE":50*1024*1024,"DOCUMENT":20*1024*1024,"RECEIPT":10*1024*1024}.get(body.purpose.value, 10*1024*1024)
    result = s3_client.generate_presigned_post(Bucket=cfg.AWS_S3_BUCKET, Key=key,
        Fields={"Content-Type":body.content_type},
        Conditions=[["content-length-range",1,max_size],["eq","$Content-Type",body.content_type]], ExpiresIn=300)
    token = UploadToken(user_id=cur.user_id, purpose=body.purpose, entity_id=body.entity_id,
        entity_type=body.entity_type, presigned_url=result["url"], presigned_fields=result["fields"],
        s3_key=key, expires_at=datetime.utcnow()+timedelta(minutes=5))
    db.add(token); await db.commit()
    return {"token_id":token.id,"presigned_url":result["url"],"presigned_fields":result["fields"],"public_url":s3_url(key)}

@app.post(f"{V}/files/upload-tokens/{{tid}}/confirm")
async def confirm_upload(tid: str, body: dict = {}, cur: CurrentUser = Depends(get_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(UploadToken).where(UploadToken.id==tid))
    t = r.scalar_one_or_none()
    if not t or t.user_id != cur.user_id: raise HTTPException(404)
    if t.used: raise HTTPException(400, "Already used")
    t.used = True
    if t.purpose == UploadPurpose.MILESTONE_PROOF:
        ptype = ProofType.VIDEO if any(t.s3_key.endswith(e) for e in [".mp4",".mov"]) else ProofType.PHOTO
        proof = MilestoneProof(milestone_id=t.entity_id, uploaded_by_id=cur.user_id, type=ptype,
            file_url=s3_url(t.s3_key), file_key=t.s3_key, mime_type="image/jpeg", size_bytes=0, caption=body.get("caption"))
        db.add(proof); await db.flush(); await db.commit(); return {"confirmed":True,"proof_id":proof.id}
    await db.commit(); return {"confirmed":True}

# Notifications
@app.get(f"{V}/notifications")
async def list_notifs(cur: CurrentUser = Depends(get_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(Notification).where(Notification.user_id==cur.user_id).order_by(Notification.created_at.desc()).limit(50))
    return [{"id":n.id,"type":n.type,"title":n.title,"body":n.body,"read":n.read,"created_at":n.created_at} for n in r.scalars()]

@app.post(f"{V}/notifications/{{nid}}/read")
async def mark_read(nid: str, cur: CurrentUser = Depends(get_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(Notification).where(Notification.id==nid, Notification.user_id==cur.user_id))
    n = r.scalar_one_or_none()
    if n: n.read = True; n.read_at = datetime.utcnow(); await db.commit()
    return {"ok":True}

# Admin
@app.get(f"{V}/admin/users")
async def admin_users(cur: CurrentUser = Depends(role_guard(UserRole.ADMIN)), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(User).where(User.deleted_at==None))
    return [{"id":u.id,"email":u.email,"role":u.role,"status":u.status,"created_at":u.created_at} for u in r.scalars()]

@app.patch(f"{V}/admin/users/{{uid_}}/status")
async def admin_user_status(uid_: str, body: dict, cur: CurrentUser = Depends(role_guard(UserRole.ADMIN)), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(User).where(User.id==uid_))
    u = r.scalar_one_or_none()
    if not u: raise HTTPException(404)
    u.status = UserStatus(body["status"]); await db.commit()
    return {"status":u.status}

@app.get(f"{V}/admin/audit-logs")
async def audit_logs(entity: Optional[str]=None, cur: CurrentUser = Depends(role_guard(UserRole.ADMIN)), db: AsyncSession = Depends(get_db)):
    q = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(100)
    if entity: q = q.where(AuditLog.entity==entity)
    r = await db.execute(q)
    return [{"id":a.id,"action":a.action,"entity":a.entity,"entity_id":a.entity_id,"actor_id":a.actor_id,"diff":a.diff,"created_at":a.created_at} for a in r.scalars()]

# Stripe webhook
@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    payload = await request.body(); sig = request.headers.get("stripe-signature","")
    try: event = stripe.Webhook.construct_event(payload, sig, cfg.STRIPE_WEBHOOK_SECRET)
    except: raise HTTPException(400, "Invalid signature")
    r = await db.execute(select(WebhookEvent).where(WebhookEvent.event_id==event["id"]))
    if r.scalar_one_or_none(): return {"status":"already_processed"}
    we = WebhookEvent(provider="stripe", event_id=event["id"], event_type=event["type"], payload=dict(event))
    db.add(we); await db.flush()
    try:
        data = event["data"]["object"]
        if event["type"] == "payment_intent.succeeded":
            r2 = await db.execute(select(Project).where(Project.external_payment_id==data["id"]))
            p = r2.scalar_one_or_none()
            if p and p.status == ProjectStatus.FUNDED:
                p.status = ProjectStatus.IN_PROGRESS
        elif event["type"] == "account.updated":
            r2 = await db.execute(select(User).where(User.stripe_account_id==data["id"]))
            u = r2.scalar_one_or_none()
            if u and data.get("charges_enabled") and data.get("payouts_enabled"): u.identity_verified = True
        we.processed = True; we.processed_at = datetime.utcnow()
    except Exception as e: we.error = str(e)
    await db.commit(); return {"status":"ok"}
