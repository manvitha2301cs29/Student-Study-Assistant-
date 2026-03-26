# app.py


import streamlit as st
import io
import time
from datetime import datetime

from database import (
    init_database, create_chat, get_all_chats,
    get_chat, rename_chat, delete_chat,
    get_messages, topics_initialized,
    get_all_topic_outputs, get_topic_statuses,
    get_agent_outputs,
)
from graph             import (
    initialize_chat, process_next_topic,
    has_pending_topics, get_progress, finalize_chat,
)
from rag_engine        import process_pdfs_for_chat, faiss_exists
from memory            import stream_tutor_response
from spaced_repetition import (
    get_topics_due_for_chat, get_due_count, get_dashboard_data,
)
from review_session    import generate_review_quiz, complete_review_session

# ─────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title = "🎓 Study Assistant",
    page_icon  = "🎓",
    layout     = "wide",
)

init_database()

# Session state defaults
for key, default in [
    ("current_chat_id", None),
    ("current_page",    "chat"),
    ("review_topic",    None),
]:
    if key not in st.session_state:
        st.session_state[key] = default


# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("🎓 Study Assistant")

    due_count = get_due_count()
    if due_count > 0:
        st.error(f"🔔 {due_count} review(s) due!")
        if st.button("📚 Review Now", use_container_width=True, type="primary"):
            st.session_state.current_page = "review"
            st.rerun()
    else:
        st.success("✅ No reviews due!")

    st.divider()

    c1, c2 = st.columns(2)
    with c1:
        if st.button("💬 Chat", use_container_width=True):
            st.session_state.current_page = "chat"
            st.rerun()
    with c2:
        if st.button("📊 Progress", use_container_width=True):
            st.session_state.current_page = "dashboard"
            st.rerun()

    st.divider()

    if st.button("➕ New Chat", use_container_width=True):
        st.session_state.current_chat_id = None
        st.session_state.current_page    = "chat"
        st.rerun()

    st.markdown("**Recent Chats**")
    chats = get_all_chats()

    if not chats:
        st.caption("No chats yet — upload a PDF!")
    else:
        for chat in chats:
            chat_id   = chat["id"]
            chat_name = chat["name"]
            is_active = chat_id == st.session_state.current_chat_id

            # Show progress badge or due reviews
            if topics_initialized(chat_id) and has_pending_topics(chat_id):
                prog  = get_progress(chat_id)
                badge = f" ⏳{prog['done']}/{prog['total']}"
            else:
                due   = get_topics_due_for_chat(chat_id)
                badge = f" 🔔{len(due)}" if due else ""

            btn_type = "primary" if is_active else "secondary"
            if st.button(
                f"{'▶ ' if is_active else ''}{chat_name[:22]}{badge}",
                key  = f"chat_{chat_id}",
                use_container_width = True,
                type = btn_type
            ):
                st.session_state.current_chat_id = chat_id
                st.session_state.current_page    = "chat"
                st.rerun()

            if is_active:
                ca, cb = st.columns(2)
                with ca:
                    if st.button("✏️", key=f"ren_{chat_id}"):
                        st.session_state[f"renaming_{chat_id}"] = True
                with cb:
                    if st.button("🗑️", key=f"del_{chat_id}"):
                        delete_chat(chat_id)
                        st.session_state.current_chat_id = None
                        st.rerun()

                if st.session_state.get(f"renaming_{chat_id}"):
                    new_name = st.text_input(
                        "New name:", value=chat_name, key=f"ri_{chat_id}"
                    )
                    if st.button("Save", key=f"rs_{chat_id}"):
                        rename_chat(chat_id, new_name)
                        st.session_state[f"renaming_{chat_id}"] = False
                        st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# PAGE: CHAT
# ─────────────────────────────────────────────────────────────────────────────
def show_chat_page():
    chat_id = st.session_state.current_chat_id

    # ── Welcome screen ────────────────────────────────────────────────────────
    if chat_id is None:
        st.title("🎓 Student Study Assistant")
        st.markdown("""
Welcome! Upload your lecture notes or textbook PDF to get started.

**How it works:**
| Agent | What it does | Speed |
|---|---|---|
|  Agent 1 | Finds ALL topics in your PDF |  |
|  Agent 2 | Web explanation per topic |  |
|  Agent 3 | Notes explanation per topic | |
|  Agent 4 | Study guide + quiz per topic |  |
|  Agent 5 | Answers follow-up questions |  |

Topics load **one by one** 
        """)

        st.divider()
        uploaded = st.file_uploader(
            "📄 Upload your PDF(s)",
            type                  = ["pdf"],
            accept_multiple_files = True
        )
        chat_name = st.text_input(
            "Chat name (optional):",
            placeholder = "e.g. Cybersecurity Day 3"
        )

        if st.button(" Start Studying", type="primary", disabled=not uploaded):
            name = chat_name.strip() or (
                f"{uploaded[0].name.replace('.pdf', '')} — "
                f"{datetime.now().strftime('%b %d')}"
            )
            pdf_names   = ", ".join(f.name for f in uploaded)
            new_chat_id = create_chat(name, pdf_names)
            st.session_state.current_chat_id = new_chat_id

            with st.spinner(" Reading your PDF..."):
                pdf_files = []
                for f in uploaded:
                    b      = io.BytesIO(f.read())
                    b.name = f.name
                    pdf_files.append(b)
                process_pdfs_for_chat(pdf_files, new_chat_id)

            st.rerun()
        return

    # ── Load chat ─────────────────────────────────────────────────────────────
    chat = get_chat(chat_id)
    if not chat:
        st.error("Chat not found")
        return

    st.title(f"💬 {chat['name']}")
    st.caption(f"📄 {chat['pdf_name']}")

    # ── Step 1: Run Agent 1 (once, fast) ─────────────────────────────────────
    if not topics_initialized(chat_id):
        if not faiss_exists(chat_id):
            st.error("PDF not processed. Please create a new chat.")
            return
        with st.spinner(" Agent 1: Finding all topics in your PDF ..."):
            result = initialize_chat(chat_id)
        if result["success"]:
            st.success(f"✅ Found {len(result['topics'])} topics! Loading explanations...")
            time.sleep(1)
            st.rerun()
        else:
            st.error(f"Failed: {result.get('error', 'Unknown error')}")
        return

    # ── Get all topic outputs ─────────────────────────────────────────────────
    topic_outputs = get_all_topic_outputs(chat_id)
    progress      = get_progress(chat_id)

    done_topics    = [t for t in topic_outputs if t["status"] == "done"]
    pending_topics = [t for t in topic_outputs
                      if t["status"] in ("pending", "processing")]

    # ─────────────────────────────────────────────────────────────────────────
    # SHOW PROGRESS BAR
    # ─────────────────────────────────────────────────────────────────────────
    if not progress["complete"]:
        pct = progress["pct"] / 100
        st.progress(pct)
        st.caption(
            f" **{progress['done']}/{progress['total']}** topics ready "
            f"({progress['pct']}%) — Read ready topics below while others load!"
        )
    else:
        st.success(f" All {progress['total']} topics are ready!")

    # ── Due reviews alert ─────────────────────────────────────────────────────
    due = get_topics_due_for_chat(chat_id)
    if due:
        col_a, col_b = st.columns([4, 1])
        col_a.warning(f" {len(due)} topic(s) due for review!")
        if col_b.button("Review Now"):
            st.session_state.review_topic = due[0]["topic"]
            st.session_state.current_page = "review"
            st.rerun()

    st.divider()

    # ─────────────────────────────────────────────────────────────────────────
    # MAIN TABS — shown ALWAYS, even while processing
    # ─────────────────────────────────────────────────────────────────────────
    tab1, tab2 = st.tabs([" Topics & Explanations", "💬 Chat with Tutor"])

    # ── Tab 1: Topics ─────────────────────────────────────────────────────────
    with tab1:
        # ── DONE topics — fully expandable with content ───────────────────────
        if done_topics:
            st.subheader(f"✅ Ready to Read ({len(done_topics)} topics)")
            st.caption("Click any topic to expand its explanation")

            for t in done_topics:
                topic = t["topic"]
                with st.expander(f"✅  {topic}", expanded=False):

                    # 3 sub-tabs per topic
                    s1, s2, s3 = st.tabs([
                        "🌐 Web Explanation",
                        "📝 From Your Notes",
                        "🎓 Study Guide + Quiz"
                    ])

                    with s1:
                        web = t.get("web_output", "")
                        if web.strip():
                            st.markdown(web)
                        else:
                            st.info("No web content for this topic")

                    with s2:
                        notes = t.get("notes_output", "")
                        if notes.strip():
                            st.markdown(notes)
                        else:
                            st.info("No notes content for this topic")

                    with s3:
                        final = t.get("final_output", "")
                        if final.strip():
                            st.markdown(final)
                        else:
                            st.info("No study guide yet")

        # ── PENDING topics — show as coming soon ──────────────────────────────
        if pending_topics:
            st.subheader(f" Loading ({len(pending_topics)} remaining)")

            for t in pending_topics:
                status = t["status"]
                if status == "processing":
                    st.markdown(f" **{t['topic']}** — Processing now...")
                else:
                    st.markdown(f" **{t['topic']}** — Queued")

        # ── Nothing ready yet ─────────────────────────────────────────────────
        if not done_topics and not pending_topics:
            st.info("Topics are being extracted... please wait a moment.")

    # ── Tab 2: Chat ───────────────────────────────────────────────────────────
    with tab2:
        st.subheader("💬 Chat with Your AI Tutor")
        st.caption(
            "Ask anything about your notes — "
            "Agent 5 remembers your full conversation"
        )

        # Show message history
        messages = get_messages(chat_id, limit=50)
        for msg in messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        # Chat input — always available even while topics are loading
        if prompt := st.chat_input("Ask anything about your notes..."):
            with st.chat_message("user"):
                st.markdown(prompt)
            with st.chat_message("assistant"):
                st.write_stream(stream_tutor_response(chat_id, prompt))

    # ─────────────────────────────────────────────────────────────────────────
    # AUTO-PROCESS NEXT TOPIC
    # Runs AFTER showing content so student can see what's ready
    # 3 second pause gives student time to read before next rerun
    # ─────────────────────────────────────────────────────────────────────────
    if has_pending_topics(chat_id):
        time.sleep(3)                          # pause so student can read
        result = process_next_topic(chat_id)   # process one topic
        if not has_pending_topics(chat_id):
            finalize_chat(chat_id)             # save combined summary
        st.rerun()                             # refresh to show new topic


# ─────────────────────────────────────────────────────────────────────────────
# PAGE: DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────
def show_dashboard_page():
    st.title("📊 Learning Progress Dashboard")

    chat_id = st.session_state.current_chat_id
    data    = get_dashboard_data(chat_id)
    stats   = data["stats"]

    # ── Top metrics ───────────────────────────────────────────────────────────
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("📚 Topics Studied",  stats["total_topics"])
    c2.metric("🏆 Mastered",        stats["mastered"])
    c3.metric("📝 Quizzes Taken",   stats["total_quizzes"])
    c4.metric("📈 Avg Score",       f"{stats['avg_score']}%")
    c5.metric("🔔 Due Today",       stats["due_today"])

    st.divider()
    col1, col2 = st.columns(2)

    # ── Due today ─────────────────────────────────────────────────────────────
    with col1:
        st.subheader("🔔 Due for Review Today")
        due = data["due_today"]
        if not due:
            st.success("All caught up! No reviews due 🎉")
        else:
            for item in due:
                ca, cb = st.columns([3, 1])
                ca.markdown(
                    f"**{item['topic']}** — _{item.get('chat_name', '')}_"
                )
                if cb.button("Review", key=f"rb_{item['topic']}"):
                    st.session_state.review_topic = item["topic"]
                    st.session_state.current_page = "review"
                    st.rerun()

    # ── Upcoming ──────────────────────────────────────────────────────────────
    with col2:
        st.subheader("📅 Upcoming Reviews (7 days)")
        upcoming = data["upcoming"]
        if not upcoming:
            st.info("No upcoming reviews scheduled")
        else:
            for item in upcoming[:8]:
                st.markdown(
                    f"**{item['topic']}** — "
                    f"_{item['next_review_date']}_ "
                    f"({item.get('chat_name', '')})"
                )

    # ── Per-chat progress ─────────────────────────────────────────────────────
    if chat_id and data["chat_topics"]:
        st.divider()
        st.subheader("📚 Topics in Current Chat")
        mastered   = data["mastered"]
        needs_work = data["needs_work"]
        if mastered:
            st.markdown(
                "**✅ Mastered:** " +
                ", ".join(t["topic"] for t in mastered)
            )
        if needs_work:
            st.markdown("**⚠️ Needs Attention:**")
            for t in needs_work:
                pct = round(t.get("last_score", 0) * 100)
                st.markdown(f"- {t['topic']} (last score: {pct}%)")


# ─────────────────────────────────────────────────────────────────────────────
# PAGE: REVIEW SESSION
# ─────────────────────────────────────────────────────────────────────────────
def show_review_page():
    st.title("🔄 Review Session")

    chat_id = st.session_state.current_chat_id
    if not chat_id:
        from database import get_due_reviews
        due = get_due_reviews()
        if due:
            chat_id = due[0]["chat_id"]
        else:
            st.info("No topics due for review!")
            return

    # ── Topic selector ────────────────────────────────────────────────────────
    due_topics = get_topics_due_for_chat(chat_id)
    if not due_topics and not st.session_state.review_topic:
        st.success("🎉 No topics due for review in this chat!")
        if st.button("← Back to Chat"):
            st.session_state.current_page = "chat"
            st.rerun()
        return

    topic_options = [d["topic"] for d in due_topics]
    if (st.session_state.review_topic and
            st.session_state.review_topic not in topic_options):
        topic_options.insert(0, st.session_state.review_topic)

    selected = st.selectbox("Select topic to review:", options=topic_options)
    st.divider()

    # ── Generate quiz ─────────────────────────────────────────────────────────
    quiz_key = f"quiz_{chat_id}_{selected}"
    if quiz_key not in st.session_state:
        with st.spinner(f"Generating quiz for: {selected}..."):
            st.session_state[quiz_key] = generate_review_quiz(chat_id, selected)

    quiz      = st.session_state[quiz_key]
    questions = quiz.get("questions", [])

    if not questions:
        st.error("Could not generate questions. Try again.")
        return

    st.subheader(f"📝 Quiz: {selected}")
    st.caption(f"{len(questions)} questions")

    # ── Show questions ────────────────────────────────────────────────────────
    ans_key = f"ans_{chat_id}_{selected}"
    if ans_key not in st.session_state:
        st.session_state[ans_key] = {}

    for q in questions:
        qid = str(q["id"])
        st.markdown(f"**Q{q['id']}: {q['question']}**")
        ans = st.text_area(
            "Your answer:",
            key         = f"ta_{chat_id}_{selected}_{qid}",
            height      = 80,
            placeholder = "Type your answer here..."
        )
        st.session_state[ans_key][qid] = ans
        st.markdown("---")

    # ── Submit ────────────────────────────────────────────────────────────────
    res_key = f"res_{chat_id}_{selected}"

    if st.button("✅ Submit Answers", type="primary"):
        with st.spinner("Evaluating your answers..."):
            result = complete_review_session(
                chat_id         = chat_id,
                topic           = selected,
                questions       = questions,
                student_answers = st.session_state[ans_key]
            )
        st.session_state[res_key] = result
        if quiz_key in st.session_state:
            del st.session_state[quiz_key]
        st.rerun()

    # ── Show results ──────────────────────────────────────────────────────────
    if res_key in st.session_state:
        r   = st.session_state[res_key]
        pct = r["score_pct"]

        if pct >= 80:
            st.success(f"🎉 Score: {r['score']}/{r['total']} ({pct}%)")
        elif pct >= 60:
            st.warning(f"👍 Score: {r['score']}/{r['total']} ({pct}%)")
        else:
            st.error(f"📚 Score: {r['score']}/{r['total']} ({pct}%)")

        st.info(r.get("sr_message", ""))

        st.subheader("📋 Detailed Feedback")
        for e in r.get("evaluations", []):
            icon = "✅" if e.get("is_correct") else "❌"
            with st.expander(
                f"{icon} Q{e['question_id']}: {e['question'][:60]}..."
            ):
                st.markdown(f"**Your answer:** {e.get('your_answer', '')}")
                st.markdown(f"**Correct answer:** {e.get('correct_answer', '')}")
                st.markdown(f"**Feedback:** {e.get('feedback', '')}")

        c1, c2 = st.columns(2)
        with c1:
            if st.button("🔄 Try Another Topic"):
                if res_key in st.session_state:
                    del st.session_state[res_key]
                st.rerun()
        with c2:
            if st.button("← Back to Chat"):
                st.session_state.current_page = "chat"
                st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# ROUTER
# ─────────────────────────────────────────────────────────────────────────────
page = st.session_state.current_page
if   page == "chat"      : show_chat_page()
elif page == "dashboard" : show_dashboard_page()
elif page == "review"    : show_review_page()
else                     : show_chat_page()
