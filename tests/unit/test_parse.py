"""Parser behavior using small in-memory-generated PDF and HTML samples."""

from pathlib import Path

import pymupdf
import pytest

from pensionpal.ingest.parse import (
    ParsedPage,
    ParseError,
    clean_text,
    drop_repeated_lines,
    heading_title,
    headings_in,
    markup_to_markdown,
    parse_file,
    parse_html,
    parse_pdf_pymupdf,
    parse_pdf_pypdf,
    parse_text,
    split_pages,
    with_heading_paths,
)


def make_pdf(path: Path, pages: list[tuple[str, str]]) -> None:
    doc = pymupdf.open()
    for heading, body in pages:
        page = doc.new_page()
        if heading:
            page.insert_text((72, 72), heading, fontsize=20)
        page.insert_text((72, 115), body, fontsize=11)
    doc.save(path)
    doc.close()


def test_clean_text_normalizes_unicode_and_removes_invalid_chars():
    assert clean_text("ﬁrst\x00 soft\u00adhyphen") == "first softhyphen"


def test_clean_text_repairs_line_break_hyphenation():
    assert clean_text("treat-\nment") == "treatment"


def test_drop_repeated_headers_and_footers():
    pages = [
        f"EPFO Circular 2024\nBody {name}\nPage {n}"
        for name, n in zip(("Alpha", "Beta", "Gamma", "Delta"), range(1, 5))
    ]
    cleaned = drop_repeated_lines(pages)
    assert all("EPFO Circular" not in page for page in cleaned)
    assert all("Page " not in page for page in cleaned)
    assert "Body Gamma" in cleaned[2]


def test_heading_title_removes_markdown_anchor():
    assert heading_title("Member transfer { #member-transfer }") == "Member transfer"


def test_headings_in_ignores_markdown_inside_code_fences():
    found, state = headings_in("# Real\n```py\n## comment\n````\n")
    assert found == [(1, "Real")]
    assert state is False


def test_heading_path_carries_across_pages():
    pages = with_heading_paths(
        ["# Scheme\n## Eligibility", "Details", "### Exceptions\nRules"]
    )
    assert pages[0].headings == []
    assert pages[1].headings == ["Scheme", "Eligibility"]
    assert pages[2].headings == ["Scheme", "Eligibility"]
    assert pages[2].page_no == 3


def test_table_count_detects_markdown_table():
    page = ParsedPage(1, "| A | B |\n|---|---|\n| 1 | 2 |")
    assert with_heading_paths([page.text])[0].tables == 1


def test_split_pages_preserves_paragraphs_and_numbers():
    result = split_pages("A" * 10 + "\n\n" + "B" * 10, size=12)
    assert result == ["A" * 10, "B" * 10]


def test_rst_heading_is_converted_to_markdown():
    assert (
        markup_to_markdown("Eligibility\n===========\nText", ".rst")
        == "# Eligibility\nText"
    )


def test_asciidoc_heading_is_converted_to_markdown():
    assert (
        markup_to_markdown("== Transfer\nSome text", ".adoc")
        == "## Transfer\nSome text"
    )


def test_plain_markdown_file_parses_and_infers_title(tmp_path: Path):
    path = tmp_path / "faq.md"
    path.write_text("# UAN Help\n\n" + "Member guidance. " * 8, encoding="utf-8")
    parsed = parse_text(path)
    assert parsed.kind == "text"
    assert parsed.title == "UAN Help"
    assert parsed.pages[0].text.startswith("# UAN Help")


def test_csv_is_kept_as_data_text(tmp_path: Path):
    path = tmp_path / "rates.csv"
    path.write_text("rate,amount\n12,100\n", encoding="utf-8")
    parsed = parse_text(path)
    assert parsed.kind == "data"
    assert "rate,amount" in parsed.pages[0].text


def test_html_extraction_keeps_article_and_table(tmp_path: Path):
    path = tmp_path / "faq.html"
    path.write_text(
        "<html><head><title>Member FAQ</title></head><body><nav>Menu</nav>"
        "<main><h1>Member FAQ</h1><p>"
        + "Useful member information. "
        * 12
        + "</p><table><tr><th>Form</th><th>Purpose</th></tr>"
        "<tr><td>13</td><td>Transfer</td></tr></table></main></body></html>",
        encoding="utf-8",
    )
    parsed = parse_html(path)
    assert parsed.kind == "html"
    assert parsed.title == "Member FAQ"
    assert "Useful member information" in parsed.pages[0].text
    assert "Menu" not in parsed.pages[0].text


def test_pymupdf_extracts_pdf_pages_and_heading_paths(tmp_path: Path):
    path = tmp_path / "rules.pdf"
    make_pdf(
        path,
        [
            ("Eligibility", "Employees may claim benefits under the scheme. " * 4),
            ("", "The member submits the prescribed form to EPFO. " * 4),
        ],
    )
    parsed = parse_pdf_pymupdf(path)
    assert parsed.kind == "pdf"
    assert parsed.pages[0].text.startswith("# Eligibility")
    assert parsed.pages[1].headings == ["Eligibility"]


def test_pypdf_parser_reads_same_pdf_text(tmp_path: Path):
    path = tmp_path / "rules.pdf"
    make_pdf(path, [("", "Provident fund member transfer guidance. " * 5)])
    parsed = parse_pdf_pypdf(path)
    assert parsed.parser == "pypdf"
    assert "member transfer" in parsed.pages[0].text


def test_scanned_pdf_has_machine_readable_no_text_layer_error(tmp_path: Path):
    path = tmp_path / "scan.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(path)
    doc.close()
    with pytest.raises(ParseError, match="no_text_layer") as error:
        parse_pdf_pymupdf(path)
    assert error.value.reason == "no_text_layer"


def test_corrupt_pdf_has_machine_readable_reason(tmp_path: Path):
    path = tmp_path / "corrupt.pdf"
    path.write_bytes(b"not a pdf")
    with pytest.raises(ParseError) as error:
        parse_file(path)
    assert error.value.reason == "corrupt"


def test_encrypted_pdf_is_recordable_failure(tmp_path: Path):
    path = tmp_path / "private.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Encrypted content")
    doc.save(
        path, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="user"
    )
    doc.close()
    with pytest.raises(ParseError) as error:
        parse_file(path)
    assert error.value.reason == "encrypted"


def test_unknown_file_type_is_recordable_failure(tmp_path: Path):
    path = tmp_path / "archive.zip"
    path.write_bytes(b"zip")
    with pytest.raises(ParseError) as error:
        parse_file(path)
    assert error.value.reason == "unsupported_type"
