"""Real PostgreSQL coverage for parser persistence and the additive migration."""

import uuid

from sqlalchemy import select, text

from pensionpal.config import Settings
from pensionpal.db.models import Document, Page, ParseFailure
from pensionpal.db.session import make_engine, make_sessionmaker
from pensionpal.ingest.parse import ParsedDoc, ParsedPage, ParseError
from pensionpal.ingest.store import save_failure, save_parsed


async def test_parse_migration_adds_headings_and_failure_table(database_url):
    engine = make_engine(
        Settings(app_env="ci", database_url=database_url, _env_file=None)
    )
    async with engine.connect() as conn:
        failures = await conn.scalar(
            text("SELECT to_regclass('public.parse_failures') IS NOT NULL")
        )
        headings = await conn.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='pages' AND column_name='headings')"
            )
        )
    await engine.dispose()
    assert failures is True
    assert headings is True


async def test_save_parsed_document_with_heading_path(database_url):
    engine = make_engine(
        Settings(app_env="ci", database_url=database_url, _env_file=None)
    )
    sessions = make_sessionmaker(engine)
    path = f"data/raw/test/{uuid.uuid4().hex}.pdf"
    parsed = ParsedDoc(
        parser="pymupdf",
        kind="pdf",
        title="Transfer guide",
        pages=[
            ParsedPage(1, "# Transfer\nInstructions", []),
            ParsedPage(2, "Submit Form 13", ["Transfer"]),
        ],
    )
    async with sessions() as session, session.begin():
        action, count = await save_parsed(
            session,
            path=path,
            sha256="a" * 64,
            source_url="https://example.test/transfer.pdf",
            licence="official source",
            source_title="Transfer guide",
            parsed=parsed,
        )
        document = await session.scalar(
            select(Document).where(
                Document.source_url == "https://example.test/transfer.pdf"
            )
        )
        pages = list(
            await session.scalars(
                select(Page)
                .where(Page.document_id == document.id)
                .order_by(Page.page_no)
            )
        )
    await engine.dispose()
    assert (action, count) == ("inserted", 2)
    assert [page.headings for page in pages] == [[], ["Transfer"]]


async def test_failure_retry_count_and_success_clears_dead_letter(database_url):
    engine = make_engine(
        Settings(app_env="ci", database_url=database_url, _env_file=None)
    )
    sessions = make_sessionmaker(engine)
    path = f"data/raw/test/{uuid.uuid4().hex}.pdf"
    async with sessions() as session, session.begin():
        first = await save_failure(
            session,
            path=path,
            sha256="b" * 64,
            source_url="https://example.test/scan.pdf",
            error=ParseError("no_text_layer", "needs OCR"),
        )
    async with sessions() as session, session.begin():
        second = await save_failure(
            session,
            path=path,
            sha256="b" * 64,
            source_url="https://example.test/scan.pdf",
            error=ParseError("no_text_layer", "still needs OCR"),
        )
        await save_parsed(
            session,
            path=path,
            sha256="b" * 64,
            source_url="https://example.test/scan.pdf",
            licence=None,
            source_title="Scanned guide",
            parsed=ParsedDoc("ocr-eng", "pdf", "OCR guide", [ParsedPage(1, "Text")]),
        )
        remaining = await session.scalar(
            select(ParseFailure.id).where(ParseFailure.path == path)
        )
    await engine.dispose()
    assert (first, second) == (1, 2)
    assert remaining is None
