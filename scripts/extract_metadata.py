"""Extract validated records into the existing documents.metadata JSONB column."""

import argparse
import asyncio
import json

from pensionpal.config import get_settings
from pensionpal.db.llm_calls import make_recorder
from pensionpal.db.session import make_engine, make_sessionmaker
from pensionpal.llm.doc_meta import DocMeta
from pensionpal.llm.extract import run
from pensionpal.llm.gateway import build_gateway
from pensionpal.llm.prompts import latest


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument(
        "--schema", action="store_true", help="print the JSON schema and exit"
    )
    parser.add_argument(
        "--native", action="store_true", help="request native JSON schema output"
    )
    args = parser.parse_args()
    if args.schema:
        print(json.dumps(DocMeta.model_json_schema(), indent=2))
        return 0
    settings = get_settings()
    version, prompt = latest(settings.prompts_dir, "extract")
    engine = make_engine(settings)
    sessions = make_sessionmaker(engine)
    gateway = build_gateway(settings, recorder=make_recorder(sessions))
    try:
        counts = await run(
            sessions,
            gateway,
            DocMeta,
            prompt,
            version,
            limit=args.limit,
            retry_failed=args.retry_failed,
            native=args.native,
        )
        total_cost = counts["micro_inr"] / 1_000_000
        print(
            f"prompt={version} pending={counts['pending']} ok={counts['ok']} "
            f"repaired={counts['repaired']} failed={counts['failed']} "
            f"tokens_in={counts['tokens_in']} tokens_out={counts['tokens_out']} "
            f"cost=Rs {total_cost:.4f}"
        )
        return int(counts["stopped"] > 0)
    finally:
        await gateway.aclose()
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
