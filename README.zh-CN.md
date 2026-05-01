# Lumina - 文档问答聊天机器人

**语言：** [English](README.md) | 简体中文

一个面向生产的 PDF 文档问答机器人：支持上传 PDF 并基于文档内容进行问答。系统使用 RAG（检索增强生成）保证回答有据可依，并尽量给出可核验的来源信息。

> GitHub 默认展示根目录的 `README.md`。如需阅读英文说明，请点击上方 English 链接。

## 快速开始

### 1. 配置环境变量

复制模板并填入 API Key：

```bash
cp .env.example .env
```

编辑 `.env`，至少配置一个 LLM API Key（例如 `OPENAI_API_KEY`），并配置 embedding provider 的 key（例如 `SILICONFLOW_API_KEY`）。

#### LLM 模型列表如何在前端出现

前端的模型下拉列表会通过 `GET /api/chat/models` 动态获取：**只要你在 `.env` 里配置了某个 provider 的 API key，前端就会显示该 provider 的模型**。

- **OpenAI**：配置 `OPENAI_API_KEY`
- **Anthropic（Claude）**：配置 `ANTHROPIC_API_KEY`
- **Google（Gemini）**：配置 `GOOGLE_API_KEY`
- **DeepSeek**：配置 `DEEPSEEK_API_KEY`

如果某个 provider 的 key 没有配置，该 provider 的模型就不会在前端出现。

### 2. 启动应用

项目提供统一的 Makefile。下面命令会在首次运行时自动安装依赖，并启动后端与前端：

```bash
make run
```

然后在浏览器打开 `http://localhost:3000`。

#### 2.1（可选）本地 embedding（BGE-M3）模式

本项目支持通过 HuggingFace 在本地运行 embedding（`EMBEDDING_PROVIDER=local`）。首次运行通常需要下载模型，并可能占用较多内存/CPU。

我们实测 **云端 embedding provider 通常更快**，默认推荐优先使用云端；只有在需要离线/本地执行时再切换到本地 embedding。

推荐（Makefile）：

```bash
make install
make run-backend-local-embed
make run-frontend
```

说明：
- Makefile 默认使用 `backend/.venv` 虚拟环境，避免 macOS 对全局/用户 site-packages 的权限限制导致安装失败。
- 本地 embedding 会把缓存目录重定向到 `data/cache/`（HuggingFace + LlamaIndex），确保可写。
- 测试建议优先用文本层更完整的 PDF（例如 `腾讯2025年度报告.pdf`）。

#### 2.2（可选）OCR 兜底

解析器默认会记录页级抽取质量诊断。OCR 兜底默认关闭，只会在启用后针对低质量页触发：

```env
OCR_PROVIDER=paddle
OCR_DPI=120
OCR_DETECTION_MODEL=PP-OCRv5_mobile_det
OCR_RECOGNITION_MODEL=PP-OCRv5_mobile_rec
```

启用前先将 OCR 依赖安装到同一个后端 venv：

```bash
make install-ocr
```

可以用美团字体映射失败样本验证真实 OCR 路径：

```bash
make test-ocr
```

如需以 OCR 模式启动后端，并将 Paddle 模型缓存到 `data/cache/paddlex`：

```bash
make run-backend-ocr
```

本地 CPU 验证使用 `美团2024年度报告.pdf`、默认 PP-OCRv5 mobile 模型和 120 DPI。前 10 页集成解析路径平均约 6.2 秒/页，峰值 RSS 约 2.7GB。对于大部分页面都存在字体映射失败的 PDF，整本 OCR 仍可能需要数十分钟，因此该模式更适合作为质量兜底，而不是默认路径。

## 演示（腾讯 2025 年报）

将仓库根目录的 `腾讯2025年度报告.pdf` 上传后，可直接用挑战文档中的示例问题进行验证，例如：

- 上传后请先等待处理完成。UI 可能会依次显示 `PARSING`、`OCR`、`INDEXING`，文档完成后才可查询。
- **事实型**：`腾讯2025年的总收入是多少？` / `公司的CEO是谁？`
- **摘要型**：`总结一下主要业务板块。`
- **比较/推理**：`How much did net profit grow from 2024 to 2025?`

回答应当包含**页码引用**，并可使用右侧 **PDF 预览**对照原文进行核验。

## 测试

运行：

```bash
make test
```

说明：
- 真实 e2e 测试（`backend/tests/test_e2e_real_pdf.py`）需要仓库根目录存在 `腾讯2025年度报告.pdf`，并且 `.env` 中配置了有效的 API key。
- 解析器诊断测试会在仓库根目录存在 `美团2024年度报告.pdf` 时，将其作为真实字体映射失败样本。
- 合约测试不依赖外部 key。

## 检索策略

我们的 RAG 流程基于 LlamaIndex，并针对中文财报等复杂文档做了设计：

1. **PDF 解析**：`pdfplumber` 提取表格为 Markdown；`PyMuPDF` 提取其余文本（更擅长多栏/中文顺序）。解析器会记录每页抽取质量诊断，低质量页可按需启用 PaddleOCR 兜底。
2. **分块**：LlamaIndex `SentenceSplitter`（chunk size: 512, overlap: 128）。表格也会以“整表 Markdown 块”的形式额外入库，避免表头/数值被拆散影响检索。
3. **向量化**：BAAI `BGE-M3`（通过 SiliconFlow API），中英混合检索效果好。
4. **检索**：向量持久化到 `ChromaDB`，余弦相似度检索 `top-k=15`，提升大文档场景的事实召回率。
5. **生成**：将检索片段（含页码与文件名）喂给用户选择的 LLM，并用 prompt 强约束输出带引用的回答。若答案正文明确写出了引用页码，则 sources 列表会优先对齐这些页码；否则回退为少量 top-N sources。

## 取舍与后续改进
* **LLM Adapter vs LiteLLM**：出于供应链安全风险（LiteLLM 曾出现恶意事件），我们选择直接使用官方 SDK（OpenAI/Anthropic/Google/DeepSeek 兼容接口）实现轻量适配层。后续可补全端到端 streaming 来优化交互延迟。
* **支持多个 LLM（Why Multi-LLM）**：我们支持多个 LLM provider，便于满足面试官/用户对具体模型的偏好，也便于在评测阶段对比不同 LLM 的效果。在商用场景下，可以隐藏前端的模型选择功能，由系统默认路由到性价比最优的模型。
* **同时支持云 embedding 与本地 embedding**：从快速实现角度，云 embedding 已足够让项目跑通；但为了提升可运行的确定性（不依赖外部 embedding 服务也能跑），以及便于后续对两种方式做对比评测、择优使用，我们在初版就同时支持云端与本地两种 embedding 模式。
* **Edge case（挑战文档提及但未列明）**：挑战文档提到测试需要覆盖 edge case，但正文未给出明确清单。后续我们会根据补齐的 edge case 来增加测试脚本（如纯图片/需 OCR 的页、`ToUnicode` 缺失导致乱码、极端多栏排版、超大表格、中英混排、空文件/重复上传等），以回归测试的形式确保长期稳定性。
* **PDF 预览（溯源/可核验）**：额外加入 PDF 预览能力，使用户可以快速对照原文核验引用与结论。对于文档问答类产品，“可溯源”是关键体验，预览能显著降低信任成本并帮助用户自行判断答案质量。
* **单用户持久化**：当前文档持久化到磁盘（`/data`），默认单用户工作流。更完整的系统可加入多租户隔离、SQLite 存元数据/会话、以及权限控制。
* **向量库**：`ChromaDB` 适合快速本地开发，但扩展性有限。高吞吐场景可切换到 `Qdrant`/`Milvus`（可容器化部署）。
* **Docker 编排**：当前用 `make run` 追求简单。后续可引入 `docker-compose.yml`，将 Next.js、FastAPI、向量库拆成独立服务，形成更稳的部署形态。
* **重排序（Reranking）**：大文档场景可加入 BGE-Reranker 作为后处理，提高召回质量，代价是检索时延上升。
* **“图文版”PDF / 字体映射失败**：部分 PDF 视觉上正常，但抽取文本效果很差（例如只剩符号），常见原因包括缺失/错误的 `ToUnicode` 映射、子集字体、或文本以图片/矢量方式嵌入。实测案例：美团 2024 年度报告使用 `MHeiHK` 系列 CID 字体，PyMuPDF 和 pdfminer.six 均无法正确解码中文（数字可正常提取）。
  当前进展：解析器已加入页级诊断指标（文本长度、中文占比、符号噪声、表格覆盖率、图片密度、字体名），并支持默认关闭的 PaddleOCR 兜底；前端也已经把处理过程拆成 `PARSING`、`OCR`、`INDEXING` 三个阶段分别展示。
  当前进展：本地 CPU 验证默认使用 PP-OCRv5 mobile 检测/识别模型和 120 DPI，以取得更好的速度/质量平衡；美团前 10 页平均约 6.2 秒/页。
  ~~下一步：为 `PARSING` 和 `OCR` 增加阶段专属百分比，再把索引流程改造成可分批汇报进度的写入路径，让 `INDEXING` 也能显示真实百分比。~~ 已完成（2026-05-01）。
  ~~下一步：索引改造对云端和本地 embedding 的主要正向影响会落在性能与稳定性上，比如更好地控制吞吐、降低资源峰值、并简化失败后的重试与恢复；它本身不会直接提升检索准确度，除非同时调整 chunking、metadata 或 embedding 模型。~~ 已完成（2026-05-01）。
  ~~下一步：代价是 batch 不能为了前端百分比显示而切得过小。过小的 batch 会提高云端 embedding 的网络往返成本，也可能拖慢本地 embedding 的整体吞吐，所以 `INDEXING` 百分比更适合和批大小调优、可恢复写入一起设计，而不是单独为了 UI 硬拆。~~ 已完成（2026-05-01）。
  ~~下一步：把文档处理从进程内后台任务迁移到持久化 job 模型，持久化页级 OCR 结果和索引批次 checkpoint，在服务重启后恢复未完成任务，而不是整单重跑。~~ 已完成（2026-05-01）。
  当前进展：Phase 1 已经落地。系统现在会用 SQLite 持久化文档处理 job，上传后立即创建可恢复任务，文档阶段进度会同步写入 job store，后端重启后也会把未完成任务重新排回处理队列，而不是直接忘掉。
  当前进展：Phase 2 也已经落地到解析/OCR 路径。解析器现在会把每页 checkpoint 写到 `data/jobs/<doc_id>/pages`，重跑时会直接复用已完成的原生解析结果，并跳过中断前已经完成 OCR 的页面。
  当前进展：Phase 3 也已经落地到索引路径。索引器保持现有文本 chunk 和整表 node 的语义不变，为 node 分配稳定 id，并改成显式 batch 写入；前端看到的 `INDEXING` 百分比现在来自持久化的 node/batch 计数，而不是终端里的 embedding 进度日志。
  当前进展：Phase 4 也已经落地到恢复控制层。job 现在带有 lease owner 和 heartbeat；后端启动时会回收上一进程遗留的 running job，运行中也会周期性回收超时 lease；索引恢复时会从“最后一个完整完成的 batch”继续，只重跑当前 unfinished batch，并通过稳定 node id 保持写入幂等。
  实施方案：见 [持久化 Job 与索引改造计划](spec/persistent_jobs_and_indexing_plan.md)。

## 开发：保持 Cursor rules 一致

本仓库把 `spec/agent_rules.md` 作为规则单一真源。根目录 `AGENTS.md` 是 Codex 入口，`.cursorrules` 和 `.agents/workflows/agent_rules.md` 必须与规则真源保持一致。

本地启用 pre-commit 校验：

```bash
pip install pre-commit
pre-commit install
```

手动校验：

```bash
python3 scripts/check_agent_rules_sync.py
```
