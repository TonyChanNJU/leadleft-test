.PHONY: run run-backend run-backend-local-embed run-backend-ocr run-frontend install install-ocr test test-ocr

VENV := backend/.venv
PYTHON ?= python3
PY := $(VENV)/bin/python
PIP := $(PY) -m pip

BACKEND_PORT ?= 8000
OCR_CACHE_HOME ?= data/cache/paddlex
OCR_CACHE_HOME_ABS := $(abspath $(OCR_CACHE_HOME))

install:
	@test -d "$(VENV)" || $(PYTHON) -m venv "$(VENV)"
	@$(PIP) install -U pip
	@$(PIP) install -r backend/requirements.txt
	cd frontend && npm install

install-ocr: install
	@$(PIP) install -r backend/requirements-ocr.txt

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

run-backend-ocr: install-ocr
	mkdir -p $(OCR_CACHE_HOME_ABS)
	cd backend && \
	PADDLE_PDX_CACHE_HOME=$(OCR_CACHE_HOME_ABS) \
	PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True \
	OCR_PROVIDER=paddle \
	BACKEND_PORT=$(BACKEND_PORT) ../$(VENV)/bin/uvicorn app.main:app --reload --port $(BACKEND_PORT)

run-frontend:
	cd frontend && BACKEND_PORT=$(BACKEND_PORT) NEXT_PUBLIC_BACKEND_PORT=$(BACKEND_PORT) npm run dev

run: install
	@echo "Starting backend and frontend..."
	@make run-backend &
	@make run-frontend

test:
	cd backend && PYTHONPATH=. ../$(VENV)/bin/pytest tests/ -v

test-ocr: install-ocr
	mkdir -p $(OCR_CACHE_HOME_ABS)
	cd backend && \
	PADDLE_PDX_CACHE_HOME=$(OCR_CACHE_HOME_ABS) \
	PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True \
	PYTHONPATH=. ../$(VENV)/bin/python tests/run_ocr_smoke.py
