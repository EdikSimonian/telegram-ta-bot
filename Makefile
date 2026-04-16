.PHONY: install test run deploy push push-prod push-test deploy-prod deploy-test run-prod run-test

# ENV_FILE defaults to .env (single-bot workflow). For dual-bot setups,
# override via `make push ENV_FILE=.env.prod` — or use the dedicated
# `push-prod`/`push-test` wrappers below.
ENV_FILE ?= .env

install:
	python3 -m venv .venv
	.venv/bin/pip install -r requirements.txt

test:
	.venv/bin/pytest tests/ -v

# ── Local polling ─────────────────────────────────────────────────────────
# Run the bot locally via polling using the selected env file. Does NOT
# touch Vercel. Before starting it removes the webhook so Telegram routes
# updates to polling instead of the deployed bot.
run:
	@test -f $(ENV_FILE) || { echo "ERROR: $(ENV_FILE) not found. Copy the matching .env.*.example first."; exit 1; }
	ENV_FILE=$(ENV_FILE) .venv/bin/python run_local.py

run-prod:
	$(MAKE) run ENV_FILE=.env.prod

run-test:
	$(MAKE) run ENV_FILE=.env.test

# ── Deploy ────────────────────────────────────────────────────────────────
# `vercel --prod` needs to know which project to deploy to. We source
# VERCEL_ORG_ID + VERCEL_PROJECT_ID from the env file so a single repo can
# deploy to multiple Vercel projects without swapping `.vercel/` folders.
deploy:
	@test -f $(ENV_FILE) || { echo "ERROR: $(ENV_FILE) not found."; exit 1; }
	@set -a; . ./$(ENV_FILE); set +a; \
	if [ -z "$$VERCEL_PROJECT_ID" ] || [ -z "$$VERCEL_ORG_ID" ]; then \
		echo "ERROR: VERCEL_ORG_ID and VERCEL_PROJECT_ID must be set in $(ENV_FILE)."; \
		echo "Find them in Vercel dashboard → Project → Settings → General."; \
		exit 1; \
	fi; \
	VERCEL_ORG_ID="$$VERCEL_ORG_ID" VERCEL_PROJECT_ID="$$VERCEL_PROJECT_ID" vercel --prod; \
	rc=$$?; \
	if [ $$rc -eq 0 ] && [ -n "$$PROD_URL" ]; then \
		echo ""; \
		printf "Warming %s/api/health to trigger deploy notice ... " "$$PROD_URL"; \
		code=$$(curl -s -o /dev/null -w "%{http_code}" "$$PROD_URL/api/health" || echo "000"); \
		echo "$$code"; \
	fi; \
	exit $$rc

deploy-prod:
	$(MAKE) deploy ENV_FILE=.env.prod

deploy-test:
	$(MAKE) deploy ENV_FILE=.env.test

# ── Push env vars + register webhook ──────────────────────────────────────
# Two independent steps:
#
#   1. Env vars:  prompts "Update Vercel env vars? [y/N]". If yes, pushes
#      every KEY=VALUE from the selected env file to Vercel production,
#      upserting via `vercel env add --force`. If no, skips.
#
#   2. Webhook:   registers the Telegram webhook at <PROD_URL>/api/webhook.
#      Runs regardless of step 1 so you can refresh the webhook alone.
#
# REQUIRED in the env file:
#   PROD_URL           — target Vercel URL
#   VERCEL_ORG_ID      — from Vercel dashboard
#   VERCEL_PROJECT_ID  — from Vercel dashboard
#
# NEVER deletes Vercel vars. Skips comments, blanks, and the three keys
# above (they are local-only orchestration metadata, not runtime vars).
push:
	@test -f $(ENV_FILE) || { echo "ERROR: $(ENV_FILE) not found. Copy the matching .env.*.example first."; exit 1; }
	@command -v vercel >/dev/null 2>&1 || { echo "ERROR: vercel CLI not installed. Run: npm i -g vercel"; exit 1; }
	@command -v curl >/dev/null 2>&1 || { echo "ERROR: curl not installed."; exit 1; }
	@grep -qE '^[[:space:]]*PROD_URL[[:space:]]*=.*[^[:space:]]' $(ENV_FILE) || { \
		echo "ERROR: PROD_URL is not set (or is empty) in $(ENV_FILE)."; \
		echo "Add: PROD_URL=https://<your-bot>.vercel.app"; \
		exit 1; \
	}
	@grep -qE '^[[:space:]]*VERCEL_PROJECT_ID[[:space:]]*=.*[^[:space:]]' $(ENV_FILE) || { \
		echo "ERROR: VERCEL_PROJECT_ID is not set in $(ENV_FILE)."; \
		exit 1; \
	}
	@grep -qE '^[[:space:]]*VERCEL_ORG_ID[[:space:]]*=.*[^[:space:]]' $(ENV_FILE) || { \
		echo "ERROR: VERCEL_ORG_ID is not set in $(ENV_FILE)."; \
		exit 1; \
	}
	@set -a; . ./$(ENV_FILE); set +a; \
	export VERCEL_ORG_ID VERCEL_PROJECT_ID; \
	printf "Push env vars from %s to Vercel project %s? [y/N] " "$(ENV_FILE)" "$$VERCEL_PROJECT_ID"; read push_ans; \
	case "$$push_ans" in y|Y|yes|YES) push_envs=1 ;; *) push_envs=0 ;; esac; \
	count=0; failed=0; tg_token=""; wh_secret=""; prod_url=""; \
	if [ "$$push_envs" = "1" ]; then \
		echo ""; echo "Pushing $(ENV_FILE) → Vercel production (OVERWRITES existing)..."; \
	else \
		echo ""; echo "Skipping env var update."; \
	fi; \
	while IFS= read -r line || [ -n "$$line" ]; do \
		line=$$(printf '%s' "$$line" | sed 's/^[[:space:]]*//;s/[[:space:]]*$$//'); \
		case "$$line" in ''|\#*) continue ;; esac; \
		key=$${line%%=*}; value=$${line#*=}; \
		case "$$value" in \
			\"*\") value=$${value#\"}; value=$${value%\"} ;; \
			\'*\') value=$${value#\'}; value=$${value%\'} ;; \
		esac; \
		if [ -z "$$value" ]; then continue; fi; \
		case "$$key" in \
			TELEGRAM_BOT_TOKEN) tg_token="$$value" ;; \
			WEBHOOK_SECRET) wh_secret="$$value" ;; \
			PROD_URL) prod_url="$$value" ;; \
			VERCEL_ORG_ID|VERCEL_PROJECT_ID) continue ;; \
		esac; \
		if [ "$$push_envs" = "1" ]; then \
			printf "  %-30s ... " "$$key"; \
			if vercel env add "$$key" production --force --yes --value "$$value" </dev/null >/dev/null 2>&1; then \
				echo "ok"; count=$$((count+1)); \
			else \
				echo "FAILED"; failed=$$((failed+1)); \
			fi; \
		fi; \
	done < $(ENV_FILE); \
	if [ "$$push_envs" = "1" ]; then echo ""; echo "Pushed $$count variable(s). $$failed failed."; fi; \
	echo ""; \
	if [ -z "$$tg_token" ]; then \
		echo "Skipping webhook registration: TELEGRAM_BOT_TOKEN not set in $(ENV_FILE)."; \
	else \
		prod_url=$${prod_url%/}; webhook_url="$$prod_url/api/webhook"; \
		printf "Registering Telegram webhook → %s ... " "$$webhook_url"; \
		allowed='["message","edited_message","my_chat_member"]'; \
		if [ -n "$$wh_secret" ]; then \
			response=$$(curl -s -X POST "https://api.telegram.org/bot$$tg_token/setWebhook" \
				--data-urlencode "url=$$webhook_url" \
				--data-urlencode "secret_token=$$wh_secret" \
				--data-urlencode "allowed_updates=$$allowed"); \
		else \
			response=$$(curl -s -X POST "https://api.telegram.org/bot$$tg_token/setWebhook" \
				--data-urlencode "url=$$webhook_url" \
				--data-urlencode "allowed_updates=$$allowed"); \
		fi; \
		case "$$response" in \
			*'"ok":true'*) echo "ok" ;; \
			*) echo "FAILED"; echo "  Telegram response: $$response" ;; \
		esac; \
	fi; \
	if [ "$$push_envs" = "1" ]; then echo ""; echo "Run 'make deploy ENV_FILE=$(ENV_FILE)' to redeploy."; fi

push-prod:
	$(MAKE) push ENV_FILE=.env.prod

push-test:
	$(MAKE) push ENV_FILE=.env.test
