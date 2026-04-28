# DocChat — 文档问答聊天机器人

## 项目概述

基于 RAG（检索增强生成）的 PDF 文档问答聊天机器人。用户上传 PDF 文件后，可通过自然语言提问，机器人基于文档内容回答并引用出处。

---

## 技术栈

### 后端
| 层 | 技术 | 说明 |
|---|------|------|
| Web 框架 | **FastAPI** | 异步、高性能、自带 OpenAPI 文档 |
| RAG 引擎 | **LlamaIndex** | 文档加载、分块、索引、查询引擎 |
| 向量数据库 | **ChromaDB** | 嵌入式、持久化到磁盘 |
| PDF 解析 | **PyMuPDF + pdfplumber** | 文本提取 + 表格解析 |
| Embedding | **BGE-M3** | 默认 SiliconFlow 云 API，可切换本地 |
| LLM | **自建适配层** | 直接调用官方 SDK（openai / anthropic / google-generativeai） |
| 数据库 | **SQLite**（可选） | 文档元数据存储 |

### 前端
| 层 | 技术 | 说明 |
|---|------|------|
| 框架 | **Next.js (React)** | SSR、路由、API 代理 |
| 样式 | **Tailwind CSS** | 实用优先 CSS 框架，现代设计 |

### 部署
| 工具 | 说明 |
|------|------|
| **Makefile** | `make run` 一键启动（当前阶段） |
| **Docker Compose** | 后续增量添加 |

---

## 架构

```
┌──────────────────┐        ┌────────────────────────────────┐
│   Next.js 前端    │──API──▶│        FastAPI 后端             │
│                  │        │                                │
│  • ChatWindow    │        │  ┌────────────────────────┐    │
│  • FileUpload    │        │  │     LlamaIndex         │    │
│  • ModelSelector │        │  │  • SentenceSplitter    │    │
│  • CitationCard  │        │  │  • VectorStoreIndex   │    │
└──────────────────┘        │  │  • CitationQueryEngine│    │
                            │  └──────┬─────────┬──────┘    │
                            │         │         │           │
                            │  ┌──────▼───┐ ┌───▼────────┐ │
                            │  │ ChromaDB │ │ LLM Adapter│ │
                            │  │ (BGE-M3) │ │ GPT/Claude │ │
                            │  │          │ │ Gemini/DS  │ │
                            │  └──────────┘ └────────────┘ │
                            └────────────────────────────────┘

数据持久化:
  data/uploads/   ← 原始 PDF 文件
  data/chroma/    ← ChromaDB 向量索引
```

---

## 支持的 LLM 模型

| Provider | 模型 | SDK | 备注 |
|----------|------|-----|------|
| OpenAI | GPT-4o, GPT-4o-mini | `openai` | — |
| Anthropic | Claude 3.5 Sonnet, Claude 3 Opus | `anthropic` | — |
| Google | Gemini 2.0 Flash, Gemini 2.0 Pro | `google-generativeai` | — |
| DeepSeek | DeepSeek-V3, DeepSeek-R1 | `openai`（兼容接口） | base_url 替换 |

---

## Embedding 配置

| 模式 | Provider | 说明 |
|------|----------|------|
| **cloud**（默认） | SiliconFlow | `BAAI/bge-m3`，OpenAI 兼容接口 |
| **local** | sentence-transformers | 本地加载 BGE-M3，需 ~2GB 内存 |

---

## RAG 检索策略

1. **PDF 解析**：PyMuPDF 提取文本块 + pdfplumber 解析表格 → 按页合并
2. **分块**：`SentenceSplitter`，chunk_size=512 tokens，overlap=128 tokens
3. **向量化**：BGE-M3（中英文混合优秀，1024 维向量）
4. **检索**：ChromaDB 余弦相似度，top-k=5
5. **引用**：CitationQueryEngine 自动标注页码与原文片段
6. **生成**：Prompt 要求模型基于检索内容回答，无法回答时坦然说明

---

## 目录结构

```
leadleft-test/
├── spec/                       # 项目规范（本文件夹）
├── backend/
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── routers/
│   │   │   ├── upload.py
│   │   │   ├── chat.py
│   │   │   └── documents.py
│   │   └── services/
│   │       ├── pdf_parser.py
│   │       ├── indexer.py
│   │       ├── query_engine.py
│   │       ├── llm_provider.py
│   │       └── embedding.py
│   └── tests/
├── frontend/
│   ├── package.json
│   └── src/
│       ├── app/
│       └── components/
├── data/                       # 运行时数据（.gitignore）
├── Makefile
└── README.md
```

---

## 环境变量

```env
# LLM（至少配置一个）
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_API_KEY=AI...
DEEPSEEK_API_KEY=sk-...

# Embedding
EMBEDDING_PROVIDER=cloud          # cloud | local
SILICONFLOW_API_KEY=sk-...        # cloud 模式必填

# 应用
DEFAULT_LLM_MODEL=gpt-4o
BACKEND_PORT=8000
FRONTEND_PORT=3000
```
