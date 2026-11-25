"""Send one inexpensive raw chat-completions request to each configured provider."""

import asyncio
import time

from pensionpal.config import get_settings
from pensionpal.llm.gateway import LLMError, OpenAICompatProvider


async def main() -> int:
    settings = get_settings()
    providers = [
        (
            "gemini",
            settings.llm_primary_base_url,
            settings.gemini_api_key,
            settings.llm_primary_model,
        ),
        (
            "groq",
            settings.llm_fallback_base_url,
            settings.groq_api_key,
            settings.llm_fallback_model,
        ),
    ]
    failures = 0
    for name, base_url, key, model in providers:
        if not key:
            print(f"{name:<7} NO KEY   add {name.upper()}_API_KEY to .env")
            failures += 1
            continue
        provider = OpenAICompatProvider(
            name, base_url, key, model, timeout=settings.llm_timeout_seconds
        )
        started = time.perf_counter()
        try:
            reply = await provider.generate(
                [{"role": "user", "content": "Reply with exactly one word: pong"}],
                temperature=0,
            )
            print(
                f"{name:<7} OK       {model} said {reply.text[:80]!r}; "
                f"{(time.perf_counter() - started) * 1000:.0f} ms; "
                f"tokens in={reply.tokens_in} out={reply.tokens_out}"
            )
        except LLMError as exc:
            failures += 1
            print(f"{name:<7} FAILED   {exc}")
        finally:
            await provider.aclose()
    return int(failures > 0)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
