# Repository Guidelines

## Project Structure & Module Organization

- `app/` contains the application: `api/` exposes FastAPI routes and schemas; `agent/` defines LangGraph state and nodes; `intent/`, `time/`, and `planner/` implement structured intent, UTC+8 time resolution, and deterministic query planning; `compiler/` and `security/` compile and validate read-only SQL; `repositories/` and `clients/` integrate MySQL, Qdrant, Elasticsearch, and embeddings.
- `conf/` stores runtime and semantic configuration. `conf/meta_config.yaml` is the semantic-model source of truth.
- `docker/` contains local service definitions and database initialization scripts. `prompts/` contains LLM prompt templates.
- `tests/` contains unit and phase-specific regression tests. `DEVELOPMENT_STATUS.md` records the current implementation checkpoint.

## Build, Test, and Development Commands

Run from the repository root:

```bash
uv sync
uv run python -m unittest discover -s tests -v
uv run python -m compileall -q app tests
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Use `docker compose -f docker/docker-compose.yaml up -d` only when local dependencies are required. Build metadata with `uv run python -m app.scripts.build_meta_knowledge --conf conf/meta_config.yaml`; this can write metadata and search indexes, so confirm the target resources first.

## Coding Style & Naming Conventions

Use Python 3.12+, four-space indentation, type hints, and clear descriptive names (`snake_case` for functions and variables, `PascalCase` for classes). Keep semantic IDs and SQL object names configuration-driven; do not hard-code user-selected tables or columns. Keep SQL values parameterized and preserve the existing synchronous/asynchronous boundaries. No formatter or linter is currently configured; run `git diff --check` before handoff.

## Testing Guidelines

Tests use the standard library `unittest` runner and are named `test_*.py`. Add focused tests beside the affected phase, then run the full discovery command. Cover semantic validation, planner ambiguity, SQLGlot security checks, parameter binding, limits, timeout behavior, and stable API terminal states where applicable.

## Commit & Pull Request Guidelines

The repository history is minimal; use concise imperative commit subjects, for example `Add deterministic SQL validation`. Pull requests should describe behavior changes, list tests run, identify configuration or schema changes, and call out any external resources affected. Do not commit credentials, generated secrets, or destructive data operations.

## Security & Configuration

Treat `conf/app_config.yaml` and service credentials as sensitive. Use example configuration for sharing, rotate real credentials before committing, and never clear MySQL, Qdrant, Elasticsearch, or Docker volumes without explicit approval. Preserve the read-only SQL allowlist and UTC+8 business-time rules.
