PY := .venv/bin/python

.PHONY: install run bot test demo demo-granite check-providers record docker-build docker-test docker-up docker-bot docker-demo docker-down

install:            ## create .venv and install everything
	uv venv --python 3.11 .venv || python3.11 -m venv .venv
	uv pip install --python $(PY) -r requirements-dev.txt || $(PY) -m pip install -r requirements-dev.txt

run:                ## API on http://localhost:8000 (provider set in .env; mock by default)
	$(PY) -m uvicorn app.main:app --reload --port 8000

bot:                ## Telegram bot (needs TELEGRAM_BOT_TOKEN and a running API)
	$(PY) -m bot.telegram_bot

test:               ## full test suite, offline, mock providers
	LLM_PROVIDER=mock SEARCH_PROVIDER=mock $(PY) -m pytest -q

demo:               ## offline terminal walkthrough of the 4 Instagram cases
	$(PY) -m scripts.demo

demo-granite:       ## same demo, but the real open-source Granite model (Ollama) reads the saved pages
	$(PY) -m scripts.demo --llm ollama

check-providers:    ## smoke-test every provider with a key in .env (never prints keys)
	$(PY) -m scripts.check_providers

record:             ## record live checks as offline demo data: make record CLAIMS='"caption 1" "caption 2"'
	$(PY) -m scripts.record_fixtures --out demo_fixtures $(CLAIMS)

docker-build:
	docker compose build

docker-test:        ## run the test suite inside Docker
	docker build --target test -t fact-check-coach:test .

docker-up:          ## API in Docker on http://localhost:8000
	docker compose up --build -d api

docker-bot:         ## API + Telegram bot in Docker
	docker compose --profile bot up --build -d

docker-demo:        ## offline demo inside Docker
	docker compose run --rm --no-deps api python -m scripts.demo

docker-down:
	docker compose --profile bot down
