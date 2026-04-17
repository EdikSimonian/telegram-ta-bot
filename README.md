# JillWatson — TA Bot for the AI Bot Workshop

A Telegram teaching assistant for the **Summer 2026 AI Bot Workshop in Armenia** (led by Edik Simonian). Runs on Vercel Functions, answers student questions in group chats and DMs, and stays out of the way when it doesn't belong.

**Stack:** Python · Flask · pyTelegramBotAPI · OpenAI SDK · Upstash Redis / Vector · Vercel Blob · Upstash QStash · Vercel

> **Try it:** <a href="https://t.me/JillWatson_Bot" target="_blank"><img src="https://img.shields.io/badge/Chat%20on-Telegram-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white" alt="Chat on Telegram"/></a>

---

## What it does

- **Group-aware Q&A.** In workshop group chats, the bot reads every message but only replies when a student asks a genuine course question. Everything else (greetings, chatter between students, off-topic) returns `IGNORE` and the bot stays silent.
- **RAG over course material.** Course docs are uploaded via `/doc add` (stored on Vercel Blob) and GitHub repos synced via `/git add owner/repo`. Chunks are embedded with OpenAI embeddings and served from Upstash Vector. Citations appear as a `Sources:` footer.
- **Anonymous 1:1 DMs.** Students can message the bot directly for follow-ups. Instructor can review transcripts via `/dm view @student`.
- **Quizzes.** `/quiz [topic]` posts an MC question; auto-reveals after a timeout via Upstash QStash delayed queue.
- **Engagement tracking.** `/stats`, `/grade`, `/grade @student` summarise message counts and quiz scores per group.
- **Announcements & feedback.** `/announce` (with preview + confirm), anonymous `/feedback <text>`.
- **Multi-provider.** `/model <name>` switches AI provider per active group.
- **Multilingual.** Replies match the student's language (Armenian, Russian, English).

---

## Services used

| Service | Purpose |
|---|---|
| [Telegram](https://telegram.org) | Bot platform |
| [Vercel](https://vercel.com) | Serverless host + Blob storage for docs |
| [Upstash Redis](https://upstash.com) | Conversation history, rate limits, per-group state |
| [Upstash Vector](https://upstash.com) | RAG index (course docs + GitHub repos) |
| [Upstash QStash](https://upstash.com) | Delayed callbacks (quiz auto-reveal) |
| [Cerebras](https://cloud.cerebras.ai) | Default LLM provider (OpenAI-compatible) |
| [OpenAI](https://platform.openai.com) | Embeddings for RAG |
| [Tavily](https://tavily.com) *(optional)* | Web search fallback when RAG has no hits |

---

## Environment variables

Copy `.env.example` → `.env.test` / `.env.prod` and fill in values. Full reference lives in [`CLAUDE.md`](./CLAUDE.md).

Required:
- `TELEGRAM_BOT_TOKEN` — from @BotFather
- `AI_API_KEY` + `AI_BASE_URL` + `AI_MODEL` — any OpenAI-compatible endpoint
- `UPSTASH_REDIS_REST_URL` / `UPSTASH_REDIS_REST_TOKEN`
- `UPSTASH_VECTOR_REST_URL` / `UPSTASH_VECTOR_REST_TOKEN`
- `OPENAI_API_KEY` — for embeddings
- `BLOB_READ_WRITE_TOKEN` — Vercel Blob store
- `QSTASH_TOKEN` / `QSTASH_CURRENT_SIGNING_KEY` / `QSTASH_NEXT_SIGNING_KEY`
- `WEBHOOK_SECRET` — random string, must match Telegram `setWebhook` call
- `PERMANENT_ADMIN` — Telegram username of the instructor (no `@`)
- `PROD_URL` — deployment URL, local-only

Optional:
- `TAVILY_API_KEY` — web search fallback
- `INSTRUCTOR_NAME` — shown in welcome messages and system prompt
- `QUIZ_TIMEOUT_MINUTES` (default 5)
- `TA_RATE_LIMIT` / `TA_RATE_LIMIT_WINDOW` — per-student throttle

---

## Local development

```bash
make install               # create .venv + install deps
make run-test              # polling mode against .env.test bot
make run-prod              # polling mode against .env.prod bot
make test                  # pytest suite (offline, mocked)
```

`make run-*` removes any registered webhook so polling takes over. Re-register the webhook afterwards via `make push-test` / `make push-prod` (answer **N** to the env prompt to refresh the webhook alone).

---

## Deployment

**Automatic** (GitHub Actions):

- Push to `test` branch → tests → deploy to test Vercel project → re-register test-bot webhook
- Push to `main` branch → tests → deploy to prod Vercel project → re-register prod-bot webhook

Secrets are scoped per [GitHub Environment](https://docs.github.com/actions/deployment/targeting-different-environments/using-environments-for-deployment) (`test`, `production`) so the test workflow can't read prod secrets. Runtime env vars (AI keys, Redis, Blob, etc.) live on Vercel and are managed via `make push-test` / `make push-prod`, not GitHub Actions.

**Manual** (bypass CI):

```bash
make push-test             # upsert .env.test → Vercel + register webhook
make deploy-test           # deploy test project
make push-prod && make deploy-prod   # same for prod
```

`make push` requires `PROD_URL`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID` set in the env file and refuses to run otherwise — prevents accidentally pointing the wrong bot's webhook at the wrong deployment.

---

## Bot commands (admin)

| Group | Commands |
|---|---|
| Basics | `/help`, `/info` |
| People | `/admin`, `/admin add @user`, `/admin remove @user` |
| Group | `/group`, `/group <N\|chatId>` |
| Model | `/model`, `/model <name>`, `/reset` |
| Knowledge | `/doc`, `/doc add\|update\|delete`, `/git add\|sync\|remove`, `/vstats` |
| DMs | `/dm`, `/dm view @user`, `/dm clear @user` |
| Engagement | `/quiz [topic]`, `/reveal`, `/stats`, `/grade [@user]` |
| Broadcast | `/announce <message>` → preview → reply `send it` / `cancel` |
| Feedback | `/feedback <text>` (anyone), `/feedback list\|clear` (admin) |
| Cleanup | `/purge` |

Students only see `/feedback` — the rest are admin-gated.

---

## Project structure

```
tabot/
├── api/
│   └── index.py              # Vercel entry — Flask app, /api/webhook, /api/health
├── bot/
│   ├── ai.py                 # ask_ai orchestration — RAG injection, SOURCES_USED parsing
│   ├── providers.py          # OpenAI-compatible + HF Gradio dispatch
│   ├── handlers.py           # Top-level message router
│   ├── helpers.py            # send_reply, keep_typing, should_respond
│   ├── history.py            # Redis-backed conversation memory
│   ├── rate_limit.py         # Per-user throttle
│   ├── preferences.py        # Per-user / per-group provider preference
│   ├── search.py             # Tavily web search (fallback when RAG empty)
│   ├── blob.py               # Vercel Blob upload/fetch
│   ├── qstash.py             # Delayed callbacks (quiz auto-reveal)
│   ├── deploy_notice.py      # Post-deploy changelog to groups
│   └── ta/                   # TA-specific logic
│       ├── commands.py       # All /admin, /quiz, /doc, /git, /stats, ... handlers
│       ├── rag.py            # Upstash Vector retrieve + format
│       ├── docs.py           # /doc lifecycle
│       ├── git_ingest.py     # GitHub repo → embeddings
│       ├── quiz.py           # Quiz state machine
│       ├── stats.py          # Engagement tracking
│       ├── admin.py          # Admin list + permission checks
│       ├── announcements.py  # /announce preview flow
│       ├── prepare.py        # Normalise incoming Telegram updates
│       ├── guardrail.py      # Strip <think>, IGNORE, hedging
│       └── welcome.py        # New-member greetings
├── tests/                    # Offline pytest suite (mocked Telegram / OpenAI / Redis)
├── .github/workflows/
│   ├── ci.yml                # Tests on PR
│   └── deploy.yml            # Auto-deploy on push to test / main
├── .env.test / .env.prod     # Per-bot env files (git-ignored)
├── run_local.py              # Polling mode entry point
├── Makefile                  # install / test / run / push / deploy wrappers
├── vercel.json
└── CLAUDE.md                 # Full project guide for AI agents
```

---

## Tests

```bash
make test
```

Offline-only. `tests/conftest.py` mocks `telebot`, `openai`, `upstash_redis`, and `flask` at the `sys.modules` level. Same suite runs on every PR via `.github/workflows/ci.yml` and on every deploy via `.github/workflows/deploy.yml`.

---

## Debugging the webhook path

If you need to hit `/api/webhook` or `/api/health` locally (rather than polling):

```bash
.venv/bin/flask --app api/index run --port 3000
ngrok http 3000
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<ngrok-url>/api/webhook&secret_token=<WEBHOOK_SECRET>"
```

Re-point the webhook at production afterwards with `make push-prod` (answer **N** to the env prompt).
