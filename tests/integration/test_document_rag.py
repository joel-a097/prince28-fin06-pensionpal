import uuid

from sqlalchemy import select, text

from pensionpal.config import Settings
from pensionpal.db.models import Document, DocumentChunk, LocalDocumentChunk, Page
from pensionpal.db.session import make_engine, make_sessionmaker
from pensionpal.ingest.indexing import index_document
from pensionpal.ingest.local_indexing import index_local_document
from pensionpal.llm.embeddings import EMBEDDING_DIMENSIONS
from pensionpal.llm.local_embeddings import LOCAL_EMBEDDING_DIMENSIONS
from pensionpal.services.retrieval import DocumentRetriever, LocalDocumentRetriever


class FakeEmbedder:
    model = "test-embedding-model"

    def __init__(self):
        self.document_calls = 0

    async def embed_documents(self, texts):
        self.document_calls += 1
        return [[1.0, *([0.0] * (EMBEDDING_DIMENSIONS - 1))] for _ in texts]

    async def embed_query(self, text):
        assert text.strip()
        return [1.0, *([0.0] * (EMBEDDING_DIMENSIONS - 1))]


class FakeLocalEmbedder:
    model = "test-local-embedding-model"

    def __init__(self):
        self.document_calls = 0

    def token_count(self, text):
        return len(text.split())

    async def embed_documents(self, texts):
        self.document_calls += 1
        return [[1.0, *([0.0] * (LOCAL_EMBEDDING_DIMENSIONS - 1))] for _ in texts]

    async def embed_query(self, text):
        assert text.strip()
        return [1.0, *([0.0] * (LOCAL_EMBEDDING_DIMENSIONS - 1))]


async def test_migration_enables_vector_extension(database_url):
    engine = make_engine(
        Settings(app_env="ci", database_url=database_url, _env_file=None)
    )
    async with engine.connect() as connection:
        installed = await connection.scalar(
            text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='vector')")
        )
    await engine.dispose()
    assert installed is True


async def test_indexing_is_idempotent_and_retrieval_cites_source(database_url):
    settings = Settings(
        app_env="ci",
        database_url=database_url,
        chunk_max_chars=100,
        chunk_overlap_chars=10,
        _env_file=None,
    )
    engine = make_engine(settings)
    sessions = make_sessionmaker(engine)
    external_id = uuid.uuid4().hex + ("a" * 32)
    source_url = f"https://example.test/{external_id}.pdf"
    async with sessions() as session, session.begin():
        document = Document(
            external_id=external_id,
            title="PF transfer guide",
            source_url=source_url,
            sha256="b" * 64,
            doc_type="corpus",
            metadata_={},
        )
        session.add(document)
        await session.flush()
        document_id = document.id
        session.add(
            Page(
                document_id=document.id,
                page_no=4,
                text="Members may transfer provident fund balances between accounts.",
                headings=["Transfers"],
            )
        )

    embedder = FakeEmbedder()
    first = await index_document(sessions, embedder, external_id, settings)
    second = await index_document(sessions, embedder, external_id, settings)
    retriever = DocumentRetriever(sessions, embedder, limit=3, max_distance=0.1)
    evidence = await retriever.retrieve("How do I transfer my provident fund?")

    async with sessions() as session:
        chunks = list(
            await session.scalars(
                select(DocumentChunk).where(DocumentChunk.document_id == document_id)
            )
        )
    await engine.dispose()

    assert first == (1, True)
    assert second == (1, False)
    assert embedder.document_calls == 1
    assert len(chunks) == 1
    assert len(evidence) == 1
    assert evidence[0].page_no == 4
    assert evidence[0].citation()["source_url"] == source_url


async def test_local_index_is_additive_idempotent_and_retrievable(database_url):
    settings = Settings(
        app_env="ci",
        database_url=database_url,
        chunk_max_chars=100,
        chunk_overlap_chars=10,
        _env_file=None,
    )
    engine = make_engine(settings)
    sessions = make_sessionmaker(engine)
    external_id = uuid.uuid4().hex + ("c" * 32)
    source_url = f"https://example.test/{external_id}.pdf"
    async with sessions() as session, session.begin():
        document = Document(
            external_id=external_id,
            title="PF transfer guide",
            source_url=source_url,
            sha256="d" * 64,
            doc_type="corpus",
            metadata_={},
        )
        session.add(document)
        await session.flush()
        document_id = document.id
        session.add(
            Page(
                document_id=document.id,
                page_no=1,
                text="Members may transfer provident fund balances between accounts.",
                headings=["Transfers"],
            )
        )

    gemini_embedder = FakeEmbedder()
    await index_document(sessions, gemini_embedder, external_id, settings)
    local_embedder = FakeLocalEmbedder()
    first = await index_local_document(sessions, local_embedder, external_id, settings)
    second = await index_local_document(sessions, local_embedder, external_id, settings)
    retriever = LocalDocumentRetriever(
        sessions, local_embedder, limit=3, max_distance=0.1
    )
    evidence = await retriever.retrieve("How do I transfer my provident fund?")

    async with sessions() as session:
        gemini_chunks = list(
            await session.scalars(
                select(DocumentChunk).where(DocumentChunk.document_id == document_id)
            )
        )
        local_chunks = list(
            await session.scalars(
                select(LocalDocumentChunk).where(
                    LocalDocumentChunk.document_id == document_id
                )
            )
        )
    await engine.dispose()

    assert first == (1, True)
    assert second == (1, False)
    assert local_embedder.document_calls == 1
    assert len(gemini_chunks) == 1
    assert gemini_chunks[0].embedding_model == gemini_embedder.model
    assert len(gemini_chunks[0].embedding) == EMBEDDING_DIMENSIONS
    assert len(local_chunks) == 1
    assert len(local_chunks[0].embedding) == LOCAL_EMBEDDING_DIMENSIONS
    assert len(evidence) == 1
    assert evidence[0].page_no == 1
    assert evidence[0].citation()["source_url"] == source_url
