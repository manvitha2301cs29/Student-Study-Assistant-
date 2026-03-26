# tasks.py
# ─────────────────────────────────────────────────────────────────────────────
# Orchestrates agent tasks
#
# NEW: run_single_topic() — runs Agents 2,3,4 for ONE topic
# This is the core of lazy loading — called per topic
# ─────────────────────────────────────────────────────────────────────────────

import time
from agents import (
    run_pdf_reader,
    run_web_researcher,
    run_notes_analyst,
    run_synthesizer,
)
from rag_engine import get_all_chunks
from web_search import get_web_explanation
from database   import (
    create_topic_entry,
    update_topic_status,
    save_topic_output,
    create_spaced_repetition_entry,
    save_agent_outputs,
    get_topic_output,
)


# ─────────────────────────────────────────────────────────────────────────────
# TASK 1: Extract ALL topics (runs once, fast ~10s)
# ─────────────────────────────────────────────────────────────────────────────
def task_extract_topics(chat_id: int) -> dict:
    """
    Agent 1: Extract all topics from PDF
    Creates a 'pending' entry in topic_outputs for each topic
    Creates spaced repetition schedule for each topic
    """
    print("\n Task 1 — Extracting topics...")

    chunks = get_all_chunks(chat_id)
    if not chunks:
        return {"topics": [], "study_order": []}

    result = run_pdf_reader(chunks, chat_id)
    topics = result.get("topics", [])

    # Create pending entries for ALL topics
    for topic in topics:
        create_topic_entry(chat_id, topic)
        create_spaced_repetition_entry(chat_id, topic)

    print(f" Found {len(topics)} topics — all marked as pending")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# TASK 2-3-4: Process ONE topic (lazy loading core)
# ─────────────────────────────────────────────────────────────────────────────
def run_single_topic(chat_id: int, topic: str) -> dict:
    """
    Run Agents 2, 3, 4 for a SINGLE topic

    This is called one topic at a time for lazy loading
    Updates status in database as it progresses:
    pending → processing → done (or error)

    Returns dict with success status + outputs
    """
    print(f"\n⚡ Processing topic: '{topic}'")

    # Mark as processing
    update_topic_status(chat_id, topic, "processing")

    try:
        # ── Agent 2: Web search for this ONE topic ────────────────────────────
        print(f"  🌐 Web search for: {topic}")
        web_data       = get_web_explanation(topic)
        web_results    = {topic: web_data}
        web_output     = run_web_researcher([topic], web_results)

        # ── Agent 3: Notes analysis for this ONE topic ────────────────────────
        print(f"  📝 Notes analysis for: {topic}")
        notes_output   = run_notes_analyst([topic], chat_id)

        # ── Agent 4: Synthesize for this ONE topic ────────────────────────────
        print(f"   Synthesizing: {topic}")
        final_output   = run_synthesizer([topic], web_output, notes_output)

        # Save to database
        save_topic_output(chat_id, topic, web_output, notes_output, final_output)
        print(f"   '{topic}' done!")

        return {
            "topic"        : topic,
            "web_output"   : web_output,
            "notes_output" : notes_output,
            "final_output" : final_output,
            "success"      : True
        }

    except Exception as e:
        error_msg = str(e)
        print(f"   '{topic}' failed: {error_msg[:100]}")
        update_topic_status(chat_id, topic, "error", error_msg)
        return {
            "topic"   : topic,
            "success" : False,
            "error"   : error_msg
        }


# ─────────────────────────────────────────────────────────────────────────────
# SAVE COMBINED SUMMARY (called after all topics done)
# ─────────────────────────────────────────────────────────────────────────────
def save_combined_summary(chat_id: int, topics: list):
    """
    After all topics processed, combine into one summary
    Saves to agent_outputs table for backward compatibility
    """
    from database import get_all_topic_outputs

    all_outputs  = get_all_topic_outputs(chat_id)
    done_outputs = [o for o in all_outputs if o["status"] == "done"]

    combined_web   = "\n\n".join(o["web_output"]   for o in done_outputs)
    combined_notes = "\n\n".join(o["notes_output"] for o in done_outputs)
    combined_final = "\n\n".join(o["final_output"] for o in done_outputs)

    save_agent_outputs(
        chat_id      = chat_id,
        topics       = topics,
        web_output   = combined_web[:50000],    # limit size
        notes_output = combined_notes[:50000],
        final_output = combined_final[:100000]
    )
    print(f" Combined summary saved for {len(done_outputs)} topics")
