#!/usr/bin/env python3
from __future__ import annotations

import difflib
import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_RULES = REPO_ROOT / "spec" / "agent_rules.md"
CURSOR_RULES = REPO_ROOT / ".cursorrules"
WORKFLOW_RULES = REPO_ROOT / ".agents" / "workflows" / "agent_rules.md"


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise SystemExit(f"Missing required file: {path}")


def _normalize(text: str) -> str:
    # Normalize EOLs and remove trailing whitespace to avoid noisy diffs.
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return "\n".join(lines).rstrip() + "\n"


def _extract_mandatory_workflow_items(spec_text: str) -> list[str]:
    """
    Extract the numbered items under '## Mandatory workflow' from spec/agent_rules.md.
    """
    normalized = _normalize(spec_text)
    marker = "## Mandatory workflow\n"
    idx = normalized.find(marker)
    if idx == -1:
        raise SystemExit("spec/agent_rules.md must contain a '## Mandatory workflow' section.")

    after = normalized[idx + len(marker) :]
    items: list[str] = []
    for line in after.splitlines():
        if line.startswith("## "):
            break
        m = re.match(r"^\s*\d+\.\s+(.*)$", line)
        if m:
            items.append(m.group(1).strip())

    if not items:
        raise SystemExit("No numbered workflow items found under '## Mandatory workflow' in spec/agent_rules.md.")

    return items


def _expected_workflow_rules(items: list[str]) -> str:
    # The workflow file is allowed to carry Cursor-specific guidance on item 1.
    cursor_item_1 = "Before starting any task in this workspace, you MUST read `spec/Agents.md` (in Cursor, use the file read tool)."
    expected_items = [cursor_item_1, *items[1:]]

    lines = [
        "---",
        "description: Ensure spec/Agents.md is strictly followed (Cursor compatible)",
        "---",
        "",
        "This workflow rule file must stay consistent with `spec/agent_rules.md` (single source of truth).",
        "",
        "## Mandatory workflow",
        "",
    ]
    for i, item in enumerate(expected_items, start=1):
        lines.append(f"{i}. {item}")
    lines.append("")
    return _normalize("\n".join(lines))


def _expected_cursorrules() -> str:
    # Keep this concise and stable: it's what Cursor auto-loads.
    lines = [
        "# You are working on the DocChat project.",
        "",
        "# VERY IMPORTANT",
        "Before making any changes, writing any code, or starting any new task, YOU MUST STRICTLY read and adhere to `spec/Agents.md`.",
        "DO NOT skip reading it. It contains mandatory rules regarding the tech stack, security (DO NOT USE LiteLLM), and workflow required for this project.",
        "",
        "Canonical agent workflow rules live in `spec/agent_rules.md`.",
        "",
        "Specifically:",
        "- We use direct LLM SDKs (OpenAI, Anthropic, Google) to build a custom adapter.",
        "- We use Tailwind CSS for the frontend.",
        "- Do not make major architectural changes without consulting spec/project.md.",
        "- AT THE END of your task, YOU MUST append a summary of your development activities into `spec/history.md`.",
        "",
    ]
    return _normalize("\n".join(lines))


def _diff(label: str, actual: str, expected: str, path: Path) -> str:
    diff = difflib.unified_diff(
        actual.splitlines(keepends=True),
        expected.splitlines(keepends=True),
        fromfile=f"{label} (current) {path}",
        tofile=f"{label} (expected) {path}",
    )
    return "".join(diff)


def main() -> int:
    spec_text = _read_text(SPEC_RULES)
    items = _extract_mandatory_workflow_items(spec_text)

    expected_workflow = _expected_workflow_rules(items)
    expected_cursor = _expected_cursorrules()

    actual_workflow = _normalize(_read_text(WORKFLOW_RULES))
    actual_cursor = _normalize(_read_text(CURSOR_RULES))

    ok = True
    if actual_workflow != expected_workflow:
        ok = False
        sys.stderr.write(
            "\nERROR: .agents/workflows/agent_rules.md is out of sync with spec/agent_rules.md.\n"
        )
        sys.stderr.write(_diff("workflow", actual_workflow, expected_workflow, WORKFLOW_RULES))

    if actual_cursor != expected_cursor:
        ok = False
        sys.stderr.write("\nERROR: .cursorrules is out of sync with expected template.\n")
        sys.stderr.write(_diff("cursor", actual_cursor, expected_cursor, CURSOR_RULES))

    if not ok:
        sys.stderr.write(
            "\nFix: update the files to match the expected content (or update the checker if the template intentionally changed).\n"
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

