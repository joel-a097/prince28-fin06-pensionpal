"""Ask PensionPal over its streaming or JSON chat endpoint."""

import argparse
import asyncio
import json
import time

import httpx


async def ask(message: str, url: str, as_json: bool) -> int:
    endpoint = url.rstrip("/") + "/v1/chat"
    started = time.perf_counter()
    first_word: float | None = None
    summary: dict = {}
    async with httpx.AsyncClient(timeout=None) as client:
        if as_json:
            response = await client.post(
                endpoint, json={"message": message, "stream": False}
            )
            if response.is_error:
                print(response.text)
                return 1
            payload = response.json()
            print(payload.pop("answer"))
            summary = payload
            first_word = time.perf_counter() - started
        else:
            async with client.stream(
                "POST", endpoint, json={"message": message, "stream": True}
            ) as response:
                if response.is_error:
                    print((await response.aread()).decode(errors="replace"))
                    return 1
                print(end="", flush=True)
                event = ""
                async for line in response.aiter_lines():
                    if line.startswith("event:"):
                        event = line[6:].strip()
                    elif line.startswith("data:"):
                        payload = json.loads(line[5:].strip())
                        if event == "error":
                            print(f"\n{payload.get('detail', 'stream failed')}")
                            return 1
                        if event == "done":
                            summary = payload
                        elif "delta" in payload:
                            if first_word is None:
                                first_word = time.perf_counter() - started
                            print(payload["delta"], end="", flush=True)
                    elif not line:
                        event = ""
            print()
    total = time.perf_counter() - started
    print(
        f"--- {summary.get('provider', 'unknown')} / {summary.get('model', 'unknown')}: "
        f"first words after {first_word or total:.2f} s, total {total:.2f} s"
    )
    print(
        f"    tokens in={summary.get('tokens_in', 0)} out={summary.get('tokens_out', 0)} "
        f"cost Rs {summary.get('cost_inr', 0):.6f} attempts={summary.get('attempts', 0)} "
        f"fallback={'yes' if summary.get('fallback_used') else 'no'}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("message")
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument(
        "--json", action="store_true", help="request a non-streaming answer"
    )
    args = parser.parse_args()
    return asyncio.run(ask(args.message, args.url, args.json))


if __name__ == "__main__":
    raise SystemExit(main())
