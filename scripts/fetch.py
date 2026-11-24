"""Fetch the PensionPal corpus through URL, sitemap, Git, or manual sources."""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urljoin

from pensionpal.ingest.fetch import (
    Manifest,
    Robots,
    fetch_all,
    make_client,
    now_iso,
    read_sources,
    slug,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCES_CSV = ROOT / "data" / "sources.csv"
RAW_DIR = ROOT / "data" / "raw"
MANIFEST_PATH = ROOT / "data" / "manifest.jsonl"


def print_result(number: list[int]):
    def show(record: dict) -> None:
        number[0] += 1
        if record["status"] == "downloaded":
            size = record.get("bytes", 0) / 1024
            print(
                f"[{number[0]:4}] downloaded {size:9.1f} kB  {record['path']}",
                flush=True,
            )
        else:
            detail = record.get("error", record["status"])
            print(
                f"[{number[0]:4}] {record['status']:<10} {record['url']}  {detail}",
                flush=True,
            )

    return show


async def run_urls(args: argparse.Namespace) -> int:
    sources = read_sources(Path(args.csv))
    started = time.monotonic()
    number = [0]
    counts = await fetch_all(
        sources,
        root=ROOT,
        max_concurrency=args.max_concurrency,
        per_host_delay=args.delay,
        max_attempts=args.attempts,
        on_result=print_result(number),
    )
    print(
        f"sources={len(sources)} downloaded={counts['downloaded']} skipped={counts['skipped']} "
        f"blocked={counts['blocked']} failed={counts['failed']} "
        f"seconds={time.monotonic() - started:.1f}"
    )
    return int(counts["failed"] > 0)


async def run_sitemap(args: argparse.Namespace) -> int:
    client = make_client(1)
    robots = Robots(client)
    current = args.url
    try:
        for _ in range(10):
            allowed, _ = await robots.check(current)
            if not allowed:
                print(f"blocked: robots.txt disallows {current}")
                return 1
            response = await client.get(current)
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("Location")
                if not location:
                    raise ValueError("sitemap redirect has no Location header")
                current = urljoin(current, location)
                continue
            response.raise_for_status()
            break
        else:
            raise ValueError("too many sitemap redirects")
        root = ET.fromstring(response.content)
        urls = [
            node.text.strip()
            for node in root.iter()
            if node.tag.endswith("loc") and node.text
        ]
    finally:
        await client.aclose()

    matched = [
        url
        for url in urls
        if all(part in url for part in args.include)
        and not any(part in url for part in args.exclude)
    ][: args.limit]
    before = (
        {source.url for source in read_sources(Path(args.csv))}
        if Path(args.csv).exists()
        else set()
    )
    additions = [url for url in matched if url not in before]
    csv_path = Path(args.csv)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    def append_rows() -> None:
        with csv_path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            if not before and csv_path.stat().st_size == 0:
                writer.writerow(["url", "source", "licence", "title"])
            for url in additions:
                writer.writerow([url, args.source, args.licence, ""])

    await asyncio.to_thread(append_rows)
    print(
        f"sitemap_urls={len(urls)} matched={len(matched)} added_to_sources={len(additions)}"
    )
    return 0


def run_manual(args: argparse.Namespace) -> int:
    folder = Path(args.path).resolve()
    raw_root = RAW_DIR.resolve()
    if raw_root not in folder.parents and folder != raw_root:
        raise ValueError("manual files must be inside data/raw/")
    if not folder.is_dir():
        raise ValueError(f"folder does not exist: {folder}")
    manifest = Manifest(MANIFEST_PATH)
    added = 0
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.name.endswith(".part"):
            continue
        identity = f"{args.from_url}#file={path.name}"
        if manifest.done(identity, ROOT):
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        record = {
            "url": identity,
            "source": args.source,
            "licence": args.licence,
            "title": path.name,
            "path": path.relative_to(ROOT).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": digest,
            "content_type": "manual",
            "http_status": None,
            "status": "downloaded",
            "attempts": 0,
            "fetched_at": now_iso(),
            "via": "manual",
        }
        manifest.add(record)
        added += 1
    print(f"folder={folder.relative_to(ROOT).as_posix()} added={added}")
    return 0


def run_repo(args: argparse.Namespace) -> int:
    owner, separator, repo = args.repo.partition("/")
    if not separator or not owner or not repo or "." in repo:
        raise ValueError("repo must be OWNER/REPO")
    with tempfile.TemporaryDirectory(prefix="pensionpal-repo-") as temp:
        clone = Path(temp) / "repo"
        command = [
            "git",
            "clone",
            "--filter=blob:none",
            "--sparse",
            "--depth",
            "1",
            "--branch",
            args.ref,
            f"https://github.com/{owner}/{repo}.git",
            str(clone),
        ]
        if subprocess.run(
            command, check=False, capture_output=True, text=True, timeout=180
        ).returncode:
            raise RuntimeError(
                "git clone failed; confirm the repository and ref are public"
            )
        subprocess.run(
            ["git", "-C", str(clone), "sparse-checkout", "set", args.path],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        subprocess.run(
            ["git", "-C", str(clone), "checkout", args.ref],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        commit = subprocess.run(
            ["git", "-C", str(clone), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.strip()
        files = [
            path
            for path in (clone / args.path).rglob("*")
            if path.is_file() and path.suffix.lower() in args.ext
        ]
        manifest = Manifest(MANIFEST_PATH)
        added = unchanged = 0
        for path in files:
            relative = path.relative_to(clone).as_posix()
            identity = f"https://github.com/{owner}/{repo}/blob/{commit}/{relative}"
            if manifest.done(identity, ROOT):
                unchanged += 1
                continue
            data = path.read_bytes()
            target = (
                RAW_DIR
                / slug(args.source)
                / f"{slug(path.stem)}-{hashlib.sha256(data).hexdigest()[:8]}{path.suffix}"
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            manifest.add(
                {
                    "url": identity,
                    "source": args.source,
                    "licence": args.licence,
                    "title": path.name,
                    "path": target.relative_to(ROOT).as_posix(),
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "content_type": "git repository file",
                    "http_status": None,
                    "status": "downloaded",
                    "attempts": 1,
                    "fetched_at": now_iso(),
                    "via": f"git:{owner}/{repo}@{commit}",
                }
            )
            added += 1
    print(
        f"repo={owner}/{repo} commit={commit[:10]} added={added} unchanged={unchanged}"
    )
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="door", required=True)

    urls = commands.add_parser("urls", help="fetch sources listed in data/sources.csv")
    urls.add_argument("--csv", default=str(SOURCES_CSV))
    urls.add_argument("--delay", type=float, default=0.5)
    urls.add_argument("--max-concurrency", type=int, default=4)
    urls.add_argument("--attempts", type=int, default=4)
    urls.set_defaults(func=lambda args: asyncio.run(run_urls(args)))

    sitemap = commands.add_parser(
        "sitemap", help="add matching sitemap URLs to the source CSV"
    )
    sitemap.add_argument("url")
    sitemap.add_argument("--include", action="append", default=[])
    sitemap.add_argument("--exclude", action="append", default=[])
    sitemap.add_argument("--limit", type=int, default=300)
    sitemap.add_argument("--source", required=True)
    sitemap.add_argument("--licence", required=True)
    sitemap.add_argument("--csv", default=str(SOURCES_CSV))
    sitemap.set_defaults(func=run_sitemap)

    repo = commands.add_parser("repo", help="sparse-clone a public repository folder")
    repo.add_argument("repo", help="OWNER/REPO")
    repo.add_argument("--path", required=True)
    repo.add_argument("--ext", action="append", required=True)
    repo.add_argument("--source", required=True)
    repo.add_argument("--licence", required=True)
    repo.add_argument("--ref", default="main")
    repo.set_defaults(func=run_repo)

    manual = commands.add_parser("manual", help="register files downloaded manually")
    manual.add_argument("path")
    manual.add_argument("--from-url", required=True)
    manual.add_argument("--source", required=True)
    manual.add_argument("--licence", required=True)
    manual.set_defaults(func=run_manual)
    return root


def main() -> int:
    args = parser().parse_args()
    if args.door == "sitemap" and args.limit < 1:
        raise SystemExit("--limit must be positive")
    try:
        result = args.func(args)
        if asyncio.iscoroutine(result):
            result = asyncio.run(result)
        return int(result or 0)
    except KeyboardInterrupt:
        print(
            "Stopped. Completed files are in the manifest; rerun to resume.",
            file=sys.stderr,
        )
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
