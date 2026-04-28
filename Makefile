.PHONY: run run-backend run-backend-local-embed run-frontend install test

VENV := backend/.venv
PY := $(VENV)/bin/python
PIP := $(PY) -m pip

BACKEND_PORT ?= 8000

install:
	@test -d "$(VENV)" || python3 -m venv "$(VENV)"
	@$(PIP) install -U pip
	@$(PIP) install -r backend/requirements.txt
	cd frontend && npm install

run-backend:
	cd backend && BACKEND_PORT=$(BACKEND_PORT) ../$(VENV)/bin/uvicorn app.main:app --reload --port $(BACKEND_PORT)

run-backend-local-embed:
	mkdir -p data/cache/llama_index data/cache/huggingface
	cd backend && \
	EMBEDDING_PROVIDER=local \
	LLAMA_INDEX_CACHE_DIR=../data/cache/llama_index \
	HF_HOME=../data/cache/huggingface \
	TRANSFORMERS_CACHE=../data/cache/huggingface/transformers \
	SENTENCE_TRANSFORMERS_HOME=../data/cache/huggingface/sentence_transformers \
	BACKEND_PORT=$(BACKEND_PORT) ../$(VENV)/bin/uvicorn app.main:app --reload --port $(BACKEND_PORT)

run-frontend:
	cd frontend && BACKEND_PORT=$(BACKEND_PORT) NEXT_PUBLIC_BACKEND_PORT=$(BACKEND_PORT) npm run dev

run: install
	@echo "Starting backend and frontend..."
	@make run-backend &
	@make run-frontend

test:
	cd backend && PYTHONPATH=. ../$(VENV)/bin/pytest tests/ -v
