# CLAUDE.md — Project Guide for AI Agents

This file describes the architecture, conventions, and deployment process for this project so an AI agent can work on it without guessing.

---

## What this project is

A serverless **Teaching Assistant Telegram bot** for the Summer 2026 AI Bot Workshop in Armenia, led by Edik Simonian (`@ediksimonian`). It joins course Telegram groups and answers student questions using RAG over instructor-uploaded course material, runs interactive quizzes with QStash-scheduled auto-reveal, and offers a wide instructor-only admin command suite.

The repository started life as a generic "Telegram + Vercel" template and still wears some of that shape (`run_local.py`, the Makefile structure, the `bot/` layout). Most domain logic now lives under `bot/ta/`.

**Stack:** Python 3.12 · Flask · pyTelegramBotAPI · OpenAI SDK (LLM + embeddings) · Upstash Redis (state) · Upstash Vector (RAG) · Upstash QStash (delayed callbacks) · Vercel Blob (doc storage) · Vercel Functions (runtime).

---

## Project structure

```
tabot/
├── api/                          # Vercel function entrypoints
│   ├── index.py                  # Flask app — /api/webhook, /api/health, /api/notify-admin
│   ├── autoreveal.py             # QStash callback — quiz auto-reveal after timeout
│   ├── github.py                 # GitHub webhook receiver — re-ingest on push
│   └── git_sync_batch.py         # QStash callback — batched repo file ingest
├── bot/
│   ├── __init__.py
│   ├── config.py                 # ALL env vars + system prompt + RAG/quiz knobs
│   ├── clients.py                # Singleton bot/ai/embeddings/redis/vector clients
│   ├── ai.py                     # ask_ai() — RAG retrieve → history → OpenAI → persist
│   ├── search.py                 # Tavily web-search fallback (only when RAG misses)
│   ├── blob.py                   # Vercel Blob adapter with BLOB_PATH_PREFIX isolation
│   ├── qstash.py                 # QStash publish + JWT signature verify (rotation-aware)
│   ├── github.py                 # GitHub REST client (list_tree, fetch_blob, parse_repo_url)
│   ├── handlers.py               # Webhook router → bot.ta.admin.route()
│   ├── helpers.py                # Telegram message splitter, typing-indicator refresh
│   ├── deploy_notice.py          # One-shot DM to admin on first /api/health hit per deploy
│   └── ta/                       # Teaching-assistant domain logic
│       ├── admin.py              # 12-step dispatch precedence (the request-routing brain)
│       ├── commands.py           # /help /info /admin /quiz /doc /git etc. — 20 commands
│       ├── state.py              # All Redis-backed state (admins, groups, history, quizzes…)
│       ├── prepare.py            # Telegram update → Prepared dataclass; admin/instructor checks
│       ├── tg.py                 # Centralized Telegram wrappers w/ error handling
│       ├── rag.py                # chunk → embed → upsert / retrieve top-k from Upstash Vector
│       ├── quiz.py               # /quiz generation, A–D answering, /reveal, QStash scheduling
│       ├── docs.py               # /doc add/list/update/delete — Blob + Vector + Redis index
│       ├── git_ingest.py         # GitHub repo ingest (sync small / async via QStash for large)
│       ├── announcements.py      # /announce — stage, DM preview, "send it" confirm
│       ├── stats.py              # Engagement scoring + inactive-user flagging
│       ├── welcome.py            # Group + DM welcome messages
│       ├── joke.py               # /joke
│       ├── guardrail.py          # Strip <think>, drop hedging, suppress IGNORE
│       └── upgrade.py            # /upgrade — fires Claude Code Routine to PR a change
├── tests/                        # 29 test files; conftest.py mocks external libs at sys.modules
├── .github/workflows/ci.yml      # Pytest on push + PR
├── .env.example                  # Template (TA bot stack — Vector, QStash, Blob, etc.)
├── run_local.py                  # Local polling runner (no Vercel) — auto-loads .env
├── Makefile                      # install / test / run / deploy / push (+ -prod / -test variants)
├── requirements.txt
├── vercel.json                   # Rewrites + per-function maxDuration + Python runtime pin
├── CLAUDE.md                     # This file
└── README.md                     # Student-facing setup guide
```

---

## How the bot works

1. Telegram POSTs every `message` / `edited_message` / `my_chat_member` update to `https://<vercel-url>/api/webhook`.
2. `vercel.json` rewrites `/api/webhook` → `api/index.py` (Vercel only auto-detects Flask apps in specific filenames; `index.py` is one of them).
3. `api/index.py` validates `X-Telegram-Bot-Api-Secret-Token` against `WEBHOOK_SECRET` (fail-closed unless local), deserialises the update, and hands it to pyTelegramBotAPI.
4. The single text handler in `bot/handlers.py` calls `bot.ta.admin.route(message)`. The 12-step precedence in `bot/ta/admin.py` is the routing brain — see next section.
5. For a question that survives the gates, `bot/ai.py::ask_ai()` runs:
   - `bot.ta.rag.retrieve()` — embed the query, ANN-search Upstash Vector top-K, filter by `RAG_MIN_SCORE`
   - `bot.ta.state.get_history()` — load group-level conversation history from Redis
   - Compose: system prompt + numbered RAG context + history + prefixed user message
   - Call OpenAI with the group's active model (`get_active_model()`) or `DEFAULT_MODEL`
   - Optional Tavily fallback if RAG returned nothing AND `needs_search()` matched a date/recency keyword AND `TAVILY_API_KEY` is set
   - `bot.ta.guardrail` strips `<think>` blocks and suppresses `IGNORE` / hedging
   - Persist user + assistant turns via `append_history()`

**Critical:** `telebot.TeleBot` is created with `threaded=False`. Without this, handlers run in threads that get killed when the serverless function returns — the message is received but never replied. `threaded=False` is also fine for local polling.

---

## The admin router (`bot/ta/admin.py`)

`route()` walks a 12-step precedence list. Earlier steps are cheaper and short-circuit on hit, so RAG/LLM cost is only paid when nothing else handles the message:

1. `/start` — DM welcome.
2. New DM user — first-time DM welcome.
3. Pending announcement confirmation (`/announce` two-step flow).
4. Admin command — instructor-gated registry in `bot/ta/commands.py`.
5. Active quiz answer (A–D in a group with a live quiz).
6. `@<bot>` mention or reply-to-bot — forced direct response.
7. Rate-limit gate — `TA_RATE_LIMIT` per `TA_RATE_LIMIT_WINDOW` (rolling, per student).
8. Question pre-gate — regex for question marks (`?`, Armenian `՞`, Arabic `؟`) + interrogative starters; non-questions fall through silently.
9. RAG retrieve.
10. LLM call.
11. Guardrail post-process.
12. Persist + reply.

The system prompt (in `bot/config.py::SYSTEM_PROMPT`) instructs the model to respond `IGNORE` for chatter / off-topic / cross-student messages. The guardrail enforces that; only `@`-mentions / replies / DMs bypass the IGNORE filter.

---

## Multi-bot isolation

A single Upstash Redis DB / Vector index / Blob store can host **multiple deployments** (typically prod + test) without collisions. Three independent prefixes:

| Env var | Default | Effect |
|---|---|---|
| `REDIS_PREFIX` | `ta:` | Prepended to every Redis key |
| `VECTOR_NAMESPACE` | `""` (default ns) | Upstash Vector namespace |
| `BLOB_PATH_PREFIX` | `docs/` | Prepended to every Blob path |
| `BOT_ENV` | `local` | Free-form label surfaced in `/info` and logs |

Use `ta:prod:` / `ta:test:` (and matching namespace / blob prefix / `BOT_ENV=prod`) to safely run two bots against one set of upstream services.

---

## Environment variables

Read in `bot/config.py`. Every value is `.strip()`-ed to defend against trailing newlines from CLI piping.

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Yes | — | From @BotFather |
| `AI_API_KEY` | Yes | — | OpenAI API key |
| `AI_BASE_URL` | No | `https://api.openai.com/v1` | OpenAI-compatible endpoint |
| `AI_MODEL` | No | `gpt-5.4-nano` | Default LLM (must be in `VALID_MODELS`: `gpt-5.4-nano`, `gpt-5.4-mini`, `gpt-5.5`) |
| `QUIZ_MODEL` | No | `AI_MODEL` | Optional override for quiz generation |
| `EMBEDDINGS_PROVIDER` | No | `openai` | Embeddings backend |
| `EMBEDDINGS_MODEL` | No | `text-embedding-3-small` | Embedding model |
| `UPSTASH_REDIS_REST_URL` | Stateful | — | Required for memory, quizzes, admin, rate limit, docs index |
| `UPSTASH_REDIS_REST_TOKEN` | Stateful | — | — |
| `UPSTASH_VECTOR_REST_URL` | RAG | — | Required for `/doc`, `/git`, RAG retrieval |
| `UPSTASH_VECTOR_REST_TOKEN` | RAG | — | — |
| `VECTOR_NAMESPACE` | No | `""` | Upstash Vector namespace |
| `QSTASH_URL` | Quiz reveal | `https://qstash.upstash.io` | Use the regional URL for lower latency |
| `QSTASH_TOKEN` | Quiz reveal | — | — |
| `QSTASH_CURRENT_SIGNING_KEY` | Quiz reveal | — | JWT verify (rotation-aware) |
| `QSTASH_NEXT_SIGNING_KEY` | Quiz reveal | — | JWT verify after rotation |
| `BLOB_READ_WRITE_TOKEN` | Docs | — | Required for `/doc add` |
| `BLOB_PATH_PREFIX` | No | `docs/` | Multi-bot isolation |
| `REDIS_PREFIX` | No | `ta:` | Multi-bot isolation |
| `BOT_ENV` | No | `local` | Label for `/info` (`prod` / `test` / etc.) |
| `DMS_ENABLED` | No | `true` | When `false`, non-admin DMs are declined (pointed back to the group) and the bot never nudges students to DM it; admins can always DM |
| `GROUP_ENGAGEMENT` | No | `true` | When `false`, the bot only replies in groups when directly addressed (`@`-mention or reply-to-bot); unaddressed questions are left alone. Admin commands + quiz answering unaffected |
| `PERMANENT_ADMIN` | No | `ediksimonian` | Username (lowercase) — fallback only |
| `PERMANENT_ADMIN_ID` | **Strongly recommended** | — | Numeric Telegram user ID — primary admin gate |
| `INSTRUCTOR_NAME` | No | `Edik Simonian` | Used in welcome + system prompt |
| `TA_RATE_LIMIT` | No | `10` | Per-student questions per window |
| `TA_RATE_LIMIT_WINDOW` | No | `3600` (sec) | Rolling-window length |
| `RATE_LIMIT` | No | `250` | Legacy daily cap (polling runner) |
| `QUIZ_TIMEOUT_MINUTES` | No | `3` | Auto-reveal delay |
| `TAVILY_API_KEY` | No | — | Enables web-search fallback |
| `GITHUB_TOKEN` | No | — | PAT for private repos / 60-rph limit |
| `GITHUB_WEBHOOK_SECRET` | No | — | HMAC-SHA256 for `api/github.py` |
| `CLAUDE_ROUTINE_ID` | No | — | Powers `/upgrade` — Claude Code Routine that PRs the change |
| `CLAUDE_ROUTINE_TOKEN` | No | — | — |
| `WEBHOOK_SECRET` | No | — | Telegram secret-token header verification |
| `HF_SPACE_ID` | No | — | Legacy HF Gradio fallback (rarely set) |
| `HF_TOKEN` | No | — | — |
| `PROD_URL` | Local-only | — | Used by `make push` to register webhook + by code to build QStash callback URLs |
| `VERCEL_ORG_ID` | Local-only | — | Required by `make deploy` / `make push` |
| `VERCEL_PROJECT_ID` | Local-only | — | Required by `make deploy` / `make push` |

`PROD_URL` / `VERCEL_ORG_ID` / `VERCEL_PROJECT_ID` are local-only orchestration metadata — `make push` skips them when syncing to Vercel.

---

## Commands (instructor-gated unless noted)

`/help`, `/info` (open to anyone) · `/admin add|remove|list` · `/reset` · `/model [list|set <id>]` · `/group <add|remove|active>` · `/doc <add|list|update|delete>` · `/git <add|list|remove>` · `/quiz [topic]` (open) · `/reveal` (open) · `/joke [theme]` (open) · `/roll` (open) · `/stats` · `/grade` · `/announce <text>` · `/dm <user> <text>` · `/vstats` · `/purge` · `/upgrade <instruction>` · `/feedback`

Registry lives in `bot/ta/commands.py`; each command supports sub-commands routed by prefix match.

---

## RAG pipeline

- **Knobs** (`bot/config.py`): `RAG_CHUNK_SIZE=800`, `RAG_CHUNK_OVERLAP=100`, `RAG_TOP_K=5`, `RAG_MIN_SCORE=0.6`.
- **Ingest** (`bot/ta/rag.py::ingest`): chunk text by char count with overlap → embed via `text-embedding-3-small` → upsert into Upstash Vector under `VECTOR_NAMESPACE`.
- **Retrieve**: embed query → ANN search top-K → drop matches below `RAG_MIN_SCORE` → format as numbered `[N] Title — chunk` blocks the model can cite.
- **Sources**: model emits `SOURCES_USED: 1,3` trailer; `bot/ai.py` parses it and appends a clickable `**Sources:**` footer to the reply.
- **Doc storage** (`bot/ta/docs.py`): the original text lives in Vercel Blob (`docs/<slug>.md`), chunks live in Vector, and the doc index lives in Redis.

---

## Quiz system

- `/quiz [topic]` — `bot/ta/quiz.py` calls `QUIZ_MODEL` to generate a multiple-choice question (A–D), saves the answer + `correct_index` to Redis, posts to the group, schedules a QStash callback to `/api/autoreveal` at `now + QUIZ_TIMEOUT_MINUTES`.
- Students answer with a bare letter (A–D) — caught at admin-router step 5.
- `/api/autoreveal` (QStash callback) verifies the JWT against `QSTASH_CURRENT_SIGNING_KEY` (with `NEXT` fallback for rotation), checks the quiz hasn't already been revealed (idempotent), reveals the answer + per-student tally.
- Inline fallback: if the QStash callback is missed (rare), the next inbound message in the group triggers a stale-quiz check and reveals inline.

---

## GitHub ingest

- `/git add <repo-url>` — `bot/ta/git_ingest.py` lists the tree, decides sync vs async by file count.
  - **Small repos** ingest in one webhook turn.
  - **Large repos** publish a QStash batch to `/api/git-sync-batch`, which processes up to `BATCH_SIZE` files and chains follow-up jobs until the tree is exhausted, then DMs the instructor.
- **Auto re-sync**: register a GitHub webhook pointing at `/api/github` with `GITHUB_WEBHOOK_SECRET` shared. On `push`, `api/github.py` re-ingests only the changed paths.
- Slug format: `gh-{owner}-{repo}-{path-slug}`.
- Binary / large files are silently skipped during text extraction.

---

## Webhook verification

When `WEBHOOK_SECRET` is set, every `/api/webhook` POST is rejected with 403 unless `X-Telegram-Bot-Api-Secret-Token` matches. `make push` registers the webhook with the same secret in `setWebhook`.

```bash
curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  --data-urlencode "url=https://<VERCEL_URL>/api/webhook" \
  --data-urlencode "secret_token=<WEBHOOK_SECRET>" \
  --data-urlencode 'allowed_updates=["message","edited_message","my_chat_member"]'
```

---

## Reliability

- **Stateless mode** — when Redis / Vector / Blob env vars are unset, the corresponding consumer modules degrade to no-ops and return safe defaults (empty history, no rate limit, etc.). The bot stays alive in memory-only mode. Useful for the original Day-1 template experience and for local smoke-tests.
- **Graceful degradation when configured-but-down** — every Redis / Vector / Blob call is wrapped in try/except and logs once on failure. The router never raises into the webhook response.
- **Question pre-gate** — non-question chatter is dropped via regex *before* embedding/LLM cost is incurred. Cheapest possible filter.
- **Typing indicator** — `bot/helpers.py` keeps the Telegram typing action alive (re-sent every ~4s) for the duration of slow LLM / embedding calls.
- **Quiz idempotency** — `reveal_now()` short-circuits if `revealed_at` is already set in Redis, so retried QStash callbacks don't double-post.
- **QStash key rotation** — both `QSTASH_CURRENT_SIGNING_KEY` and `QSTASH_NEXT_SIGNING_KEY` are tried during JWT verify; safe to rotate without downtime.
- **Admin gate** — `PERMANENT_ADMIN_ID` (numeric) takes precedence over `PERMANENT_ADMIN` (username). Telegram usernames are mutable and can be recycled 30 days after release; numeric IDs are stable.

---

## How to add a command

Add a function to `bot/ta/commands.py` and register it in the `COMMANDS` dict (see existing entries — each command has a handler + permission level). The router in `bot/ta/admin.py` dispatches to the registry at step 4.

If the command needs new state, add helpers to `bot/ta/state.py` (always namespaced under `REDIS_PREFIX`).

If the command schedules a delayed callback, publish to QStash via `bot/qstash.py` and add a new file under `api/` for the callback handler — verify the JWT before doing any work. Add the new path to `vercel.json::rewrites` and `functions` if it needs a non-default `maxDuration`.

Update `cmd_help` in `bot/ta/commands.py` so the new command shows in `/help`.

---

## How to add a new feature module

1. Decide if it's TA-domain (`bot/ta/`) or infrastructure (`bot/`). Most new features are TA-domain.
2. Create the module; import `clients.py` for upstream services rather than instantiating new ones.
3. If it touches Redis: namespace every key under `REDIS_PREFIX` and wrap every call in try/except for graceful degradation.
4. Add tests in `tests/` — `conftest.py` already mocks `telebot`, `openai`, `upstash_redis`, `upstash_vector`, `flask`, etc. at `sys.modules` level.

`api/index.py` rarely needs changes — it's a thin webhook adapter.

---

## Running tests

```bash
make install   # creates .venv, installs requirements.txt
make test      # pytest -v
```

Tests use `unittest.mock`. `tests/conftest.py` sets fake env vars and mocks external packages at `sys.modules` level *before* any `bot/` module is imported. Individual tests patch module-level names (e.g. `bot.ta.state.redis`) for fine-grained control.

CI: `.github/workflows/ci.yml` runs pytest on every push + PR.

---

## Local development

`run_local.py` runs the same `bot/` modules via `bot.infinity_polling()` instead of the webhook. It auto-loads `.env` (or the file pointed at by `ENV_FILE`) with a zero-dependency inline loader and calls `bot.remove_webhook()` first so Telegram routes updates to polling.

```bash
make run                       # uses .env
make run-prod                  # uses .env.prod
make run-test                  # uses .env.test
make run ENV_FILE=.env.custom  # any other file
```

After stopping local polling, **re-register the production webhook** (`make push` answering `n` to the env-var prompt is enough — it always re-registers the webhook).

---

## Deployment

Single-env workflow uses `.env`; dual-env workflow uses `.env.prod` + `.env.test` and the `-prod` / `-test` Make targets.

```bash
make deploy                # vercel --prod, picks Vercel project from .env
make deploy-prod           # ENV_FILE=.env.prod
make deploy-test           # ENV_FILE=.env.test
```

`make deploy` requires `VERCEL_ORG_ID` and `VERCEL_PROJECT_ID` in the env file — they pin the deploy to the right Vercel project so a single repo can deploy to multiple projects without swapping `.vercel/`. On success it warms `<PROD_URL>/api/health` to trigger `bot/deploy_notice.py`, which DMs the admin a short-SHA + commit changelog.

### `make push` — env sync + webhook registration

```bash
make push                  # uses .env
make push-prod             # uses .env.prod
make push-test             # uses .env.test
```

Two phases (independent):

1. **Env push** — prompts `Push env vars from <file> to Vercel project <id>? [y/N]`. On `y`, reads every `KEY=VALUE` and upserts each into Vercel production via `vercel env add <KEY> production --force --yes --value "<VALUE>" </dev/null`. The `</dev/null` is critical — without it `vercel env add` consumes stdin from the `while read` loop and only the first variable gets pushed. Skips comments, blanks, empty values, and `PROD_URL` / `VERCEL_ORG_ID` / `VERCEL_PROJECT_ID`. On `n`, skips this phase entirely.
2. **Webhook registration** — runs regardless. Calls Telegram `setWebhook` via `POST` + `--data-urlencode` (safe against special chars), pointing at `<PROD_URL>/api/webhook` with `WEBHOOK_SECRET` and `allowed_updates=["message","edited_message","my_chat_member"]`.

Preflight checks: env file exists, `vercel` and `curl` are installed, and `PROD_URL` / `VERCEL_PROJECT_ID` / `VERCEL_ORG_ID` are non-empty in the env file. Refuses to run otherwise — there is no safe default, and a default would risk pushing to the wrong production bot.

After a `y`-answered push, run `make deploy` (or `deploy-prod` / `deploy-test`) to redeploy with the new env vars.

---

## Known gotchas

- **`threaded=False`** — required on `telebot.TeleBot`. Threads die when the serverless function returns.
- **Vercel entrypoint filenames** — only specific names are auto-detected as Flask apps; `index.py` is one. The `vercel.json` rewrite from `/api/webhook` → `/api/index` exists because Vercel's path-based routing would otherwise look for a function literally named `webhook`.
- **Per-function `maxDuration`** — `api/index.py` and `api/git_sync_batch.py` and `api/github.py` are pinned to 60s; `api/autoreveal.py` to 30s. All on `@vercel/python@4.3.0`.
- **Env var newlines** — always use `--value` with `vercel env add`. Piping (`echo "..." | vercel env add`) appends a trailing newline that breaks URL parsing.
- **OpenAI model IDs** — `VALID_MODELS` is intentionally tight (`gpt-5.4-nano`, `gpt-5.4-mini`, `gpt-5.5`). Add to that list before pointing `AI_MODEL` at a new model — invalid IDs just 404 at request time.
- **Telegram 4096-char limit** — `bot/helpers.py` splits replies at `TG_CHUNK_LEN=4000` automatically.
- **Webhook secret must match** — if `WEBHOOK_SECRET` is set, the same value must go into `setWebhook`'s `secret_token`. Mismatch → 403 on every update → bot goes silent.
- **QStash callbacks must verify JWT** — every `api/<callback>.py` should start by calling `bot.qstash.verify_jwt()`. Skipping verification means anyone with the URL can fire callbacks.
- **GitHub webhook secret** — `api/github.py` rejects unsigned requests. The same `GITHUB_WEBHOOK_SECRET` must be configured on every GitHub repo's webhook.
- **`PERMANENT_ADMIN_ID` over `PERMANENT_ADMIN`** — username gates are unsafe on Telegram (usernames are mutable + recycled after 30 days). Always set the numeric ID.
- **`REDIS_PREFIX` / `VECTOR_NAMESPACE` / `BLOB_PATH_PREFIX`** — these MUST differ between prod and test if both share upstream services. Easy to forget; everything appears to work until one bot reads the other's data.
- **Multi-bot env isolation** — `BOT_ENV` is purely cosmetic (shows in `/info` + logs). The actual isolation is the three prefixes above.
- **`run_local.py` removes the webhook** — after a local-polling session, run `make push` (or any `setWebhook` call) to restore it, otherwise the production bot stays silent.
- **HF provider is legacy** — `bot/providers.py` no longer exists; `HF_SPACE_ID` is preserved as an env-var stub but the code path is effectively dormant. Don't ground new features on it.
