from pensionpal.ingest.chunk import chunk_pages
from pensionpal.ingest.parse import ParsedPage


def test_chunk_pages_preserves_page_and_heading_citations():
    pages = [
        ParsedPage(1, "transfer " * 30, ["EPF", "Transfer"]),
        ParsedPage(2, "claim " * 30, ["Claims"]),
    ]

    chunks = chunk_pages(pages, max_chars=50, overlap_chars=8)

    assert len(chunks) > 2
    assert {chunk.page_no for chunk in chunks} == {1, 2}
    assert all(len(chunk.text) <= 50 for chunk in chunks)
    assert all(chunk.headings == pages[chunk.page_no - 1].headings for chunk in chunks)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert chunks == chunk_pages(pages, max_chars=50, overlap_chars=8)
