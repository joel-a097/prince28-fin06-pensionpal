import json

from scripts.ingest_local import read_manifest


def test_read_manifest_uses_latest_status_per_url(tmp_path):
    manifest = tmp_path / "manifest.jsonl"
    records = [
        {
            "url": "https://example.test/a.pdf",
            "path": "data/raw/a.pdf",
            "sha256": "a" * 64,
            "status": "downloaded",
        },
        {
            "url": "https://example.test/a.pdf",
            "path": "data/raw/a.pdf",
            "sha256": "a" * 64,
            "status": "failed",
        },
        {
            "url": "https://example.test/b.pdf",
            "path": "data/raw/b.pdf",
            "sha256": "b" * 64,
            "status": "downloaded",
        },
    ]
    manifest.write_text(
        "\n".join(json.dumps(record) for record in records), encoding="utf-8"
    )

    result = read_manifest(manifest)

    assert [record["url"] for record in result] == ["https://example.test/b.pdf"]
