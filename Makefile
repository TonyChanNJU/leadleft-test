.PHONY: run run-backend run-backend-local-embed run-frontend install test

VENV := backend/.venv
PY := $(VENV)/bin/python
PIP := $(PY) -m pip

install:
	@test -d "$(VENV)" || python3 -m venv "$(VENV)"
	@$(PIP) install -U pip
	@$(PIP) install -r backend/requirements.txt
	cd frontend && npm install

run-backend:
	cd backend && ../$(VENV)/bin/uvicorn app.main:app --reload --port 8000

run-backend-local-embed:
	mkdir -p data/cache/llama_index data/cache/huggingface
	cd backend && \
	EMBEDDING_PROVIDER=local \
	LLAMA_INDEX_CACHE_DIR=../data/cache/llama_index \
	HF_HOME=../data/cache/huggingface \
	TRANSFORMERS_CACHE=../data/cache/huggingface/transformers \
	SENTENCE_TRANSFORMERS_HOME=../data/cache/huggingface/sentence_transformers \
	../$(VENV)/bin/uvicorn app.main:app --reload --port 8000

run-frontend:
	cd frontend && npm run dev

run: install
	@echo "Starting backend and frontend..."
	@make run-backend &
	@make run-frontend

test:
	cd backend && PYTHONPATH=. ../$(VENV)/bin/pytest tests/ -v
