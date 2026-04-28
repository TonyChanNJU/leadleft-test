# Agent Rules (Single Source of Truth)

This file is the canonical source for agent workflow rules in this repository.

- Cursor-facing rules are projected into `.cursorrules`
- Workflow enforcement rules are projected into `.agents/workflows/agent_rules.md`

## Mandatory workflow

1. Before starting any task in this workspace, you MUST read `spec/Agents.md`.
2. Read `spec/project.md` if making structural changes.
3. Obey all security rules in those files (e.g., prohibiting LiteLLM).
4. AT THE END of your task, YOU MUST append a summary of your development activities into `spec/history.md` to keep track of changes.

