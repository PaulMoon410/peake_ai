# Dual-Agent Implementation Workflow

This project is now running locally on Python 3.8 with compatibility patches.

## Goal
Run two agents in parallel with minimal merge conflicts:
- Agent A: core behavior changes
- Agent B: tests, hardening, docs, and validation

## Branch Strategy
1. Create branch for Agent A:
   - feature/core-<short-name>
2. Create branch for Agent B:
   - feature/support-<short-name>
3. Merge order:
   - Merge Agent A into integration branch first
   - Merge Agent B second

## Ownership Boundaries
Agent A primary files:
- peakebot.py
- web_app.py
- autonomous_ai.py

Agent B primary files:
- validate_admin_setup.py
- README_RENDER.md
- DEPLOYMENT_COMPLETE.md
- tests or validation scripts

Shared file caution:
- requirements.txt is shared and should be changed by one agent only per feature.

## Baseline Verification Commands
Run server:
- python3 web_app.py

Check health:
- curl -sS http://127.0.0.1:10000/health

Check chat:
- curl -sS -X POST http://127.0.0.1:10000/api/chat -H "Content-Type: application/json" -d '{"prompt":"hello"}'

## Current Local Compatibility Baseline
- Python: 3.8.10
- NumPy pinned for Python 3.8
- ZoneInfo fallback enabled through backports.zoneinfo
- Model pickle loading falls back cleanly if incompatible

## Suggested Prompt For Agent B
"Implement tests and validation updates only. Do not modify core inference logic in peakebot.py unless required for testability. Validate /health, /api/chat, and admin auth behavior. Provide a concise diff summary and exact commands run."
