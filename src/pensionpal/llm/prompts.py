"""Load versioned LLM prompts from the repository prompt directory."""

import re
from pathlib import Path


def versions(directory: Path, task: str) -> list[tuple[str, Path]]:
    pattern = re.compile(rf"^{re.escape(task)}_v(\d+)\.md$")
    found = []
    for path in directory.glob(f"{task}_v*.md"):
        match = pattern.match(path.name)
        if match:
            found.append((f"{task}_v{match.group(1)}", path))
    return sorted(found, key=lambda item: int(item[0].rsplit("v", 1)[1]))


def load(directory: Path, name: str) -> str:
    path = directory / f"{name}.md"
    return path.read_text(encoding="utf-8").strip()


def latest(directory: Path, task: str) -> tuple[str, str]:
    found = versions(directory, task)
    if not found:
        raise FileNotFoundError(f"no {task}_v<number>.md prompt found in {directory}")
    name, path = found[-1]
    return name, path.read_text(encoding="utf-8").strip()
