from types import SimpleNamespace

from pensionpal.config import Settings
from pensionpal.ingest.local_indexing import _prepare_chunks


class WordCountEmbedder:
    model = "local-test"

    def token_count(self, text):
        return len(text.split())


class CharacterCountEmbedder(WordCountEmbedder):
    def token_count(self, text):
        return len(text)


def test_local_chunking_respects_model_token_limit():
    settings = Settings(
        app_env="ci",
        chunk_max_chars=2000,
        chunk_overlap_chars=0,
        local_embedding_token_limit=10,
        _env_file=None,
    )
    page = SimpleNamespace(
        page_no=1,
        text=" ".join(["paragraph"] * 60),
        headings=["Transfers"],
    )
    embedder = WordCountEmbedder()

    chunks, embedding_texts, signature = _prepare_chunks(
        "PF transfer guide", [page], settings, embedder
    )

    assert len(chunks) > 1
    assert all(embedder.token_count(text) <= 10 for text in embedding_texts)
    assert " ".join(chunk.text for chunk in chunks) == page.text
    assert len(signature) == 64


def test_long_metadata_is_bounded_without_truncating_page_text():
    settings = Settings(
        app_env="ci",
        chunk_max_chars=2000,
        chunk_overlap_chars=0,
        local_embedding_token_limit=40,
        _env_file=None,
    )
    text = " ".join(["paragraph"] * 60)
    headings = [" ".join(["very-long-heading"] * 20)]
    page = SimpleNamespace(page_no=1, text=text, headings=headings)

    chunks, embedding_texts, _ = _prepare_chunks(
        " ".join(["very-long-title"] * 20),
        [page],
        settings,
        CharacterCountEmbedder(),
    )

    assert all(len(embedding_text) <= 40 for embedding_text in embedding_texts)
    assert " ".join(chunk.text for chunk in chunks) == text
    assert all(chunk.headings == headings for chunk in chunks)
