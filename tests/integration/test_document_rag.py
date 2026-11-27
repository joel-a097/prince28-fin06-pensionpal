import uuid

from sqlalchemy import select, text

from pensionpal.config import Settings
from pensionpal.db.models import Document, DocumentChunk, Page
from pensionpal.db.session import make_engine, make_sessionmaker
from pensionpal.ingest.indexing import index_document
from pensionpal.llm.embeddings import EMBEDDING_DIMENSIONS
from pensionpal.services.retrieval import DocumentRetriever


class FakeEmbedder:
    model = "test-embedding-model"

    def __init__(self):
        self.document_calls = 0

    async def embed_documents(self, texts):
        self.document_calls += 1
        return [[1.0, *([0.0] * (EMBEDDING_DIMENSIONS - 1))] for _ in texts]

    async def embed_query(self, text):
        return [1.0, *([0.0] * (EMBEDDING_DIMENSIONS - 1))]


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
        chunks = list(await session.scalars(select(DocumentChunk)))
    await engine.dispose()

    assert first == (1, True)
    assert second == (1, False)
    assert embedder.document_calls == 1
    assert len(chunks) == 1
    assert len(evidence) == 1
    assert evidence[0].page_no == 4
    assert evidence[0].citation()["source_url"] == source_url
