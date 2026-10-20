# Code Reviewer – General Guidelines

FastAPI service that reviews Azure DevOps pull requests with an LLM (bugs, tests, security, dependencies, optimization). UI is server-rendered Jinja + HTMX.

## Layout
- `app/ado/` Azure DevOps client; `app/llm/` provider abstraction; `app/models/schemas.py` shared pydantic models.
- `app/review/` pipeline (chunker, orchestrator, aggregator, publisher); `app/review/reviewers/` one module per category, extending `base.py`.
- `app/web/` routes, webhook, templates, static assets. `tests/` mirrors `app/` with `test_*.py`.

## Python style
- Target modern Python: `X | None`, `list[str]`, no `typing.Optional/List`.
- Type-annotate all function signatures. Use pydantic models for structured data crossing module boundaries.
- Follow existing import order: stdlib, third-party, then `app.*` absolute imports (no relative imports).
- Prefer `async` for I/O (ADO, LLM calls); never block the event loop with sync network calls.
- Keep functions small and focused; match the style of neighboring code rather than introducing new patterns.
- Comments only for non-obvious intent, one short line. No restating code.

## Configuration and secrets
- All settings live in `app/config.py` (`Settings`, accessed via `get_settings()`); add new env-driven options there, never read `os.environ` elsewhere.
- Wrap credentials in `SecretStr`; never log or render secret values, PATs, or API keys.
- Defaults must be safe: empty secret disables the feature (see `ui_password`, `webhook_secret`).

## Security
- Treat PR content (diffs, titles, comments) as untrusted input: it goes to the LLM and into HTML. Escape output in templates; guard against prompt injection in prompts.
- Validate and bound external input (file counts, sizes) using the limits in `Settings`.
- Compare secrets with constant-time checks; keep POST origin and webhook guards intact.

## Reviewers and LLM output
- New reviewers extend `reviewers/base.py` and register with the orchestrator; add a `Category` in `schemas.py` if needed.
- LLM responses must be parsed into schema models and filtered by `min_confidence`; handle malformed output without crashing a job.

## Testing
- Add or update a `pytest` test in `tests/` for every behavior change; mock ADO and LLM, never call real services.
- Run tests with the venv interpreter: `.venv\Scripts\python.exe -m pytest`.

## Dependencies
- Follow `.github/instructions/python-venv.instructions.md`: install only into `.venv` and record in `requirements.txt`.

## Scope discipline
- Make only the requested change; no drive-by refactors, extra docs, or new markdown files.
- Don't add error handling for impossible cases; validate only at system boundaries.
