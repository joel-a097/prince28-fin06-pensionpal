"""add isolated local-model document chunks

Revision ID: f31a9d8c0b27
Revises: a4d73e6192f0
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "f31a9d8c0b27"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "a4d73e6192f0"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_chunks_local",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("page_no", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "headings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("embedding_model", sa.String(length=120), nullable=False),
        sa.Column("embedding", Vector(384), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_chunks_local_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_chunks_local")),
        sa.UniqueConstraint(
            "document_id",
            "chunk_index",
            name="uq_local_document_chunks_document_chunk",
        ),
    )
    op.create_index(
        op.f("ix_document_chunks_local_document_id"),
        "document_chunks_local",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        "ix_document_chunks_local_embedding_hnsw",
        "document_chunks_local",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_chunks_local_embedding_hnsw",
        table_name="document_chunks_local",
        postgresql_using="hnsw",
    )
    op.drop_index(
        op.f("ix_document_chunks_local_document_id"),
        table_name="document_chunks_local",
    )
    op.drop_table("document_chunks_local")
