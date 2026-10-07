"""initial schema

Creates the extensions, enum types, invoice number sequence, every table with its
constraints and indexes, and the default application settings.

Revision ID: 0001
Revises:
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


EXTENSIONS = ("vector", "pg_trgm", "btree_gist", "pgcrypto", "citext")

# Enum values are frozen here on purpose: a migration must describe the schema as it
# was when the revision was written, regardless of later changes to application code.
ENUMS: dict[str, tuple[str, ...]] = {
    "user_role": ("patient", "receptionist", "dentist", "admin"),
    "patient_source": ("web", "chatbot", "walk_in", "referral"),
    "exception_reason": ("leave", "holiday", "training"),
    "appointment_status": (
        "booked", "confirmed", "checked_in", "completed", "cancelled", "no_show",
    ),
    "appointment_channel": ("web", "chatbot", "staff"),
    "invoice_status": ("draft", "issued", "partially_paid", "paid", "void"),
    "payment_method": ("card", "cash", "insurance", "bank_transfer"),
    "payer_type": ("patient", "insurer"),
    "reminder_kind": ("confirmation", "48h", "24h", "followup", "recall"),
    "reminder_channel": ("email",),
    "reminder_status": ("pending", "sent", "failed", "cancelled"),
    "chat_role": ("user", "assistant", "system"),
    "chat_route": ("rule", "cache", "faq_direct", "llm", "handoff"),
    "inquiry_source": ("contact_form", "chatbot_handoff", "callback_request"),
    "inquiry_status": ("new", "in_progress", "closed"),
}

DEFAULT_SETTINGS: dict[str, object] = {
    "booking_min_notice_hours": 2,
    "booking_max_horizon_days": 90,
    "booking_same_day_enabled": True,
    "booking_buffer_minutes": 10,
    "booking_slot_grid_minutes": 15,
    "cancellation_free_hours": 24,
    "receptionist_max_discount_percent": 10,
    "reminder_hours_before": [48, 24],
    "llm_primary": "groq",
    "llm_budget_failover_threshold": 0.8,
}


def _create_extensions() -> None:
    for name in EXTENSIONS:
        op.execute(f'CREATE EXTENSION IF NOT EXISTS "{name}"')


def _drop_extensions() -> None:
    for name in reversed(EXTENSIONS):
        op.execute(f'DROP EXTENSION IF EXISTS "{name}"')


def _create_enums() -> None:
    for name, values in ENUMS.items():
        labels = ", ".join(f"'{v}'" for v in values)
        op.execute(f"CREATE TYPE {name} AS ENUM ({labels})")


def _drop_enums() -> None:
    for name in reversed(ENUMS):
        op.execute(f"DROP TYPE IF EXISTS {name}")


def _seed_app_settings() -> None:
    settings = sa.table(
        "app_settings", sa.column("key", sa.String), sa.column("value", postgresql.JSONB)
    )
    op.bulk_insert(settings, [{"key": k, "value": v} for k, v in DEFAULT_SETTINGS.items()])


def upgrade() -> None:
    _create_extensions()
    _create_enums()
    op.execute(sa.schema.CreateSequence(sa.Sequence('invoice_number_seq', start=1000)))

    op.create_table('contact_inquiries',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=True),
    sa.Column('phone', sa.String(length=40), nullable=True),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('source', postgresql.ENUM('contact_form', 'chatbot_handoff', 'callback_request', name='inquiry_source', create_type=False), nullable=False),
    sa.Column('status', postgresql.ENUM('new', 'in_progress', 'closed', name='inquiry_status', create_type=False), server_default=sa.text("'new'"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_contact_inquiries'))
    )
    op.create_index('ix_contact_inquiries_status_created_at', 'contact_inquiries', ['status', 'created_at'], unique=False)
    op.create_table('insurance_providers',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('plan_types', sa.ARRAY(sa.String(length=60)), server_default=sa.text("'{}'::varchar[]"), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_insurance_providers')),
    sa.UniqueConstraint('name', name=op.f('uq_insurance_providers_name'))
    )
    op.create_table('intent_examples',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('intent', sa.String(length=60), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(dim=384), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_intent_examples'))
    )
    op.create_index('ix_intent_examples_embedding_hnsw', 'intent_examples', ['embedding'], unique=False, postgresql_using='hnsw', postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.create_index('ix_intent_examples_intent', 'intent_examples', ['intent'], unique=False)
    op.create_table('kb_documents',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('slug', sa.String(length=120), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('category', sa.String(length=60), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('short_answer', sa.Text(), nullable=True),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_kb_documents')),
    sa.UniqueConstraint('slug', name=op.f('uq_kb_documents_slug'))
    )
    op.create_table('newsletter_subscribers',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('email', postgresql.CITEXT(), nullable=False),
    sa.Column('subscribed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('unsubscribed_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_newsletter_subscribers')),
    sa.UniqueConstraint('email', name=op.f('uq_newsletter_subscribers_email'))
    )
    op.create_table('services',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('code', sa.String(length=20), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('category', sa.String(length=60), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('duration_min', sa.Integer(), nullable=False),
    sa.Column('base_price', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('display_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.CheckConstraint('base_price >= 0', name=op.f('ck_services_price_non_negative')),
    sa.CheckConstraint('duration_min > 0', name=op.f('ck_services_duration_positive')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_services')),
    sa.UniqueConstraint('code', name=op.f('uq_services_code'))
    )
    op.create_table('testimonials',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('first_name', sa.String(length=80), nullable=False),
    sa.Column('last_initial', sa.String(length=1), nullable=False),
    sa.Column('treatment', sa.String(length=120), nullable=True),
    sa.Column('rating', sa.SmallInteger(), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('is_published', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('rating BETWEEN 1 AND 5', name=op.f('ck_testimonials_rating_range')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_testimonials'))
    )
    op.create_table('users',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('email', postgresql.CITEXT(), nullable=False),
    sa.Column('password_hash', sa.Text(), nullable=False),
    sa.Column('role', postgresql.ENUM('patient', 'receptionist', 'dentist', 'admin', name='user_role', create_type=False), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('mfa_secret_enc', sa.Text(), nullable=True),
    sa.Column('mfa_enabled', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('failed_logins', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('email', name=op.f('uq_users_email'))
    )
    op.create_table('app_settings',
    sa.Column('key', sa.String(length=100), nullable=False),
    sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], name=op.f('fk_app_settings_updated_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('key', name=op.f('pk_app_settings'))
    )
    op.create_table('audit_logs',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('actor_id', sa.UUID(), nullable=True),
    sa.Column('actor_role', sa.String(length=30), nullable=True),
    sa.Column('action', sa.String(length=80), nullable=False),
    sa.Column('entity', sa.String(length=80), nullable=True),
    sa.Column('entity_id', sa.String(length=80), nullable=True),
    sa.Column('ip', postgresql.INET(), nullable=True),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], name=op.f('fk_audit_logs_actor_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_logs'))
    )
    op.create_index('ix_audit_logs_actor_id', 'audit_logs', ['actor_id'], unique=False)
    op.create_index('ix_audit_logs_created_at', 'audit_logs', ['created_at'], unique=False)
    op.create_index('ix_audit_logs_entity_entity_id', 'audit_logs', ['entity', 'entity_id'], unique=False)
    op.create_table('chat_sessions',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=True),
    sa.Column('anon_token_hash', sa.String(length=128), nullable=True),
    sa.Column('state', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('provider_last', sa.String(length=30), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_chat_sessions_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_chat_sessions'))
    )
    op.create_index('ix_chat_sessions_created_at', 'chat_sessions', ['created_at'], unique=False)
    op.create_index('ix_chat_sessions_user_id', 'chat_sessions', ['user_id'], unique=False)
    op.create_table('dentists',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=True),
    sa.Column('full_name', sa.String(length=200), nullable=False),
    sa.Column('specialty', sa.String(length=100), nullable=False),
    sa.Column('bio', sa.Text(), nullable=True),
    sa.Column('photo_url', sa.String(length=500), nullable=True),
    sa.Column('license_no', sa.String(length=60), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('color', sa.String(length=7), server_default=sa.text("'#13A3A1'"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_dentists_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_dentists')),
    sa.UniqueConstraint('license_no', name=op.f('uq_dentists_license_no')),
    sa.UniqueConstraint('user_id', name=op.f('uq_dentists_user_id'))
    )
    op.create_table('kb_chunks',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('chunk_index', sa.Integer(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('token_count', sa.Integer(), nullable=False),
    sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(dim=384), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['kb_documents.id'], name=op.f('fk_kb_chunks_document_id_kb_documents'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_kb_chunks')),
    sa.UniqueConstraint('document_id', 'chunk_index', name='uq_kb_chunks_document_chunk')
    )
    op.create_index('ix_kb_chunks_embedding_hnsw', 'kb_chunks', ['embedding'], unique=False, postgresql_using='hnsw', postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.create_table('patients',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=True),
    sa.Column('first_name', sa.String(length=100), nullable=False),
    sa.Column('last_name', sa.String(length=100), nullable=False),
    sa.Column('dob_enc', sa.Text(), nullable=True),
    sa.Column('phone_enc', sa.Text(), nullable=True),
    sa.Column('email', sa.String(length=320), nullable=True),
    sa.Column('address_enc', sa.Text(), nullable=True),
    sa.Column('insurance_provider_id', sa.UUID(), nullable=True),
    sa.Column('insurance_member_id_enc', sa.Text(), nullable=True),
    sa.Column('marketing_consent', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('source', postgresql.ENUM('web', 'chatbot', 'walk_in', 'referral', name='patient_source', create_type=False), server_default=sa.text("'web'"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['insurance_provider_id'], ['insurance_providers.id'], name=op.f('fk_patients_insurance_provider_id_insurance_providers'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_patients_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_patients')),
    sa.UniqueConstraint('user_id', name=op.f('uq_patients_user_id'))
    )
    op.create_index('ix_patients_email', 'patients', ['email'], unique=False)
    op.create_index('ix_patients_first_name_trgm', 'patients', ['first_name'], unique=False, postgresql_using='gin', postgresql_ops={'first_name': 'gin_trgm_ops'})
    op.create_index('ix_patients_last_name_trgm', 'patients', ['last_name'], unique=False, postgresql_using='gin', postgresql_ops={'last_name': 'gin_trgm_ops'})
    op.create_index('ix_patients_user_id', 'patients', ['user_id'], unique=False)
    op.create_table('refresh_tokens',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('token_hash', sa.String(length=128), nullable=False),
    sa.Column('family_id', sa.UUID(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('replaced_by', sa.UUID(), nullable=True),
    sa.Column('user_agent', sa.String(length=400), nullable=True),
    sa.Column('ip', postgresql.INET(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['replaced_by'], ['refresh_tokens.id'], name=op.f('fk_refresh_tokens_replaced_by_refresh_tokens'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_refresh_tokens_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_refresh_tokens')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_refresh_tokens_token_hash'))
    )
    op.create_index('ix_refresh_tokens_family_id', 'refresh_tokens', ['family_id'], unique=False)
    op.create_index('ix_refresh_tokens_user_id', 'refresh_tokens', ['user_id'], unique=False)
    op.create_table('appointments',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('patient_id', sa.UUID(), nullable=False),
    sa.Column('dentist_id', sa.UUID(), nullable=False),
    sa.Column('service_id', sa.UUID(), nullable=False),
    sa.Column('slot', postgresql.TSTZRANGE(), nullable=False),
    sa.Column('status', postgresql.ENUM('booked', 'confirmed', 'checked_in', 'completed', 'cancelled', 'no_show', name='appointment_status', create_type=False), nullable=False),
    sa.Column('channel', postgresql.ENUM('web', 'chatbot', 'staff', name='appointment_channel', create_type=False), nullable=False),
    sa.Column('reason_note', sa.Text(), nullable=True),
    sa.Column('cancel_reason', sa.Text(), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('rescheduled_from', sa.UUID(), nullable=True),
    postgresql.ExcludeConstraint((sa.column('dentist_id'), '='), (sa.column('slot'), '&&'), where=sa.text("status IN ('booked', 'confirmed', 'checked_in', 'completed')"), using='gist', name='ex_appointments_dentist_no_overlap'),
    postgresql.ExcludeConstraint((sa.column('patient_id'), '='), (sa.column('slot'), '&&'), where=sa.text("status IN ('booked', 'confirmed', 'checked_in', 'completed')"), using='gist', name='ex_appointments_patient_no_overlap'),
    sa.CheckConstraint('NOT isempty(slot) AND NOT lower_inf(slot) AND NOT upper_inf(slot)', name=op.f('ck_appointments_slot_bounded')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_appointments_created_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['dentist_id'], ['dentists.id'], name=op.f('fk_appointments_dentist_id_dentists'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], name=op.f('fk_appointments_patient_id_patients'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['rescheduled_from'], ['appointments.id'], name=op.f('fk_appointments_rescheduled_from_appointments'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['service_id'], ['services.id'], name=op.f('fk_appointments_service_id_services'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_appointments'))
    )
    op.create_index('ix_appointments_dentist_slot_start', 'appointments', ['dentist_id', sa.literal_column('lower(slot)')], unique=False)
    op.create_index('ix_appointments_patient_id', 'appointments', ['patient_id'], unique=False)
    op.create_index('ix_appointments_status', 'appointments', ['status'], unique=False)
    op.create_table('chat_messages',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('session_id', sa.UUID(), nullable=False),
    sa.Column('role', postgresql.ENUM('user', 'assistant', 'system', name='chat_role', create_type=False), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('intent', sa.String(length=60), nullable=True),
    sa.Column('route', postgresql.ENUM('rule', 'cache', 'faq_direct', 'llm', 'handoff', name='chat_route', create_type=False), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['chat_sessions.id'], name=op.f('fk_chat_messages_session_id_chat_sessions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_chat_messages'))
    )
    op.create_index('ix_chat_messages_session_id_created_at', 'chat_messages', ['session_id', 'created_at'], unique=False)
    op.create_table('dentist_schedules',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('dentist_id', sa.UUID(), nullable=False),
    sa.Column('weekday', sa.SmallInteger(), nullable=False),
    sa.Column('start_time', sa.Time(), nullable=False),
    sa.Column('end_time', sa.Time(), nullable=False),
    sa.Column('break_start', sa.Time(), nullable=True),
    sa.Column('break_end', sa.Time(), nullable=True),
    sa.CheckConstraint('(break_start IS NULL) = (break_end IS NULL)', name=op.f('ck_dentist_schedules_break_pair')),
    sa.CheckConstraint('break_start IS NULL OR (break_start < break_end AND break_start >= start_time AND break_end <= end_time)', name=op.f('ck_dentist_schedules_break_within_hours')),
    sa.CheckConstraint('start_time < end_time', name=op.f('ck_dentist_schedules_hours_order')),
    sa.CheckConstraint('weekday BETWEEN 0 AND 6', name=op.f('ck_dentist_schedules_weekday_range')),
    sa.ForeignKeyConstraint(['dentist_id'], ['dentists.id'], name=op.f('fk_dentist_schedules_dentist_id_dentists'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_dentist_schedules')),
    sa.UniqueConstraint('dentist_id', 'weekday', name='uq_dentist_schedules_dentist_weekday')
    )
    op.create_table('dentist_services',
    sa.Column('dentist_id', sa.UUID(), nullable=False),
    sa.Column('service_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['dentist_id'], ['dentists.id'], name=op.f('fk_dentist_services_dentist_id_dentists'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['service_id'], ['services.id'], name=op.f('fk_dentist_services_service_id_services'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('dentist_id', 'service_id', name=op.f('pk_dentist_services'))
    )
    op.create_table('llm_usage',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('session_id', sa.UUID(), nullable=True),
    sa.Column('provider', sa.String(length=30), nullable=False),
    sa.Column('model', sa.String(length=100), nullable=False),
    sa.Column('purpose', sa.String(length=60), nullable=False),
    sa.Column('prompt_tokens', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('completion_tokens', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('latency_ms', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['chat_sessions.id'], name=op.f('fk_llm_usage_session_id_chat_sessions'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_llm_usage'))
    )
    op.create_index('ix_llm_usage_created_at', 'llm_usage', ['created_at'], unique=False)
    op.create_table('schedule_exceptions',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('dentist_id', sa.UUID(), nullable=False),
    sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('reason', postgresql.ENUM('leave', 'holiday', 'training', name='exception_reason', create_type=False), nullable=False),
    sa.Column('note', sa.String(length=400), nullable=True),
    sa.CheckConstraint('starts_at < ends_at', name=op.f('ck_schedule_exceptions_range_order')),
    sa.ForeignKeyConstraint(['dentist_id'], ['dentists.id'], name=op.f('fk_schedule_exceptions_dentist_id_dentists'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_schedule_exceptions'))
    )
    op.create_index('ix_schedule_exceptions_dentist_id_starts_at', 'schedule_exceptions', ['dentist_id', 'starts_at'], unique=False)
    op.create_table('appointment_status_history',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('appointment_id', sa.UUID(), nullable=False),
    sa.Column('from_status', postgresql.ENUM('booked', 'confirmed', 'checked_in', 'completed', 'cancelled', 'no_show', name='appointment_status', create_type=False), nullable=True),
    sa.Column('to_status', postgresql.ENUM('booked', 'confirmed', 'checked_in', 'completed', 'cancelled', 'no_show', name='appointment_status', create_type=False), nullable=False),
    sa.Column('changed_by', sa.UUID(), nullable=True),
    sa.Column('changed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['appointment_id'], ['appointments.id'], name=op.f('fk_appointment_status_history_appointment_id_appointments'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['changed_by'], ['users.id'], name=op.f('fk_appointment_status_history_changed_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_appointment_status_history'))
    )
    op.create_index('ix_appointment_status_history_appointment_id', 'appointment_status_history', ['appointment_id'], unique=False)
    op.create_table('invoices',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('appointment_id', sa.UUID(), nullable=False),
    sa.Column('patient_id', sa.UUID(), nullable=False),
    sa.Column('number', sa.BigInteger(), server_default=sa.text("nextval('invoice_number_seq')"), nullable=False),
    sa.Column('issued_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('subtotal', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('discount', sa.Numeric(precision=12, scale=2), server_default=sa.text('0'), nullable=False),
    sa.Column('tax', sa.Numeric(precision=12, scale=2), server_default=sa.text('0'), nullable=False),
    sa.Column('total', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('insurance_expected', sa.Numeric(precision=12, scale=2), server_default=sa.text('0'), nullable=False),
    sa.Column('status', postgresql.ENUM('draft', 'issued', 'partially_paid', 'paid', 'void', name='invoice_status', create_type=False), server_default=sa.text("'draft'"), nullable=False),
    sa.CheckConstraint('discount <= subtotal', name=op.f('ck_invoices_discount_within_subtotal')),
    sa.CheckConstraint('insurance_expected >= 0', name=op.f('ck_invoices_insurance_non_negative')),
    sa.CheckConstraint('subtotal >= 0 AND discount >= 0 AND tax >= 0', name=op.f('ck_invoices_amounts_non_negative')),
    sa.CheckConstraint('total = subtotal - discount + tax', name=op.f('ck_invoices_total_matches_components')),
    sa.ForeignKeyConstraint(['appointment_id'], ['appointments.id'], name=op.f('fk_invoices_appointment_id_appointments'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], name=op.f('fk_invoices_patient_id_patients'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_invoices')),
    sa.UniqueConstraint('number', name=op.f('uq_invoices_number'))
    )
    op.create_index('ix_invoices_issued_at', 'invoices', ['issued_at'], unique=False)
    op.create_index('ix_invoices_patient_id', 'invoices', ['patient_id'], unique=False)
    op.create_index('ix_invoices_status', 'invoices', ['status'], unique=False)
    op.create_index('uq_invoices_live_appointment', 'invoices', ['appointment_id'], unique=True, postgresql_where=sa.text("status <> 'void'"))
    op.create_table('reminders',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('appointment_id', sa.UUID(), nullable=False),
    sa.Column('kind', postgresql.ENUM('confirmation', '48h', '24h', 'followup', 'recall', name='reminder_kind', create_type=False), nullable=False),
    sa.Column('channel', postgresql.ENUM('email', name='reminder_channel', create_type=False), nullable=False),
    sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', postgresql.ENUM('pending', 'sent', 'failed', 'cancelled', name='reminder_status', create_type=False), nullable=False),
    sa.Column('error', sa.String(length=400), nullable=True),
    sa.ForeignKeyConstraint(['appointment_id'], ['appointments.id'], name=op.f('fk_reminders_appointment_id_appointments'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_reminders')),
    sa.UniqueConstraint('appointment_id', 'kind', name='uq_reminders_appointment_kind')
    )
    op.create_index('ix_reminders_status_scheduled_at', 'reminders', ['status', 'scheduled_at'], unique=False)
    op.create_table('invoice_items',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('invoice_id', sa.UUID(), nullable=False),
    sa.Column('service_id', sa.UUID(), nullable=True),
    sa.Column('description', sa.String(length=300), nullable=False),
    sa.Column('qty', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('unit_price', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.CheckConstraint('amount = round(qty * unit_price, 2)', name=op.f('ck_invoice_items_amount_matches_qty_price')),
    sa.CheckConstraint('qty > 0', name=op.f('ck_invoice_items_qty_positive')),
    sa.CheckConstraint('unit_price >= 0', name=op.f('ck_invoice_items_unit_price_non_negative')),
    sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], name=op.f('fk_invoice_items_invoice_id_invoices'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['service_id'], ['services.id'], name=op.f('fk_invoice_items_service_id_services'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_invoice_items'))
    )
    op.create_index('ix_invoice_items_invoice_id', 'invoice_items', ['invoice_id'], unique=False)
    op.create_table('payments',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('invoice_id', sa.UUID(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('method', postgresql.ENUM('card', 'cash', 'insurance', 'bank_transfer', name='payment_method', create_type=False), nullable=False),
    sa.Column('payer_type', postgresql.ENUM('patient', 'insurer', name='payer_type', create_type=False), nullable=False),
    sa.Column('paid_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('reference', sa.Text(), nullable=True),
    sa.CheckConstraint('amount > 0', name=op.f('ck_payments_amount_positive')),
    sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], name=op.f('fk_payments_invoice_id_invoices'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_payments'))
    )
    op.create_index('ix_payments_invoice_id', 'payments', ['invoice_id'], unique=False)
    op.create_index('ix_payments_paid_at', 'payments', ['paid_at'], unique=False)
    _seed_app_settings()


def downgrade() -> None:
    op.drop_index('ix_payments_paid_at', table_name='payments')
    op.drop_index('ix_payments_invoice_id', table_name='payments')
    op.drop_table('payments')
    op.drop_index('ix_invoice_items_invoice_id', table_name='invoice_items')
    op.drop_table('invoice_items')
    op.drop_index('ix_reminders_status_scheduled_at', table_name='reminders')
    op.drop_table('reminders')
    op.drop_index('uq_invoices_live_appointment', table_name='invoices', postgresql_where=sa.text("status <> 'void'"))
    op.drop_index('ix_invoices_status', table_name='invoices')
    op.drop_index('ix_invoices_patient_id', table_name='invoices')
    op.drop_index('ix_invoices_issued_at', table_name='invoices')
    op.drop_table('invoices')
    op.drop_index('ix_appointment_status_history_appointment_id', table_name='appointment_status_history')
    op.drop_table('appointment_status_history')
    op.drop_index('ix_schedule_exceptions_dentist_id_starts_at', table_name='schedule_exceptions')
    op.drop_table('schedule_exceptions')
    op.drop_index('ix_llm_usage_created_at', table_name='llm_usage')
    op.drop_table('llm_usage')
    op.drop_table('dentist_services')
    op.drop_table('dentist_schedules')
    op.drop_index('ix_chat_messages_session_id_created_at', table_name='chat_messages')
    op.drop_table('chat_messages')
    op.drop_index('ix_appointments_status', table_name='appointments')
    op.drop_index('ix_appointments_patient_id', table_name='appointments')
    op.drop_index('ix_appointments_dentist_slot_start', table_name='appointments')
    op.drop_table('appointments')
    op.drop_index('ix_refresh_tokens_user_id', table_name='refresh_tokens')
    op.drop_index('ix_refresh_tokens_family_id', table_name='refresh_tokens')
    op.drop_table('refresh_tokens')
    op.drop_index('ix_patients_user_id', table_name='patients')
    op.drop_index('ix_patients_last_name_trgm', table_name='patients', postgresql_using='gin', postgresql_ops={'last_name': 'gin_trgm_ops'})
    op.drop_index('ix_patients_first_name_trgm', table_name='patients', postgresql_using='gin', postgresql_ops={'first_name': 'gin_trgm_ops'})
    op.drop_index('ix_patients_email', table_name='patients')
    op.drop_table('patients')
    op.drop_index('ix_kb_chunks_embedding_hnsw', table_name='kb_chunks', postgresql_using='hnsw', postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.drop_table('kb_chunks')
    op.drop_table('dentists')
    op.drop_index('ix_chat_sessions_user_id', table_name='chat_sessions')
    op.drop_index('ix_chat_sessions_created_at', table_name='chat_sessions')
    op.drop_table('chat_sessions')
    op.drop_index('ix_audit_logs_entity_entity_id', table_name='audit_logs')
    op.drop_index('ix_audit_logs_created_at', table_name='audit_logs')
    op.drop_index('ix_audit_logs_actor_id', table_name='audit_logs')
    op.drop_table('audit_logs')
    op.drop_table('app_settings')
    op.drop_table('users')
    op.drop_table('testimonials')
    op.drop_table('services')
    op.drop_table('newsletter_subscribers')
    op.drop_table('kb_documents')
    op.drop_index('ix_intent_examples_intent', table_name='intent_examples')
    op.drop_index('ix_intent_examples_embedding_hnsw', table_name='intent_examples', postgresql_using='hnsw', postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.drop_table('intent_examples')
    op.drop_table('insurance_providers')
    op.drop_index('ix_contact_inquiries_status_created_at', table_name='contact_inquiries')
    op.drop_table('contact_inquiries')

    op.execute(sa.schema.DropSequence(sa.Sequence('invoice_number_seq')))
    _drop_enums()
    _drop_extensions()
