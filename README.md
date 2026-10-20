# Code Reviewer

A FastAPI service that reviews Azure DevOps pull requests with an LLM. It analyzes a PR's changes for bugs, missing unit tests, security issues, risky dependencies, and optimization opportunities, then lets you post selected findings back to the PR as comments. The UI is server-rendered (Jinja + HTMX).

## Features

- **Review categories:** bugs, unit tests, security, dependencies, optimization.
- **Web UI:** enter an Azure DevOps org, project, repo, and PR ID; watch progress live; pick findings to post as PR comments.
- **Webhook mode:** automatically review PRs when they are created or updated, optionally post comments and set a PR status check.
- **JSON API:** fetch a review's results at `/api/reviews/{job_id}`.
- **Safeguards:** limits on files, file size, and concurrent jobs; confidence filtering; optional UI password and webhook secret.

## Requirements

- Python 3.11+
- An OpenAI-compatible API key
- An Azure DevOps Personal Access Token (PAT) with permission to read code/pull requests and write PR threads

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```env
OPENAI_API_KEY=sk-...
ADO_ORG=my-organization
ADO_PAT=your-azure-devops-pat
```

## Run

```powershell
.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000.

## Usage

### Web UI

1. Open the home page and fill in the organization, project, repository, and pull request ID.
2. Select the analysis modules to run.
3. Start the review and wait for the progress to complete.
4. Review the findings, grouped by file and severity, select the ones you want, and post them to the pull request.

### Webhook (automatic reviews)

1. Set `WEBHOOK_SECRET` and `ADO_ORG` in `.env`.
2. In Azure DevOps, add a service hook for **Pull request created** and **Pull request updated** pointing to `POST https://<your-host>/webhooks/ado`.
3. Send the secret in the `X-Webhook-Secret` header, or as the Basic-auth password.

Draft and inactive PRs are ignored, as are updates that do not include a new commit.

## Configuration

All settings are environment variables (or `.env` entries).

| Variable | Default | Description |
| --- | --- | --- |
| `OPENAI_API_KEY` | _(empty)_ | LLM API key (required) |
| `OPENAI_MODEL` | `gpt-4o` | Model name |
| `OPENAI_BASE_URL` | _(none)_ | Custom OpenAI-compatible endpoint |
| `OPENAI_TEMPERATURE` | `0.1` | Sampling temperature |
| `ADO_ORG` | _(empty)_ | Default Azure DevOps organization |
| `ADO_PAT` | _(empty)_ | Azure DevOps PAT (required) |
| `MAX_FILES` | `40` | Max files reviewed per PR |
| `MAX_FILE_CHARS` | `200000` | Max characters per file |
| `MAX_CHUNK_CHARS` | `12000` | Max characters per LLM chunk |
| `MAX_SEGMENTS` | `150` | Max chunks per review |
| `MAX_ACTIVE_JOBS` | `5` | Max concurrent reviews |
| `LLM_CONCURRENCY` | `4` | Parallel LLM calls |
| `MIN_CONFIDENCE` | `0.4` | Findings below this confidence are dropped |
| `JOB_TTL_SECONDS` | `3600` | How long finished reviews are kept |
| `UI_PASSWORD` | _(empty)_ | Protects the UI when set |
| `WEBHOOK_SECRET` | _(empty)_ | Enables the webhook endpoint when set |
| `ALLOWED_ORIGINS` | _(empty)_ | Extra comma-separated hosts allowed as POST origins |
| `AUTO_REVIEW_CATEGORIES` | `bug,test,security,dependency,optimization` | Categories for webhook reviews |
| `AUTO_POST_COMMENTS` | `true` | Post findings automatically for webhook reviews |
| `STATUS_CHECK_ENABLED` | `false` | Set a PR status check for webhook reviews |
| `BLOCK_ON_SEVERITY` | `high` | Severity at which the status check fails |

## Project layout

- `app/ado/` Azure DevOps client
- `app/llm/` LLM provider abstraction
- `app/review/` review pipeline (chunker, orchestrator, aggregator, publisher) and `reviewers/` per category
- `app/web/` routes, webhook, templates, static assets
- `tests/` pytest suite

## Tests

```powershell
.venv\Scripts\python.exe -m pytest
```
