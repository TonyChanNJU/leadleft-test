# Coding Challenge: Document Q&A Chatbot

## Overview

Build a chatbot that lets a user upload a PDF and then ask natural-language questions about its content. The bot should ground its answers in the uploaded document and be honest when the document doesn't contain an answer.

We are evaluating how you scope, design, and implement a real-world feature — not how many features you can ship.

You may use any language, framework, LLM, and libraries you like. The program should take the form of a web chat UI. Commit to a public Git repo and send us the link.

A sample PDF is provided with this challenge (`腾讯2025年度报告.pdf`, a Chinese-language annual report). Your bot should work on it end-to-end.

---

## What the chatbot must do

### PDF upload
- Accept a PDF upload from the user.
- Extract text. Handle multi-column layouts, tables, and Chinese text reasonably well — perfect table parsing is not required, but a page of Chinese should not come out as gibberish.
- The bot should know which document(s) the current user has uploaded and scope answers to them.

### Question answering
- A chat interface where the user asks questions in natural language and gets grounded answers.
- Answers must be based on the uploaded PDF, not the model's prior knowledge. If the document doesn't contain the answer, the bot should say so rather than guess.
- Cite the source — at minimum, the page number(s) the answer came from. A short quoted snippet is even better.

### Persistence
- Uploaded PDFs and their extracted content survive a restart. The user shouldn't need to re-upload on every session.

### Tests
- Enough tests to catch real regressions on the important cases (see "Edge cases" below). We are not grading coverage percentage.

---

## Sample questions your bot should handle well

Given the provided Tencent annual report, your bot should be able to answer questions like these.

**Factual lookup (single fact from the doc):**
- 腾讯2025年的总收入是多少？ / What was Tencent's total revenue in 2025?
- 公司的CEO是谁？ / Who is the CEO of the company?
- 报告期末员工总数是多少？ / How many employees did the company have at year-end?

**Section summarization:**
- 总结一下主要业务板块。 / Summarize the main business segments.
- What are the top three risk factors mentioned in the report?
- 简要介绍公司的AI战略。 / Briefly describe the company's AI strategy.

**Comparison / numerical reasoning:**
- 2025年的净利润相比2024年增长了多少？ / How much did net profit grow from 2024 to 2025?
- Which business segment grew fastest year-over-year?

---

## Deliverables

1. A Git repo with your code.
2. A `README.md` with:
   - Setup + run instructions (one command to start, ideally `docker compose up` or `make run`)
   - Which model(s) and embedding provider you used, and how to plug in API keys
   - How to upload a PDF and start chatting (include the provided Tencent report as a demo)
   - Your retrieval strategy in 3–5 sentences (chunk size, overlap, embedding model, any reranking)
   - Trade-offs and what you would do next with more time
3. A few screenshots of a real chat session against the provided PDF.

---

We read every submission. Looking forward to seeing your work.
