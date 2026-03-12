"""init

Revision ID: 0001
Revises: 
Create Date: 2026-03-11

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('users',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('password_hash', sa.String(), nullable=False),
        sa.Column('role', sa.Enum('HOMEOWNER','CONTRACTOR','ADMIN', name='userrole'), nullable=False),
        sa.Column('status', sa.Enum('ACTIVE','SUSPENDED','BANNED', name='userstatus'), nullable=False),
        sa.Column('first_name', sa.String(), nullable=False),
        sa.Column('last_name', sa.String(), nullable=False),
        sa.Column('phone', sa.String(), nullable=True),
        sa.Column('stripe_account_id', sa.String(), nullable=True),
        sa.Column('stripe_customer_id', sa.String(), nullable=True),
        sa.Column('identity_verified', sa.Boolean(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email'),
        sa.UniqueConstraint('stripe_account_id'),
        sa.UniqueConstraint('stripe_customer_id'),
    )
    op.create_index('ix_users_email', 'users', ['email'])

    op.create_table('companies',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('phone', sa.String(), nullable=True),
        sa.Column('license_number', sa.String(), nullable=True),
        sa.Column('owner_id', sa.String(), nullable=False),
        sa.Column('stripe_account_id', sa.String(), nullable=True),
        sa.Column('verified', sa.Boolean(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email'),
        sa.UniqueConstraint('owner_id'),
        sa.UniqueConstraint('stripe_account_id'),
    )
    op.create_index('ix_companies_email', 'companies', ['email'])

    op.create_table('sessions',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('token', sa.String(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token'),
    )

    op.create_table('refresh_tokens',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('token', sa.String(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token'),
    )

    op.create_table('payment_provider_accounts',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('provider', sa.Enum('STRIPE', name='paymentprovider'), nullable=False),
        sa.Column('external_id', sa.String(), nullable=False),
        sa.Column('account_type', sa.String(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('meta', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'provider', 'account_type'),
    )
    op.create_index('ix_ppa_user', 'payment_provider_accounts', ['user_id'])

    op.create_table('inspectors',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('license_number', sa.String(), nullable=True),
        sa.Column('service_areas', sa.JSON(), nullable=True),
        sa.Column('rating', sa.Float(), nullable=False),
        sa.Column('available', sa.Boolean(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id'),
    )

    op.create_table('projects',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('category', sa.Enum('ROOFING','HVAC','KITCHEN_REMODEL','BATHROOM_REMODEL','POOL_INSTALLATION','LANDSCAPING','ELECTRICAL','PLUMBING','FLOORING','PAINTING','GENERAL_CONSTRUCTION','OTHER', name='projectcategory'), nullable=False),
        sa.Column('status', sa.Enum('DRAFT','AWAITING_FUNDING','FUNDED','IN_PROGRESS','COMPLETED','DISPUTED','CANCELLED','REFUNDED', name='projectstatus'), nullable=False),
        sa.Column('homeowner_id', sa.String(), nullable=False),
        sa.Column('contractor_id', sa.String(), nullable=True),
        sa.Column('company_id', sa.String(), nullable=True),
        sa.Column('address_line1', sa.String(), nullable=False),
        sa.Column('city', sa.String(), nullable=False),
        sa.Column('state', sa.String(2), nullable=False),
        sa.Column('zip_code', sa.String(), nullable=False),
        sa.Column('total_amount', sa.Integer(), nullable=False),
        sa.Column('platform_fee_percent', sa.Float(), nullable=False),
        sa.Column('platform_fee', sa.Integer(), nullable=False),
        sa.Column('contractor_payout', sa.Integer(), nullable=False),
        sa.Column('external_payment_id', sa.String(), nullable=True),
        sa.Column('escrow_funded', sa.Boolean(), nullable=False),
        sa.Column('escrow_funded_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(), nullable=True),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['homeowner_id'], ['users.id']),
        sa.ForeignKeyConstraint(['contractor_id'], ['users.id']),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('external_payment_id'),
    )
    op.create_index('ix_projects_homeowner', 'projects', ['homeowner_id'])
    op.create_index('ix_projects_status', 'projects', ['status'])

    op.create_table('milestones',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('project_id', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('order', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Integer(), nullable=False),
        sa.Column('status', sa.Enum('PENDING','IN_PROGRESS','SUBMITTED','AI_REVIEWING','HOMEOWNER_REVIEW','APPROVED','DISPUTED','PAYMENT_RELEASED', name='milestonestatus'), nullable=False),
        sa.Column('due_date', sa.DateTime(), nullable=True),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.Column('released_at', sa.DateTime(), nullable=True),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_milestones_project', 'milestones', ['project_id'])

    op.create_table('milestone_proofs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('milestone_id', sa.String(), nullable=False),
        sa.Column('uploaded_by_id', sa.String(), nullable=False),
        sa.Column('type', sa.Enum('PHOTO','VIDEO','DOCUMENT', name='prooftype'), nullable=False),
        sa.Column('file_url', sa.String(), nullable=False),
        sa.Column('file_key', sa.String(), nullable=False),
        sa.Column('mime_type', sa.String(), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('caption', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['milestone_id'], ['milestones.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['uploaded_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('ai_verifications',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('milestone_id', sa.String(), nullable=False),
        sa.Column('status', sa.Enum('PENDING','PROCESSING','COMPLETED','FAILED', name='aistatus'), nullable=False),
        sa.Column('confidence_score', sa.Float(), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('issues', sa.JSON(), nullable=True),
        sa.Column('recommendation', sa.Enum('APPROVE','REJECT','HUMAN_REVIEW', name='airec'), nullable=True),
        sa.Column('attempt_count', sa.Integer(), nullable=False),
        sa.Column('failure_reason', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['milestone_id'], ['milestones.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('milestone_id'),
    )

    op.create_table('payment_ledger',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('project_id', sa.String(), nullable=False),
        sa.Column('milestone_id', sa.String(), nullable=True),
        sa.Column('type', sa.Enum('ESCROW_FUNDED','PLATFORM_FEE','MILESTONE_RELEASED','PARTIAL_REFUND','FULL_REFUND','ADJUSTMENT', name='ledgertype'), nullable=False),
        sa.Column('direction', sa.Enum('CREDIT','DEBIT', name='ledgerdir'), nullable=False),
        sa.Column('amount_cents', sa.Integer(), nullable=False),
        sa.Column('balance_cents', sa.Integer(), nullable=False),
        sa.Column('external_ref', sa.String(), nullable=True),
        sa.Column('idempotency_key', sa.String(), nullable=True),
        sa.Column('description', sa.String(), nullable=False),
        sa.Column('actor_id', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
        sa.ForeignKeyConstraint(['milestone_id'], ['milestones.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('idempotency_key'),
    )
    op.create_index('ix_ledger_project', 'payment_ledger', ['project_id'])

    op.create_table('project_events',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('project_id', sa.String(), nullable=False),
        sa.Column('event_type', sa.Enum('PROJECT_CREATED','CONTRACTOR_ASSIGNED','ESCROW_FUNDED','MILESTONE_SUBMITTED','AI_DONE','MILESTONE_APPROVED','PAYMENT_RELEASED','DISPUTE_OPENED','DISPUTE_RESOLVED','PROJECT_COMPLETED','PROJECT_CANCELLED','COMPANY_AUTO_LINKED', name='eventtype'), nullable=False),
        sa.Column('actor_id', sa.String(), nullable=True),
        sa.Column('from_status', sa.Enum('DRAFT','AWAITING_FUNDING','FUNDED','IN_PROGRESS','COMPLETED','DISPUTED','CANCELLED','REFUNDED', name='projectstatus'), nullable=True),
        sa.Column('to_status', sa.Enum('DRAFT','AWAITING_FUNDING','FUNDED','IN_PROGRESS','COMPLETED','DISPUTED','CANCELLED','REFUNDED', name='projectstatus'), nullable=True),
        sa.Column('milestone_id', sa.String(), nullable=True),
        sa.Column('payload', sa.JSON(), nullable=True),
        sa.Column('source', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_events_project', 'project_events', ['project_id'])

    op.create_table('disputes',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('project_id', sa.String(), nullable=False),
        sa.Column('initiated_by', sa.String(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('status', sa.Enum('OPEN','UNDER_REVIEW','RESOLVED', name='disputestatus'), nullable=False),
        sa.Column('resolution', sa.Text(), nullable=True),
        sa.Column('resolved_by', sa.String(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.Column('outcome', sa.Enum('FULL_RELEASE','PARTIAL_RELEASE','FULL_REFUND','PARTIAL_REFUND', name='disputeoutcome'), nullable=True),
        sa.Column('refund_amount', sa.Integer(), nullable=True),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
        sa.ForeignKeyConstraint(['initiated_by'], ['users.id']),
        sa.ForeignKeyConstraint(['resolved_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_disputes_project', 'disputes', ['project_id'])

    op.create_table('dispute_comments',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('dispute_id', sa.String(), nullable=False),
        sa.Column('author_id', sa.String(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('file_urls', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['dispute_id'], ['disputes.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['author_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('inspection_requests',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('dispute_id', sa.String(), nullable=False),
        sa.Column('inspector_id', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('scheduled_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['dispute_id'], ['disputes.id']),
        sa.ForeignKeyConstraint(['inspector_id'], ['inspectors.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('dispute_id'),
    )

    op.create_table('receipts',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('project_id', sa.String(), nullable=False),
        sa.Column('raw_text', sa.Text(), nullable=True),
        sa.Column('file_url', sa.String(), nullable=True),
        sa.Column('vendor_email', sa.String(), nullable=True),
        sa.Column('vendor_name', sa.String(), nullable=True),
        sa.Column('amount', sa.Integer(), nullable=True),
        sa.Column('receipt_date', sa.DateTime(), nullable=True),
        sa.Column('items', sa.JSON(), nullable=True),
        sa.Column('auto_linked_company_id', sa.String(), nullable=True),
        sa.Column('auto_linked', sa.Boolean(), nullable=False),
        sa.Column('processing_status', sa.Enum('PENDING','PROCESSING','COMPLETED','FAILED', name='receiptstatus'), nullable=False),
        sa.Column('processing_error', sa.String(), nullable=True),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_receipts_vendor_email', 'receipts', ['vendor_email'])

    op.create_table('documents',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('project_id', sa.String(), nullable=False),
        sa.Column('uploaded_by_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('file_url', sa.String(), nullable=False),
        sa.Column('file_key', sa.String(), nullable=False),
        sa.Column('mime_type', sa.String(), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['uploaded_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('proof_of_funds_certs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('project_id', sa.String(), nullable=False),
        sa.Column('cert_number', sa.String(), nullable=False),
        sa.Column('issued_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id'),
        sa.UniqueConstraint('cert_number'),
    )

    op.create_table('notifications',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('project_id', sa.String(), nullable=True),
        sa.Column('type', sa.Enum('PROJECT_FUNDED','MILESTONE_SUBMITTED','MILESTONE_APPROVED','PAYMENT_RELEASED','DISPUTE_OPENED','DISPUTE_RESOLVED','COMPANY_DETECTED','GENERAL', name='notiftype'), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('body', sa.String(), nullable=False),
        sa.Column('read', sa.Boolean(), nullable=False),
        sa.Column('read_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_notifs_user', 'notifications', ['user_id', 'read'])

    op.create_table('audit_logs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('actor_id', sa.String(), nullable=True),
        sa.Column('actor_role', sa.String(), nullable=True),
        sa.Column('action', sa.String(), nullable=False),
        sa.Column('entity', sa.String(), nullable=False),
        sa.Column('entity_id', sa.String(), nullable=False),
        sa.Column('before', sa.JSON(), nullable=True),
        sa.Column('after', sa.JSON(), nullable=True),
        sa.Column('diff', sa.JSON(), nullable=True),
        sa.Column('project_id', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_audit_entity', 'audit_logs', ['entity', 'entity_id'])

    op.create_table('upload_tokens',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('purpose', sa.Enum('MILESTONE_PROOF','DISPUTE_EVIDENCE','DOCUMENT','RECEIPT', name='uploadpurpose'), nullable=False),
        sa.Column('entity_id', sa.String(), nullable=False),
        sa.Column('entity_type', sa.String(), nullable=False),
        sa.Column('presigned_url', sa.String(), nullable=False),
        sa.Column('presigned_fields', sa.JSON(), nullable=False),
        sa.Column('s3_key', sa.String(), nullable=False),
        sa.Column('used', sa.Boolean(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('webhook_events',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('provider', sa.String(), nullable=False),
        sa.Column('event_id', sa.String(), nullable=False),
        sa.Column('event_type', sa.String(), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('processed', sa.Boolean(), nullable=False),
        sa.Column('processed_at', sa.DateTime(), nullable=True),
        sa.Column('error', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('event_id'),
    )
    op.create_index('ix_webhook_event_id', 'webhook_events', ['event_id'])


def downgrade() -> None:
    op.drop_table('webhook_events')
    op.drop_table('upload_tokens')
    op.drop_table('audit_logs')
    op.drop_table('notifications')
    op.drop_table('proof_of_funds_certs')
    op.drop_table('documents')
    op.drop_table('receipts')
    op.drop_table('inspection_requests')
    op.drop_table('dispute_comments')
    op.drop_table('disputes')
    op.drop_table('project_events')
    op.drop_table('payment_ledger')
    op.drop_table('ai_verifications')
    op.drop_table('milestone_proofs')
    op.drop_table('milestones')
    op.drop_table('projects')
    op.drop_table('inspectors')
    op.drop_table('payment_provider_accounts')
    op.drop_table('refresh_tokens')
    op.drop_table('sessions')
    op.drop_table('companies')
    op.drop_table('users')
