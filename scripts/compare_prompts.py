"""Score every versioned classifier prompt against eval/prompt_testset.jsonl."""

import asyncio
import hashlib
import json
import time
from pathlib import Path

from pensionpal.config import get_settings
from pensionpal.core.logging_config import request_id_var
from pensionpal.db.llm_calls import make_recorder
from pensionpal.db.session import make_engine, make_sessionmaker
from pensionpal.llm.classify import accuracy, classify, find_leaks
from pensionpal.llm.gateway import build_gateway
from pensionpal.llm.prompts import versions

ROOT = Path(__file__).resolve().parents[1]
TESTSET = ROOT / "eval" / "prompt_testset.jsonl"
CACHE = ROOT / "eval" / "cache"


async def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="ask the model again, even for cached questions",
    )
    args = parser.parse_args()
    rows = [
        json.loads(line)
        for line in TESTSET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(rows) < 20 or any(
        row.get("label") not in {"docs", "personal", "off_topic"}
        or "TODO" in row.get("question", "")
        for row in rows
    ):
        raise ValueError(
            "test set needs at least 20 completed questions with valid labels"
        )
    CACHE.mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    engine = make_engine(settings)
    gateway = build_gateway(settings, recorder=make_recorder(make_sessionmaker(engine)))
    calls = 0
    reports = []
    last_call: float | None = None
    try:
        for name, path in versions(ROOT / "prompts", "classify"):
            prompt = path.read_text(encoding="utf-8").strip()
            leaks = find_leaks(prompt, [row["question"] for row in rows])
            if leaks:
                print(f"LEAK {name}: {leaks[0]}")
            answers = []
            input_tokens = 0
            for index, row in enumerate(rows, 1):
                digest = hashlib.sha256(
                    f"{settings.llm_primary_model}\0{prompt}\0{row['question']}".encode()
                ).hexdigest()
                cache_path = CACHE / f"{digest}.json"
                if cache_path.exists() and not args.refresh:
                    reply = json.loads(cache_path.read_text(encoding="utf-8"))
                else:
                    if last_call is not None:
                        await asyncio.sleep(max(0, 5 - (time.monotonic() - last_call)))
                    token = request_id_var.set(f"eval-{digest[:48]}")
                    try:
                        label, result = await classify(
                            gateway, prompt, name, row["question"]
                        )
                    finally:
                        request_id_var.reset(token)
                    last_call = time.monotonic()
                    reply = {
                        "label": label,
                        "text": result.text,
                        "tokens_in": result.tokens_in,
                        "tokens_out": result.tokens_out,
                        "model": result.model,
                    }
                    cache_path.write_text(json.dumps(reply), encoding="utf-8")
                    calls += 1
                got = reply["label"]
                input_tokens += reply.get("tokens_in", 0)
                answers.append({**row, "got": got})
                if got != row["label"]:
                    print(
                        f"{name} missed line {index}: wanted {row['label']}, got {got} ({reply['text'][:100]!r})"
                    )
            score = accuracy(answers)
            correct = sum(r["got"] == r["label"] for r in answers)
            print(
                f"{name:<14} {correct}/{len(rows)} {score:.0%} input_tokens={input_tokens}"
            )
            reports.append((name, correct, len(rows), input_tokens))
        print(f"model calls made now: {calls} (other answers came from eval/cache)")
    finally:
        await gateway.aclose()
        await engine.dispose()
    notes = ROOT / "NOTES.md"
    content = notes.read_text(encoding="utf-8")
    start, end = "<!-- prompt-comparison:start -->", "<!-- prompt-comparison:end -->"
    table = [start, "| Prompt | Accuracy | Input tokens |", "|---|---:|---:|"]
    table.extend(
        f"| {name} | {correct}/{total} ({correct / total:.0%}) | {tokens} |"
        for name, correct, total, tokens in reports
    )
    table.append(end)
    section = "\n".join(table)
    if start in content and end in content:
        before, rest = content.split(start, 1)
        _, after = rest.split(end, 1)
        content = before + section + after
    else:
        content += "\n\n" + section + "\n"
    notes.write_text(content, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
