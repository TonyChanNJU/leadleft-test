---
description: Ensure spec/Agents.md is strictly followed (Cursor compatible)
---

This workflow rule file must stay consistent with `spec/agent_rules.md` (single source of truth).

## Mandatory workflow

1. Before starting any task in this workspace, you MUST read `spec/Agents.md` (in Cursor, use the file read tool).
2. Read `spec/project.md` if making structural changes.
3. Obey all security rules in those files (e.g., prohibiting LiteLLM).
4. AT THE END of your task, YOU MUST append a summary of your development activities into `spec/history.md` to keep track of changes.
