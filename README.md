# 🎓 Student Study Assistant
### *Your AI-Powered Personal Tutor *


> Upload your lecture notes. Get personalized explanations from 5 AI agents. Chat with your tutor. Never forget what you studied — with science-backed spaced repetition.

---

## 📖 Table of Contents

- [What is this?](#-what-is-this)
- [How it Works](#️-how-it-works)
- [The 5 AI Agents](#-the-5-ai-agents)
- [Key Features](#-key-features)
- [Project Structure](#-project-structure)
- [File-by-File Breakdown](#️-file-by-file-breakdown)
- [Database Schema](#️-database-schema)
- [Tech Stack](#️-tech-stack)
- [Quick Start](#-quick-start)
- [Deployment](#️-deployment)
- [Agent 5 — What Can You Ask?](#-agent-5--what-can-you-ask)
- [Spaced Repetition Science](#-spaced-repetition-science)
- [Lazy Loading Architecture](#-lazy-loading-architecture)
- [Contributing](#-contributing)

---

## 🤔 What is this?

Most AI tools just **summarize your PDF**. This project goes much further.

**Student Study Assistant** is a production-grade AI application that acts as a full personal tutor. It doesn't just read your notes — it researches the web for the best explanations, teaches you using your own words, generates personalized quizzes, and reminds you exactly when to review each topic based on cognitive science.

### The Problem it Solves

Students face three core challenges:
1. **Understanding** — dense lecture notes are hard to parse alone
2. **Depth** — notes don't always explain *why* something works
3. **Retention** — even understood content fades without the right review schedule

This application solves all three with a pipeline of 5 specialized AI agents working in sequence, backed by RAG, LangGraph orchestration, SQLite persistence, and the SM-2 spaced repetition algorithm used by Anki and Duolingo.

---

## ⚙️ How it Works

```
                    ┌──────────────────────────────────────────────┐
                    │         STUDENT STUDY ASSISTANT              │
                    └──────────────────────────────────────────────┘

Student uploads PDF
        │
        ▼
┌───────────────────┐     Smart extraction:
│   RAG ENGINE      │  →  PyPDF2 for text PDFs
│  (rag_engine.py)  │  →  pdfplumber for tables
└───────────────────┘  →  Tesseract OCR for scanned PDFs
        │                  Broken text cleaning (word\n \nword fixed)
        ▼
┌───────────────────┐
│  FAISS Vector DB  │  Chunks stored as Gemini embeddings
│  (per chat)       │  Saved to disk — survives app restart
└───────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│                    LANGGRAPH PIPELINE                        │
│                                                              │
│  INIT GRAPH (runs once per PDF, ~10 seconds):               │
│  Agent 1 → Extract ALL topics → Create pending DB entries   │
│                                                              │
│  TOPIC GRAPH (runs per topic, lazy loading ~50s each):      │
│  Agent 2 → Web Search & Scrape                              │
│      ↓                                                       │
│  Agent 3 → FAISS Search → Notes-based explanation           │
│      ↓                                                       │
│  Agent 4 → Synthesize → ELI5 + Code + Quiz                 │
│      ↓                                                       │
│  Save to SQLite → Mark topic "done" → Refresh UI            │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────┐     Always available (even mid-pipeline):
│   AGENT 5 TUTOR   │  →  Full conversation memory (SQLite)
│   (memory.py)     │  →  FAISS context search per question
└───────────────────┘  →  Streams word by word like ChatGPT
        │
        ▼
┌───────────────────┐
│ SPACED REPETITION │  SM-2 Algorithm → next review date per topic
└───────────────────┘  Notifications → "Review Binary Search today!"
```

---

## 🤖 The 5 AI Agents

Each agent is a specialized Python function powered by **Groq LLaMA 3.1 8B** (free, fastest inference available).

### 🧠 Agent 1 — PDF Reader
**File:** `agents.py → run_pdf_reader()`

Scans all FAISS chunks from the student's PDF and extracts a structured list of every CS topic covered. Returns topics with difficulty levels, prerequisites, knowledge gaps, and a suggested study order.

- **Input:** Raw text chunks from the PDF
- **Output:** `{"topics": [...], "difficulty": {...}, "prerequisites": {...}, "study_order": [...]}`
- **Speed:** ~10 seconds (runs once per PDF, not per topic)

### 🌐 Agent 2 — Web Researcher
**File:** `agents.py → run_web_researcher()`

Takes each topic and processes pre-fetched web content into a clean structured explanation. Prioritizes GeeksForGeeks, Wikipedia, Programiz, and other trusted CS sources automatically.

- **Input:** Topic name + raw scraped web content
- **Output:** Structured Markdown with Definition, How It Works, Example, Complexity, Key Points
- **Speed:** ~15 seconds per topic

### 📝 Agent 3 — Notes Analyst
**File:** `agents.py → run_notes_analyst()`

Uses FAISS similarity search to find the most relevant chunks from the student's own PDF for each topic. Explains the topic using the professor's exact words and examples — making it feel personal and familiar.

- **Input:** Topic name + relevant PDF chunks (from FAISS)
- **Output:** Notes-based explanation with "Your notes say..." / "According to your PDF..."
- **Speed:** ~15 seconds per topic

### 🎓 Agent 4 — Synthesizer
**File:** `agents.py → run_synthesizer()`

The most powerful agent. Combines Agent 2's web explanation and Agent 3's notes explanation into one complete study guide per topic. Also generates 5 targeted quiz questions with answers.

- **Input:** Topic + Agent 2 output + Agent 3 output
- **Output:** ELI5 explanation + full explanation + common mistakes + Python code + 5 quiz Q&A
- **Speed:** ~20 seconds per topic

### 💬 Agent 5 — Tutor
**File:** `memory.py`

The conversational agent — available at all times, even while Agents 1-4 are still processing other topics. Has access to the full conversation history, all previous agent outputs, the student's FAISS index, and their quiz weak points. Can answer **any CS question** — not just topics in the PDF.

- **Input:** Student question + conversation history + system context
- **Output:** Streamed response (word by word, like ChatGPT)
- **Speed:** ~3-5 seconds per response

---

## ✨ Key Features

| Feature | Description |
|---|---|
| **⚡ Lazy Loading** | Topics appear one by one — read immediately while others load |
| **💬 Streaming Chat** | Agent 5 streams responses word by word, exactly like ChatGPT |
| **🧠 Full Memory** | Agent 5 remembers the entire conversation history across sessions |
| **🔄 Spaced Repetition** | SM-2 algorithm schedules optimal review times, like Anki |
| **📊 Progress Dashboard** | Track topics studied, quiz scores, mastery, upcoming reviews |
| **🌐 Web Research** | Auto-searches GeeksForGeeks, Wikipedia, Programiz per topic |
| **📄 Multi-PDF Support** | Upload multiple PDFs per chat — merged into one knowledge base |
| **💾 Persistent Storage** | SQLite + FAISS saved to disk — all chats survive app restarts |
| **✏️ Chat Management** | Rename, delete, and resume any previous chat session |
| **🔔 Review Reminders** | Notification badge when topics are due for review |
| **🔍 Smart PDF Parsing** | Handles text PDFs, scanned PDFs (OCR), and PDFs with tables |
| **📈 LangSmith Monitoring** | Optional full observability of every LLM call and agent step |

---

## 📁 Project Structure

```
StudentStudyAssistant/
│
├── app.py                   ← Streamlit UI (3 pages: Chat, Dashboard, Review)
├── agents.py                ← 5 AI agent functions (Groq + LangChain)
├── tasks.py                 ← Task orchestration (what each agent does)
├── graph.py                 ← LangGraph state machines (init + topic graphs)
├── rag_engine.py            ← PDF extraction + FAISS vector store
├── web_search.py            ← DuckDuckGo search + BeautifulSoup scraping
├── memory.py                ← Agent 5 memory + streaming (Groq LLM)
├── database.py              ← SQLite CRUD for all 6 tables
├── spaced_repetition.py     ← SM-2 algorithm wrapper + dashboard data
├── review_session.py        ← Quiz generation + AI-graded evaluation
│
├── requirements.txt         ← Python dependencies
├── .env                     ← API keys (never commit this!)
├── .gitignore               ← Files excluded from git
├── LICENSE                  ← MIT License
│
├── study_assistant.db       ← SQLite database (auto-created on first run)
└── faiss_indexes/           ← FAISS vector indexes per chat (auto-created)
    ├── chat_1/
    │   ├── index.faiss
    │   ├── index.pkl
    │   └── chunks.json
    └── chat_2/
        └── ...
```

---

## 🗂️ File-by-File Breakdown

### `app.py` — The UI
Three-page Streamlit application:
- **Chat Page:** Upload PDF → lazy-loading progress bar → expandable topic cards (Web / Notes / Study Guide sub-tabs) → Agent 5 chat always at bottom
- **Dashboard Page:** Overall stats, due reviews with one-click button, upcoming review calendar, mastered/needs-work topic lists
- **Review Page:** AI-generated quiz per topic, AI-graded evaluation, SM-2 schedule update, detailed per-question feedback

Key behavior: Topics shown as `✅ Ready` or `🔵 Queued`. Page auto-reruns every 3 seconds to pick up newly completed topics. Agent 5 chat always available even mid-processing.

---

### `agents.py` — The AI Workers
Four agent functions using `ChatGroq` with `llama-3.1-8b-instant`. No CrewAI — pure Python functions for simplicity and Windows compatibility (avoids litellm long-path issues).

```python
run_pdf_reader(chunks, chat_id)             # → dict with topics + metadata
run_web_researcher(topics, web_results)     # → formatted Markdown string
run_notes_analyst(topics, chat_id)          # → formatted Markdown string
run_synthesizer(topics, web_out, notes_out) # → full study guide + quiz
```

Each function builds a detailed system prompt, calls the LLM with retry logic, and returns structured output. Agent 1 requests JSON for reliable topic parsing with a fallback text parser.

---

### `tasks.py` — Task Coordination
Orchestrates what each agent does and ensures outputs are saved correctly:

- `task_extract_topics(chat_id)` — runs Agent 1, creates `pending` DB entries for each topic, schedules spaced repetition entries
- `run_single_topic(chat_id, topic)` — runs Agents 2, 3, 4 for ONE topic in sequence. Updates status: `pending → processing → done`
- `save_combined_summary(chat_id, topics)` — combines all topic outputs into a single summary for Agent 5's context

---

### `graph.py` — LangGraph Orchestration
Two LangGraph state machines:

**Init Graph** (runs once per PDF, ~10s):
```
START → node_extract_topics → END
```

**Topic Graph** (runs per topic, ~50s):
```
START → node_process_topic → END
```

Public API called by `app.py`:
- `initialize_chat(chat_id)` — runs init graph or returns cached result
- `process_next_topic(chat_id)` — picks next pending topic, runs topic graph
- `get_progress(chat_id)` — returns `{total, done, pending, pct, complete}`
- `has_pending_topics(chat_id)` — bool for loop control in app.py

LangSmith tracing is enabled here when `LANGCHAIN_API_KEY` is set in `.env`.

---

### `rag_engine.py` — PDF Intelligence
Smart PDF extraction with 3-method cascade:
1. `extract_text_pypdf2()` — fast, for standard text PDFs
2. `extract_text_pdfplumber()` — better, handles tables and complex layouts
3. `extract_text_ocr()` — Tesseract OCR for scanned/image-based PDFs

`clean_pdf_text()` fixes the common `word\n \nword` broken-text pattern from custom-font PDFs using regex.

FAISS embeddings use **lazy initialization** — the model is only created when first needed, not at import time. This prevents SSL timeout errors when other modules import `rag_engine`.

Key functions: `process_pdfs_for_chat()`, `search_faiss()`, `get_all_chunks()`, `load_faiss()`, `faiss_exists()`

---

### `web_search.py` — Web Intelligence
1. **Search:** DuckDuckGo (`ddgs`) with CS-optimized query
2. **Prioritize:** GeeksForGeeks → Wikipedia → Programiz → Tutorialspoint → others
3. **Scrape:** BeautifulSoup with site-specific extractors
4. **Clean:** Removes menus, ads, short lines, non-alpha content, truncates at 4000 chars
5. **Fallback:** Combines search result snippets if scraping fails

---

### `memory.py` — Agent 5's Brain
`build_system_prompt()` injects 5 context layers into every LLM call: agent outputs, student weak topics, relevant FAISS chunks, chat metadata, role instructions.

`stream_tutor_response()` is a generator that yields text chunks and is used directly with Streamlit's `st.write_stream()`. The full response is saved to SQLite after streaming completes.

FAISS search in memory.py uses a lazy import (`from rag_engine import search_faiss` inside the function) to avoid circular imports and SSL initialization at module load.

---

### `database.py` — Persistence Layer
30+ CRUD functions across 6 SQLite tables. Key non-obvious functions:

- `create_topic_entry()` — idempotent, only inserts if topic doesn't already exist
- `get_topic_statuses()` — returns `{topic: status}` dict without loading content (fast, used for polling)
- `get_pending_topics()` — ordered list of unprocessed topics
- `update_spaced_repetition()` — full SM-2 calculation + single DB update

---

### `spaced_repetition.py` — Retention Science
Thin wrapper around database SM-2 functions plus dashboard data aggregation:
- `process_quiz_result()` — calls SM-2 update, returns human-readable next-review message
- `get_dashboard_data()` — aggregates stats, due reviews, upcoming schedule, mastered/needs-work splits
- `get_due_count()` — fast integer count for sidebar notification badge

---

### `review_session.py` — Quiz Engine
- `generate_review_quiz()` — Groq generates 5 targeted questions in JSON, focused on the student's previous weak areas
- `evaluate_answers()` — Groq evaluates each answer semantically (not just keyword matching)
- `complete_review_session()` — full flow: evaluate → save score → update SM-2 → return results

---

## 🗄️ Database Schema

```sql
-- Each study session (like a ChatGPT conversation)
CREATE TABLE chats (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    pdf_name   TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- One row per topic per chat — core table for lazy loading
-- status: 'pending' → 'processing' → 'done' | 'error'
CREATE TABLE topic_outputs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id      INTEGER NOT NULL,
    topic        TEXT NOT NULL,
    web_output   TEXT DEFAULT '',
    notes_output TEXT DEFAULT '',
    final_output TEXT DEFAULT '',    -- includes ELI5, code, quiz questions
    status       TEXT DEFAULT 'pending',
    error_msg    TEXT DEFAULT '',
    FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
);

-- Full conversation history per chat (Agent 5 memory)
CREATE TABLE messages (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id   INTEGER NOT NULL,
    role      TEXT NOT NULL,         -- 'user' or 'assistant'
    content   TEXT NOT NULL,
    timestamp TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
);

-- Quiz attempt history
CREATE TABLE quiz_scores (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id         INTEGER NOT NULL,
    topic           TEXT NOT NULL,
    score           INTEGER DEFAULT 0,
    total_questions INTEGER DEFAULT 0,
    wrong_topics    TEXT DEFAULT '[]',   -- JSON list
    attempted_at    TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
);

-- SM-2 review schedule — one row per topic per chat
CREATE TABLE spaced_repetition (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id          INTEGER NOT NULL,
    topic            TEXT NOT NULL,
    next_review_date TEXT DEFAULT '',    -- KEY: when to show reminder
    review_count     INTEGER DEFAULT 0,
    ease_factor      REAL DEFAULT 2.5,   -- SM-2 interval multiplier
    interval_days    INTEGER DEFAULT 1,
    last_score       REAL DEFAULT 0.0,
    is_mastered      INTEGER DEFAULT 0,  -- 1 after 5+ reviews with score >= 80%
    FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
);

-- Combined summary for Agent 5 context
CREATE TABLE agent_outputs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id      INTEGER NOT NULL,
    topics       TEXT DEFAULT '',        -- JSON list of all topics
    web_output   TEXT DEFAULT '',
    notes_output TEXT DEFAULT '',
    final_output TEXT DEFAULT '',
    FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
);
```

---

## 🛠️ Tech Stack

| Layer | Technology | Why Chosen |
|---|---|---|
| **LLM** | Groq (LLaMA 3.1 8B) | Free tier (14,400 req/day), fastest inference available |
| **Embeddings** | Gemini Embedding-001 | Free, high quality semantic search |
| **Vector DB** | FAISS (CPU) | Fast local similarity search, no server needed |
| **Orchestration** | LangGraph | State machines for reliable multi-step agent pipelines |
| **RAG Framework** | LangChain | Standardized LLM and retrieval interface |
| **PDF Parsing** | PyPDF2 + pdfplumber + Tesseract | Cascading fallback handles any PDF type |
| **Web Search** | ddgs (DuckDuckGo) | Free, no API key, reliable for CS queries |
| **Web Scraping** | BeautifulSoup4 | Site-specific extractors for GFG, Wikipedia |
| **Database** | SQLite | Zero-config, file-based, built into Python |
| **UI** | Streamlit | Fastest way to ship Python web apps |
| **Monitoring** | LangSmith (optional) | Full observability of every agent step |

---

## 🚀 Quick Start

### Prerequisites
- Python 3.10+
- **Groq API key** (free) → [console.groq.com](https://console.groq.com)
- **Google Gemini API key** (free, for embeddings only) → [aistudio.google.com](https://aistudio.google.com/app/apikey)

### Step 1 — Clone the repository
```bash
git clone https://github.com/YOUR_USERNAME/student-study-assistant.git
cd student-study-assistant
```

### Step 2 — Create virtual environment
```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Mac / Linux
source venv/bin/activate
```

### Step 3 — Install dependencies
```bash
pip install -r requirements.txt
```

### Step 4 — Set up API keys
Create a `.env` file in the root folder:
```env
GOOGLE_API_KEY=your_gemini_api_key_here
GROQ_API_KEY=your_groq_api_key_here

# Optional — LangSmith observability
LANGCHAIN_API_KEY=your_langsmith_key_here
LANGCHAIN_TRACING_V2=true
LANGCHAIN_PROJECT=StudentStudyAssistant
```

### Step 5 — Run
```bash
streamlit run app.py
```

Open **http://localhost:8501** in your browser.

---

## ☁️ Deployment

### Streamlit Community Cloud (Free, Recommended for demos)

1. Push code to a public GitHub repository
2. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with GitHub
3. Click **New app** → select repo → set main file to `app.py`
4. Open **Advanced settings** → add secrets:

```toml
GOOGLE_API_KEY = "your_key_here"
GROQ_API_KEY = "your_key_here"
```

5. Click **Deploy** — live in ~2 minutes

> ⚠️ Streamlit Cloud uses ephemeral storage. SQLite and FAISS reset on restart. For persistent data use Railway or Render.

---

### Railway (Free tier, persistent storage)

1. Create account at [railway.app](https://railway.app)
2. New Project → Deploy from GitHub repo
3. Add environment variables in the Railway dashboard
4. Add `Procfile` to repo root:

```
web: streamlit run app.py --server.port=$PORT --server.address=0.0.0.0
```

5. Deploy — DB and FAISS files persist between restarts.

---

### Docker (Any cloud provider)

Add `Dockerfile` to repo root:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8501

HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health

ENTRYPOINT ["streamlit", "run", "app.py", \
            "--server.port=8501", \
            "--server.address=0.0.0.0"]
```

```bash
docker build -t study-assistant .
docker run -p 8501:8501 \
  -e GOOGLE_API_KEY=your_key \
  -e GROQ_API_KEY=your_key \
  study-assistant
```

---

## 💬 Agent 5 — What Can You Ask?

Agent 5 is a **general CS tutor**. It is NOT limited to only the topics in your PDF.

### What Agent 5 can answer

| Question Type | Example |
|---|---|
| Topics in your PDF | "Explain backpropagation from my notes" |
| General CS concepts | "What is a B-tree and when do you use it?" |
| Follow-up questions | "Give me Python code for what you just explained" |
| Comparisons | "What's the difference between TCP and UDP?" |
| Quiz clarification | "Why was my answer to Q3 wrong?" |
| Concept connections | "How does gradient descent relate to backpropagation?" |
| Code requests | "Write a Python implementation of quicksort" |
| Conceptual depth | "Why does regularization help prevent overfitting?" |

### What Agent 5 cannot answer

| Limitation | Reason |
|---|---|
| Real-time information | No live internet during chat |
| Latest research papers | LLaMA 3.1 knowledge cutoff |
| Non-CS topics | System prompt focuses it on CS education |

### How Agent 5 Remembers

Every response from Agent 5 is built with this full context:

```
System prompt:
├── All topics found in your PDF
├── Web explanations from Agent 2
├── Notes explanations from Agent 3
├── Study guide from Agent 4
└── Topics you scored poorly on (quiz history)

+ Last 20 conversation messages (from SQLite)
+ Top 3 FAISS chunks most relevant to your question
+ Your current question
```

This entire context is rebuilt and sent with every single message. This is exactly how ChatGPT maintains memory — there is no magic, just context injection.

---

## 🔬 Spaced Repetition Science

This app implements the **SM-2 algorithm** — the same algorithm used by Anki (used by millions of medical students worldwide).

### The Ebbinghaus Forgetting Curve

Without review, memory decays exponentially:
- After 1 day: ~58% retained
- After 7 days: ~25% retained
- After 30 days: ~5% retained

With correctly timed reviews, retention stays near 100%.

### SM-2 Formula

```
Score >= 80%  →  interval = interval × ease_factor
               ease_factor += 0.1  (max 3.0)
               (You know it well — review less often)

Score 60-79%  →  interval = interval × 1.2
               ease_factor unchanged

Score < 60%   →  interval = 1 day (reset to tomorrow)
               ease_factor -= 0.2  (min 1.3)
               (You need more practice)

Typical progression:  Day 1 → Day 3 → Day 7 → Day 14 → MASTERED
```

After 5+ reviews with score >= 80%, the topic is marked **MASTERED** and removed from the review queue.

---

## ⚡ Lazy Loading Architecture

For a 40-topic PDF, processing all topics takes ~30 minutes total. Batch processing would make the app unusable. Lazy loading solves this.

### Timeline

```
Time 0:10  → Agent 1 done → 40 topics visible (all pending)
Time 0:30  → Topic 1 done → Student reads Neural Networks
Time 0:50  → Topic 2 done → Student reads Backpropagation
Time 1:10  → Topic 3 done → Student reads Adam Optimizer
...continuing in background...
Time 30:00 → All 40 done → Complete study guide available
```

The student starts reading from the 30-second mark, not the 30-minute mark.

### Implementation in app.py

```python
# 1. Show all ready topics with full content
for topic in done_topics:
    with st.expander(f"✅ {topic}"):
        # sub-tabs: Web | Notes | Study Guide

# 2. Show queued topics
for topic in pending_topics:
    st.markdown(f"🔵 {topic} — Queued")

# 3. Give student 3 seconds to read
time.sleep(3)

# 4. Process one more topic in background
process_next_topic(chat_id)

# 5. Refresh UI — new topic now appears as ready
st.rerun()
```

---

## 🤝 Contributing

Contributions are welcome. Good first issues:

- [ ] Export study notes as PDF using `reportlab`
- [ ] Support for `.docx` files using `python-docx`
- [ ] YouTube video suggestions per topic
- [ ] Code execution sandbox using `Judge0 API`
- [ ] Study streak tracking and gamification
- [ ] Support for non-English PDFs

To contribute:
```bash
git fork
git checkout -b feature/your-feature
git commit -m "Add your feature"
git push origin feature/your-feature
# Open a Pull Request
```

---

## 📄 License

Distributed under the MIT License. See `LICENSE` for details.

---

## 🙏 Acknowledgements

- [LangChain](https://langchain.com) — LLM framework and RAG tooling
- [LangGraph](https://langchain-ai.github.io/langgraph/) — Agent orchestration
- [Groq](https://groq.com) — Ultra-fast free LLM inference
- [Google Gemini](https://ai.google.dev) — Free embedding model
- [FAISS](https://faiss.ai) — Facebook AI Similarity Search
- [Streamlit](https://streamlit.io) — Python web app framework
- [GeeksForGeeks](https://geeksforgeeks.org) — Primary CS knowledge source
- [SM-2 Algorithm](https://super-memory.com/english/ol/sm2.htm) — Spaced repetition algorithm by Piotr Wozniak

---

*Built as a demonstration of production-grade multi-agent AI systems combining RAG, LangGraph, streaming, and spaced repetition.*
