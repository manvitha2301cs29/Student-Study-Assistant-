# database.py
# ─────────────────────────────────────────────────────────────────────────────
# Handles ALL SQLite database operations
#
# TABLES:
# 1. chats              → each chat session
# 2. agent_outputs      → combined outputs (legacy + summary)
# 3. topic_outputs      → NEW: one row per topic (for lazy loading)
# 4. messages           → full conversation history
# 5. quiz_scores        → quiz attempts and scores
# 6. spaced_repetition  → SM-2 review schedule
# ─────────────────────────────────────────────────────────────────────────────

import sqlite3
import json
from datetime import datetime, date, timedelta
from typing import Optional

DB_PATH = "study_assistant.db"


# ─────────────────────────────────────────────────────────────────────────────
# CONNECTION
# ─────────────────────────────────────────────────────────────────────────────
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ─────────────────────────────────────────────────────────────────────────────
# INITIALIZE DATABASE
# ─────────────────────────────────────────────────────────────────────────────
def init_database():
    """Create all tables. Safe to call multiple times."""
    conn   = get_connection()
    cursor = conn.cursor()

    # ── Table 1: chats ────────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chats (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            pdf_name    TEXT    DEFAULT '',
            created_at  TEXT    DEFAULT (datetime('now')),
            updated_at  TEXT    DEFAULT (datetime('now'))
        )
    """)

    # ── Table 2: agent_outputs (summary — one row per chat) ───────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS agent_outputs (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id       INTEGER NOT NULL,
            topics        TEXT    DEFAULT '',
            web_output    TEXT    DEFAULT '',
            notes_output  TEXT    DEFAULT '',
            final_output  TEXT    DEFAULT '',
            FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
        )
    """)

    # ── Table 3: topic_outputs (NEW — one row per topic) ─────────────────────
    # This is the KEY table for lazy loading
    # Each topic has its own row with its own status
    # status: "pending" → "processing" → "done" | "error"
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS topic_outputs (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id       INTEGER NOT NULL,
            topic         TEXT    NOT NULL,
            web_output    TEXT    DEFAULT '',
            notes_output  TEXT    DEFAULT '',
            final_output  TEXT    DEFAULT '',
            status        TEXT    DEFAULT 'pending',
            error_msg     TEXT    DEFAULT '',
            created_at    TEXT    DEFAULT (datetime('now')),
            updated_at    TEXT    DEFAULT (datetime('now')),
            FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
        )
    """)

    # ── Table 4: messages ─────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id     INTEGER NOT NULL,
            role        TEXT    NOT NULL,
            content     TEXT    NOT NULL,
            timestamp   TEXT    DEFAULT (datetime('now')),
            FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
        )
    """)

    # ── Table 5: quiz_scores ──────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS quiz_scores (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id         INTEGER NOT NULL,
            topic           TEXT    NOT NULL,
            score           INTEGER DEFAULT 0,
            total_questions INTEGER DEFAULT 0,
            wrong_topics    TEXT    DEFAULT '[]',
            attempted_at    TEXT    DEFAULT (datetime('now')),
            FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
        )
    """)

    # ── Table 6: spaced_repetition ────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS spaced_repetition (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id           INTEGER NOT NULL,
            topic             TEXT    NOT NULL,
            first_studied     TEXT    DEFAULT '',
            last_reviewed     TEXT    DEFAULT '',
            next_review_date  TEXT    DEFAULT '',
            review_count      INTEGER DEFAULT 0,
            ease_factor       REAL    DEFAULT 2.5,
            interval_days     INTEGER DEFAULT 1,
            last_score        REAL    DEFAULT 0.0,
            is_mastered       INTEGER DEFAULT 0,
            FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
        )
    """)

    conn.commit()
    conn.close()
    print("✅ Database initialized successfully")


# ─────────────────────────────────────────────────────────────────────────────
# CHAT OPERATIONS
# ─────────────────────────────────────────────────────────────────────────────
def create_chat(name: str, pdf_name: str = "") -> int:
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO chats (name, pdf_name) VALUES (?, ?)",
        (name, pdf_name)
    )
    chat_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return chat_id


def get_all_chats() -> list:
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, pdf_name, created_at, updated_at
        FROM   chats ORDER BY updated_at DESC
    """)
    chats = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return chats


def get_chat(chat_id: int) -> Optional[dict]:
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM chats WHERE id = ?", (chat_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def rename_chat(chat_id: int, new_name: str):
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE chats SET name=?, updated_at=datetime('now') WHERE id=?",
        (new_name, chat_id)
    )
    conn.commit()
    conn.close()


def delete_chat(chat_id: int):
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# AGENT OUTPUTS (summary — one row per chat)
# ─────────────────────────────────────────────────────────────────────────────
def save_agent_outputs(chat_id: int, topics: list,
                       web_output: str, notes_output: str,
                       final_output: str):
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM agent_outputs WHERE chat_id=?", (chat_id,)
    )
    if cursor.fetchone():
        cursor.execute("""
            UPDATE agent_outputs
            SET topics=?, web_output=?, notes_output=?, final_output=?
            WHERE chat_id=?
        """, (json.dumps(topics), web_output, notes_output, final_output, chat_id))
    else:
        cursor.execute("""
            INSERT INTO agent_outputs
                   (chat_id, topics, web_output, notes_output, final_output)
            VALUES (?, ?, ?, ?, ?)
        """, (chat_id, json.dumps(topics), web_output, notes_output, final_output))
    conn.commit()
    conn.close()


def get_agent_outputs(chat_id: int) -> Optional[dict]:
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM agent_outputs WHERE chat_id=?", (chat_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        result = dict(row)
        result["topics"] = json.loads(result["topics"]) if result["topics"] else []
        return result
    return None


# ─────────────────────────────────────────────────────────────────────────────
# TOPIC OUTPUTS (NEW — one row per topic for lazy loading)
# ─────────────────────────────────────────────────────────────────────────────
def create_topic_entry(chat_id: int, topic: str):
    """
    Create a pending entry for a topic
    Called by Agent 1 after extracting all topics
    Status starts as 'pending'
    """
    conn   = get_connection()
    cursor = conn.cursor()
    # Only create if doesn't exist
    cursor.execute(
        "SELECT id FROM topic_outputs WHERE chat_id=? AND topic=?",
        (chat_id, topic)
    )
    if not cursor.fetchone():
        cursor.execute("""
            INSERT INTO topic_outputs (chat_id, topic, status)
            VALUES (?, ?, 'pending')
        """, (chat_id, topic))
        conn.commit()
    conn.close()


def update_topic_status(chat_id: int, topic: str, status: str,
                        error_msg: str = ""):
    """
    Update topic processing status
    status: 'pending' | 'processing' | 'done' | 'error'
    """
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE topic_outputs
        SET    status=?, error_msg=?, updated_at=datetime('now')
        WHERE  chat_id=? AND topic=?
    """, (status, error_msg, chat_id, topic))
    conn.commit()
    conn.close()


def save_topic_output(chat_id: int, topic: str,
                      web_output: str, notes_output: str,
                      final_output: str):
    """
    Save completed outputs for a single topic
    Sets status to 'done'
    """
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE topic_outputs
        SET    web_output=?, notes_output=?, final_output=?,
               status='done', updated_at=datetime('now')
        WHERE  chat_id=? AND topic=?
    """, (web_output, notes_output, final_output, chat_id, topic))
    conn.commit()
    conn.close()


def get_topic_output(chat_id: int, topic: str) -> Optional[dict]:
    """Get output for a single topic"""
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM topic_outputs
        WHERE chat_id=? AND topic=?
    """, (chat_id, topic))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_topic_outputs(chat_id: int) -> list:
    """
    Get all topic outputs for a chat
    Returns list ordered by created_at
    Used by app.py to show all topics with their status
    """
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT topic, web_output, notes_output, final_output,
               status, error_msg, updated_at
        FROM   topic_outputs
        WHERE  chat_id=?
        ORDER  BY created_at ASC
    """, (chat_id,))
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def get_topic_statuses(chat_id: int) -> dict:
    """
    Get just the status of each topic (fast — no content)
    Used by app.py to check progress without loading full content
    Returns: {topic_name: status_string}
    """
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT topic, status FROM topic_outputs WHERE chat_id=?
    """, (chat_id,))
    statuses = {row["topic"]: row["status"] for row in cursor.fetchall()}
    conn.close()
    return statuses


def get_pending_topics(chat_id: int) -> list:
    """Get topics that haven't been processed yet"""
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT topic FROM topic_outputs
        WHERE chat_id=? AND status='pending'
        ORDER BY created_at ASC
    """, (chat_id,))
    topics = [row["topic"] for row in cursor.fetchall()]
    conn.close()
    return topics


def get_done_topics(chat_id: int) -> list:
    """Get topics that are fully processed"""
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT topic FROM topic_outputs
        WHERE chat_id=? AND status='done'
        ORDER BY created_at ASC
    """, (chat_id,))
    topics = [row["topic"] for row in cursor.fetchall()]
    conn.close()
    return topics


def topics_initialized(chat_id: int) -> bool:
    """Check if Agent 1 has run and created topic entries"""
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) as cnt FROM topic_outputs WHERE chat_id=?",
        (chat_id,)
    )
    count = cursor.fetchone()["cnt"]
    conn.close()
    return count > 0


# ─────────────────────────────────────────────────────────────────────────────
# MESSAGES
# ─────────────────────────────────────────────────────────────────────────────
def save_message(chat_id: int, role: str, content: str):
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO messages (chat_id, role, content) VALUES (?, ?, ?)",
        (chat_id, role, content)
    )
    cursor.execute(
        "UPDATE chats SET updated_at=datetime('now') WHERE id=?",
        (chat_id,)
    )
    conn.commit()
    conn.close()


def get_messages(chat_id: int, limit: int = 20) -> list:
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT role, content, timestamp FROM messages
        WHERE chat_id=? ORDER BY timestamp DESC LIMIT ?
    """, (chat_id, limit))
    messages = [dict(row) for row in cursor.fetchall()][::-1]
    conn.close()
    return messages


def clear_messages(chat_id: int):
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM messages WHERE chat_id=?", (chat_id,))
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# QUIZ SCORES
# ─────────────────────────────────────────────────────────────────────────────
def save_quiz_score(chat_id: int, topic: str, score: int,
                    total_questions: int, wrong_topics: list):
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO quiz_scores
               (chat_id, topic, score, total_questions, wrong_topics)
        VALUES (?, ?, ?, ?, ?)
    """, (chat_id, topic, score, total_questions, json.dumps(wrong_topics)))
    conn.commit()
    conn.close()


def get_quiz_scores(chat_id: int) -> list:
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT topic, score, total_questions, wrong_topics, attempted_at
        FROM quiz_scores WHERE chat_id=? ORDER BY attempted_at DESC
    """, (chat_id,))
    scores = []
    for row in cursor.fetchall():
        r = dict(row)
        r["wrong_topics"] = json.loads(r["wrong_topics"]) if r["wrong_topics"] else []
        scores.append(r)
    conn.close()
    return scores


def get_latest_quiz_score(chat_id: int, topic: str) -> Optional[dict]:
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT score, total_questions, wrong_topics, attempted_at
        FROM quiz_scores WHERE chat_id=? AND topic=?
        ORDER BY attempted_at DESC LIMIT 1
    """, (chat_id, topic))
    row = cursor.fetchone()
    conn.close()
    if row:
        r = dict(row)
        r["wrong_topics"] = json.loads(r["wrong_topics"]) if r["wrong_topics"] else []
        return r
    return None


# ─────────────────────────────────────────────────────────────────────────────
# SPACED REPETITION
# ─────────────────────────────────────────────────────────────────────────────
def create_spaced_repetition_entry(chat_id: int, topic: str):
    conn     = get_connection()
    cursor   = conn.cursor()
    today    = date.today().isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    cursor.execute(
        "SELECT id FROM spaced_repetition WHERE chat_id=? AND topic=?",
        (chat_id, topic)
    )
    if not cursor.fetchone():
        cursor.execute("""
            INSERT INTO spaced_repetition
                   (chat_id, topic, first_studied, last_reviewed,
                    next_review_date, review_count, ease_factor,
                    interval_days, last_score, is_mastered)
            VALUES (?, ?, ?, ?, ?, 0, 2.5, 1, 0.0, 0)
        """, (chat_id, topic, today, today, tomorrow))
        conn.commit()
    conn.close()


def update_spaced_repetition(chat_id: int, topic: str,
                              score_ratio: float):
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT ease_factor, interval_days, review_count
        FROM spaced_repetition WHERE chat_id=? AND topic=?
    """, (chat_id, topic))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return
    ease_factor  = row["ease_factor"]
    interval     = row["interval_days"]
    review_count = row["review_count"]

    if score_ratio >= 0.8:
        if review_count == 0:   interval = 1
        elif review_count == 1: interval = 3
        else:                   interval = round(interval * ease_factor)
        ease_factor = min(ease_factor + 0.1, 3.0)
    elif score_ratio >= 0.6:
        interval = round(interval * 1.2)
    else:
        interval    = 1
        ease_factor = max(ease_factor - 0.2, 1.3)

    next_review = (date.today() + timedelta(days=interval)).isoformat()
    today       = date.today().isoformat()
    is_mastered = 1 if (review_count >= 4 and score_ratio >= 0.8) else 0

    cursor.execute("""
        UPDATE spaced_repetition
        SET ease_factor=?, interval_days=?, next_review_date=?,
            last_reviewed=?, last_score=?,
            review_count=review_count+1, is_mastered=?
        WHERE chat_id=? AND topic=?
    """, (ease_factor, interval, next_review, today,
          score_ratio, is_mastered, chat_id, topic))
    conn.commit()
    conn.close()


def get_due_reviews() -> list:
    conn   = get_connection()
    cursor = conn.cursor()
    today  = date.today().isoformat()
    cursor.execute("""
        SELECT sr.chat_id, sr.topic, sr.next_review_date,
               sr.last_score, sr.review_count, sr.is_mastered,
               c.name AS chat_name
        FROM   spaced_repetition sr
        JOIN   chats c ON sr.chat_id = c.id
        WHERE  sr.next_review_date <= ? AND sr.is_mastered = 0
        ORDER  BY sr.next_review_date ASC
    """, (today,))
    reviews = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return reviews


def get_due_reviews_for_chat(chat_id: int) -> list:
    conn   = get_connection()
    cursor = conn.cursor()
    today  = date.today().isoformat()
    cursor.execute("""
        SELECT topic, next_review_date, last_score,
               review_count, interval_days, is_mastered
        FROM spaced_repetition
        WHERE chat_id=? AND next_review_date<=? AND is_mastered=0
        ORDER BY next_review_date ASC
    """, (chat_id, today))
    reviews = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return reviews


def get_all_topics_for_chat(chat_id: int) -> list:
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT topic, first_studied, last_reviewed, next_review_date,
               review_count, last_score, interval_days, is_mastered
        FROM spaced_repetition WHERE chat_id=? ORDER BY topic ASC
    """, (chat_id,))
    topics = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return topics


def get_upcoming_reviews(days_ahead: int = 7) -> list:
    conn   = get_connection()
    cursor = conn.cursor()
    today  = date.today().isoformat()
    future = (date.today() + timedelta(days=days_ahead)).isoformat()
    cursor.execute("""
        SELECT sr.topic, sr.next_review_date, sr.last_score,
               c.name AS chat_name, sr.chat_id
        FROM spaced_repetition sr
        JOIN chats c ON sr.chat_id = c.id
        WHERE sr.next_review_date > ? AND sr.next_review_date <= ?
          AND sr.is_mastered = 0
        ORDER BY sr.next_review_date ASC
    """, (today, future))
    upcoming = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return upcoming


def get_overall_stats() -> dict:
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) AS total FROM spaced_repetition")
    total_topics = cursor.fetchone()["total"]
    cursor.execute(
        "SELECT COUNT(*) AS total FROM spaced_repetition WHERE is_mastered=1"
    )
    mastered = cursor.fetchone()["total"]
    cursor.execute("SELECT COUNT(*) AS total FROM quiz_scores")
    total_quizzes = cursor.fetchone()["total"]
    cursor.execute("""
        SELECT AVG(CAST(score AS REAL)/NULLIF(total_questions,0)) AS avg
        FROM quiz_scores
    """)
    avg_row   = cursor.fetchone()["avg"]
    avg_score = round((avg_row or 0) * 100, 1)
    today = date.today().isoformat()
    cursor.execute("""
        SELECT COUNT(*) AS total FROM spaced_repetition
        WHERE next_review_date<=? AND is_mastered=0
    """, (today,))
    due_today = cursor.fetchone()["total"]
    cursor.execute("SELECT COUNT(*) AS total FROM chats")
    total_chats = cursor.fetchone()["total"]
    cursor.execute("SELECT COUNT(*) AS total FROM messages")
    total_messages = cursor.fetchone()["total"]
    conn.close()
    return {
        "total_topics"   : total_topics,
        "mastered"       : mastered,
        "total_quizzes"  : total_quizzes,
        "avg_score"      : avg_score,
        "due_today"      : due_today,
        "total_chats"    : total_chats,
        "total_messages" : total_messages
    }


# ─────────────────────────────────────────────────────────────────────────────
# TEST
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(" Testing database.py...")
    init_database()

    chat_id = create_chat("Test Chat", "test.pdf")
    print(f" Created chat: {chat_id}")

    # Test topic outputs
    for t in ["Binary Search", "Recursion", "Stack"]:
        create_topic_entry(chat_id, t)

    print(f" Topics initialized: {topics_initialized(chat_id)}")
    print(f" Pending: {get_pending_topics(chat_id)}")

    update_topic_status(chat_id, "Binary Search", "processing")
    save_topic_output(chat_id, "Binary Search",
                      "web output", "notes output", "final output")

    statuses = get_topic_statuses(chat_id)
    print(f" Statuses: {statuses}")

    done = get_done_topics(chat_id)
    print(f" Done topics: {done}")

    print("\n database.py tests passed!")
