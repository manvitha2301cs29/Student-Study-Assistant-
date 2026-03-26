# spaced_repetition.py
# ─────────────────────────────────────────────────────────────────────────────
# Implements the SM-2 Spaced Repetition Algorithm
#
# WHAT IS SPACED REPETITION?
# Based on Ebbinghaus Forgetting Curve — you forget 70% within 24 hours
# unless you review at scientifically optimal intervals
#
# HOW SM-2 WORKS:
# After each review, calculate next review date based on:
# - How well student remembered (score ratio)
# - Ease factor (how easy the topic is for this student)
# - Current interval (days since last review)
#
# INTERVALS:
# Review 1 → 1 day later
# Review 2 → 3 days later
# Review 3 → 7 days later  (adjusts based on score)
# Review 4 → 14 days later
# Review 5 → topic MASTERED ✅
# ─────────────────────────────────────────────────────────────────────────────

from datetime import date, timedelta
from database import (
    get_due_reviews,
    get_due_reviews_for_chat,
    get_all_topics_for_chat,
    update_spaced_repetition,
    create_spaced_repetition_entry,
    get_overall_stats,
    get_upcoming_reviews,
)


# ─────────────────────────────────────────────────────────────────────────────
# GET DUE TOPICS
# ─────────────────────────────────────────────────────────────────────────────
def get_topics_due_today() -> list:
    """
    Get all topics due for review today across ALL chats
    Used for sidebar notification badge
    """
    return get_due_reviews()


def get_topics_due_for_chat(chat_id: int) -> list:
    """
    Get topics due for review for a specific chat
    Used in chat view to show review button
    """
    return get_due_reviews_for_chat(chat_id)


def get_due_count() -> int:
    """Get total count of topics due today — for notification badge"""
    return len(get_due_reviews())


# ─────────────────────────────────────────────────────────────────────────────
# PROCESS QUIZ RESULT
# Updates SM-2 schedule after student completes a quiz
# ─────────────────────────────────────────────────────────────────────────────
def process_quiz_result(chat_id: int, topic: str,
                        score: int, total: int) -> dict:
    """
    Update spaced repetition schedule after a quiz

    score / total → score_ratio
    Calls SM-2 algorithm in database.py
    Returns next review info for display

    Returns:
        dict with next_review_date, interval, message
    """
    if total == 0:
        return {"message": "No questions answered"}

    score_ratio = score / total

    # Update SM-2 in database
    update_spaced_repetition(chat_id, topic, score_ratio)

    # Get updated entry to show student
    topics = get_all_topics_for_chat(chat_id)
    entry  = next((t for t in topics if t["topic"] == topic), None)

    if not entry:
        return {"message": "Review scheduled"}

    next_date    = entry.get("next_review_date", "")
    interval     = entry.get("interval_days", 1)
    is_mastered  = entry.get("is_mastered", 0)

    # Build friendly message
    if is_mastered:
        message = f"🏆 You've MASTERED {topic}! No more reviews needed."
    elif score_ratio >= 0.8:
        message = f"✅ Great job! Next review in {interval} days ({next_date})"
    elif score_ratio >= 0.6:
        message = f"👍 Good effort! Next review in {interval} days ({next_date})"
    else:
        message = f"📚 Keep studying! Review again tomorrow ({next_date})"

    return {
        "next_review_date" : next_date,
        "interval_days"    : interval,
        "is_mastered"      : bool(is_mastered),
        "score_ratio"      : score_ratio,
        "message"          : message
    }


# ─────────────────────────────────────────────────────────────────────────────
# DASHBOARD DATA
# ─────────────────────────────────────────────────────────────────────────────
def get_dashboard_data(chat_id: int = None) -> dict:
    """
    Get all data needed for the progress dashboard

    Returns comprehensive stats for display in app.py
    """
    # Overall stats across all chats
    stats = get_overall_stats()

    # Due today
    due_today = get_due_reviews()

    # Upcoming in next 7 days
    upcoming = get_upcoming_reviews(days_ahead=7)

    # Per-chat data if chat_id provided
    chat_topics = []
    if chat_id:
        chat_topics = get_all_topics_for_chat(chat_id)

    # Separate mastered vs in-progress
    mastered    = [t for t in chat_topics if t.get("is_mastered")]
    in_progress = [t for t in chat_topics if not t.get("is_mastered")]
    needs_work  = [t for t in chat_topics
                   if not t.get("is_mastered") and t.get("last_score", 1) < 0.6]

    return {
        "stats"       : stats,
        "due_today"   : due_today,
        "upcoming"    : upcoming,
        "chat_topics" : chat_topics,
        "mastered"    : mastered,
        "in_progress" : in_progress,
        "needs_work"  : needs_work,
    }


# ─────────────────────────────────────────────────────────────────────────────
# FORMAT DUE REVIEWS FOR DISPLAY
# ─────────────────────────────────────────────────────────────────────────────
def format_due_reviews(due_reviews: list) -> str:
    """Format due reviews as readable string for sidebar"""
    if not due_reviews:
        return "No reviews due today! 🎉"

    today = date.today().isoformat()
    lines = []
    for r in due_reviews:
        topic     = r["topic"]
        due_date  = r["next_review_date"]
        chat_name = r.get("chat_name", "")

        if due_date < today:
            status = "⚠️ OVERDUE"
        else:
            status = "📅 Due Today"

        lines.append(f"{status}: {topic} ({chat_name})")

    return "\n".join(lines)
