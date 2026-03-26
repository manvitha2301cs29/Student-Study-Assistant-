# graph.py
# ─────────────────────────────────────────────────────────────────────────────
# LangGraph orchestration with LAZY LOADING
#
# TWO GRAPHS:
# 1. init_graph  → runs Agent 1 only (fast ~10s)
#                  extracts all topics, creates pending entries
# 2. topic_graph → runs Agents 2,3,4 for ONE topic (~15-20s)
#                  called repeatedly for each topic
#
# LAZY LOADING FLOW:
# init_graph runs once → all topics shown as "pending"
# topic_graph runs per topic → each topic becomes "done" one by one
# app.py calls process_next_topic() in a loop with st.rerun()
# ─────────────────────────────────────────────────────────────────────────────

import os
import time
from typing import TypedDict, Optional
from dotenv import load_dotenv

load_dotenv()

# ── LangSmith ─────────────────────────────────────────────────────────────────
LANGSMITH_KEY = os.getenv("LANGCHAIN_API_KEY", "")
if LANGSMITH_KEY:
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"]    = LANGSMITH_KEY
    os.environ["LANGCHAIN_PROJECT"]    = "StudentStudyAssistant"
    os.environ["LANGCHAIN_ENDPOINT"]   = "https://api.smith.langchain.com"
    print(" LangSmith enabled")
else:
    os.environ["LANGCHAIN_TRACING_V2"] = "false"

from langgraph.graph import StateGraph, END
from tasks    import task_extract_topics, run_single_topic, save_combined_summary
from database import (
    get_pending_topics,
    get_done_topics,
    get_topic_statuses,
    topics_initialized,
    get_all_topic_outputs,
)


# ─────────────────────────────────────────────────────────────────────────────
# STATE DEFINITIONS
# ─────────────────────────────────────────────────────────────────────────────
class InitState(TypedDict):
    """State for the initialization graph (Agent 1)"""
    chat_id        : int
    topics         : list
    topic_metadata : dict
    error          : str
    success        : bool


class TopicState(TypedDict):
    """State for the single-topic graph (Agents 2,3,4)"""
    chat_id      : int
    topic        : str
    web_output   : str
    notes_output : str
    final_output : str
    error        : str
    success      : bool


# ─────────────────────────────────────────────────────────────────────────────
# INIT GRAPH — runs Agent 1 only
# ─────────────────────────────────────────────────────────────────────────────
def node_extract_topics(state: InitState) -> InitState:
    """Node: Extract all topics from PDF using Agent 1"""
    print("\n🔵 Init Node: Extracting topics...")
    try:
        result = task_extract_topics(state["chat_id"])
        state["topics"]         = result.get("topics", [])
        state["topic_metadata"] = result
        state["success"]        = True
        state["error"]          = ""
        print(f" Extracted {len(state['topics'])} topics")
    except Exception as e:
        print(f" Topic extraction failed: {e}")
        state["error"]   = str(e)
        state["success"] = False
        state["topics"]  = []
    return state


def build_init_graph():
    """Build the initialization graph (Agent 1 only)"""
    graph = StateGraph(InitState)
    graph.add_node("extract_topics", node_extract_topics)
    graph.set_entry_point("extract_topics")
    graph.add_edge("extract_topics", END)
    return graph.compile()


# ─────────────────────────────────────────────────────────────────────────────
# TOPIC GRAPH — runs Agents 2,3,4 for ONE topic
# ─────────────────────────────────────────────────────────────────────────────
def node_process_topic(state: TopicState) -> TopicState:
    """Node: Process one topic through Agents 2, 3, 4"""
    print(f"\n Topic Node: Processing '{state['topic']}'")
    try:
        result = run_single_topic(state["chat_id"], state["topic"])
        state["web_output"]   = result.get("web_output",   "")
        state["notes_output"] = result.get("notes_output", "")
        state["final_output"] = result.get("final_output", "")
        state["success"]      = result.get("success", False)
        state["error"]        = result.get("error", "")
    except Exception as e:
        print(f" Topic processing failed: {e}")
        state["error"]   = str(e)
        state["success"] = False
    return state


def build_topic_graph():
    """Build the per-topic graph (Agents 2,3,4)"""
    graph = StateGraph(TopicState)
    graph.add_node("process_topic", node_process_topic)
    graph.set_entry_point("process_topic")
    graph.add_edge("process_topic", END)
    return graph.compile()


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API — called by app.py
# ─────────────────────────────────────────────────────────────────────────────
def initialize_chat(chat_id: int) -> dict:
    """
    Step 1: Run Agent 1 to extract all topics
    Called ONCE when student first uploads PDF
    Returns list of all topics found

    After this call:
    - All topics exist in topic_outputs with status='pending'
    - Student can see all topic names immediately
    """
    print(f"\n Initializing chat {chat_id}...")

    # Already initialized? Return existing topics
    if topics_initialized(chat_id):
        statuses = get_topic_statuses(chat_id)
        topics   = list(statuses.keys())
        print(f"  ✅ Already initialized — {len(topics)} topics")
        return {"topics": topics, "success": True, "from_cache": True}

    # Run init graph
    pipeline = build_init_graph()
    initial: InitState = {
        "chat_id"        : chat_id,
        "topics"         : [],
        "topic_metadata" : {},
        "error"          : "",
        "success"        : False,
    }

    final_state = initial
    for update in pipeline.stream(initial):
        for node_name, node_state in update.items():
            final_state = node_state

    return {
        "topics"     : final_state.get("topics", []),
        "success"    : final_state.get("success", False),
        "error"      : final_state.get("error", ""),
        "from_cache" : False,
    }


def process_next_topic(chat_id: int) -> dict:
    """
    Step 2: Process the NEXT pending topic
    Called repeatedly by app.py — one call per topic
    Returns info about which topic was processed

    Flow in app.py:
        while has_pending_topics(chat_id):
            result = process_next_topic(chat_id)
            st.rerun()   ← triggers UI refresh
    """
    pending = get_pending_topics(chat_id)

    if not pending:
        print("   No pending topics")
        return {"done": True, "topic": None}

    # Take the first pending topic
    topic = pending[0]
    print(f"\n Processing next topic: '{topic}'")

    pipeline = build_topic_graph()
    initial: TopicState = {
        "chat_id"      : chat_id,
        "topic"        : topic,
        "web_output"   : "",
        "notes_output" : "",
        "final_output" : "",
        "error"        : "",
        "success"      : False,
    }

    final_state = initial
    for update in pipeline.stream(initial):
        for node_name, node_state in update.items():
            final_state = node_state

    return {
        "done"    : False,
        "topic"   : topic,
        "success" : final_state.get("success", False),
        "error"   : final_state.get("error", ""),
    }


def has_pending_topics(chat_id: int) -> bool:
    """Check if any topics still need processing"""
    return len(get_pending_topics(chat_id)) > 0


def get_progress(chat_id: int) -> dict:
    """
    Get current processing progress for a chat
    Used by app.py to show progress bar

    Returns:
        total, done, pending, processing, progress_pct
    """
    statuses   = get_topic_statuses(chat_id)
    total      = len(statuses)
    done       = sum(1 for s in statuses.values() if s == "done")
    pending    = sum(1 for s in statuses.values() if s == "pending")
    processing = sum(1 for s in statuses.values() if s == "processing")
    errors     = sum(1 for s in statuses.values() if s == "error")
    pct        = round(done / total * 100) if total > 0 else 0

    return {
        "total"      : total,
        "done"       : done,
        "pending"    : pending,
        "processing" : processing,
        "errors"     : errors,
        "pct"        : pct,
        "complete"   : done == total and total > 0,
    }


def finalize_chat(chat_id: int):
    """
    Called when all topics are done
    Saves combined summary to agent_outputs table
    """
    statuses = get_topic_statuses(chat_id)
    topics   = list(statuses.keys())
    save_combined_summary(chat_id, topics)
    print(f" Chat {chat_id} finalized")
