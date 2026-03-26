# memory.py
# ─────────────────────────────────────────────────────────────────────────────
# This file manages CONVERSATION MEMORY for Agent 5 (Tutor)
#
# WHAT THIS FILE DOES:
# 1. Loads previous messages from SQLite for a chat
# 2. Builds a memory context string Agent 5 can read
# 3. Manages the conversation window (last N messages)
# 4. Combines PDF knowledge + conversation history + agent outputs
#    into one unified context for Agent 5
#
# LLM: Groq (free, fast, reliable) — using llama-3.1-8b-instant
# Embeddings: Gemini (only for FAISS search) — lazy loaded
# ─────────────────────────────────────────────────────────────────────────────

import os
import time
from typing import Optional
from dotenv import load_dotenv

# ── LangChain Groq ────────────────────────────────────────────────────────────
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

# ── Database functions ────────────────────────────────────────────────────────
from database import (
    get_messages,
    save_message,
    get_agent_outputs,
    get_quiz_scores,
    get_chat
)

load_dotenv()

# ── Groq LLM — free, fast, reliable ──────────────────────────────────────────
llm = ChatGroq(
    model="llama-3.1-8b-instant",
    temperature=0.7,
    api_key=os.getenv("GROQ_API_KEY"),

    streaming=True
)

# ── How many previous messages to include in memory ──────────────────────────
MEMORY_WINDOW = 20


# ─────────────────────────────────────────────────────────────────────────────
# SEARCH FAISS — lazy import to avoid SSL issues at module load
# ─────────────────────────────────────────────────────────────────────────────
def search_pdf_context(query: str, chat_id: int) -> str:
    """
    Search FAISS for relevant PDF chunks
    Lazy import prevents SSL initialization at module load time
    """
    try:
        from rag_engine import search_faiss
        chunks = search_faiss(query, chat_id, k=3)
        return "\n\n".join(chunks) if chunks else ""
    except Exception as e:
        print(f"   FAISS search failed: {e}")
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# BUILD SYSTEM PROMPT
# The "memory" and "knowledge" injected into every Agent 5 call
# ─────────────────────────────────────────────────────────────────────────────
def build_system_prompt(chat_id: int, current_question: str) -> str:
    """
    Build a rich system prompt for Agent 5 that includes:
    1. Role definition
    2. Topics from student's PDF
    3. What agents 1-4 already explained
    4. Student's weak points from quiz history
    5. Relevant PDF chunks for current question
    """

    # ── Get chat info ─────────────────────────────────────────────────────────
    chat      = get_chat(chat_id)
    chat_name = chat["name"]     if chat else "Study Session"
    pdf_name  = chat["pdf_name"] if chat else "uploaded PDF"

    # ── Get agent outputs ─────────────────────────────────────────────────────
    outputs      = get_agent_outputs(chat_id)
    topics_list  = outputs["topics"]       if outputs else []
    web_output   = outputs["web_output"]   if outputs else ""
    notes_output = outputs["notes_output"] if outputs else ""
    final_output = outputs["final_output"] if outputs else ""

    # ── Get weak topics from quiz history ─────────────────────────────────────
    quiz_scores = get_quiz_scores(chat_id)
    weak_topics = []
    for score in quiz_scores:
        ratio = score["score"] / max(score["total_questions"], 1)
        if ratio < 0.6:
            weak_topics.append(score["topic"])

    # ── Get relevant PDF chunks for current question ──────────────────────────
    pdf_context = search_pdf_context(current_question, chat_id)

    # ── Build system prompt ───────────────────────────────────────────────────
    system = f"""You are an expert CS tutor helping a student understand topics from their study material.

## YOUR IDENTITY
- Name: Study Tutor AI
- Role: Personal CS tutor who has analyzed the student's PDF
- Style: Clear, simple, friendly but professional
- Always use examples, analogies, and step-by-step explanations
- For CS topics, always include Python code examples when relevant

## STUDENT'S STUDY SESSION
- Chat: {chat_name}
- PDF: {pdf_name}
- Topics covered: {", ".join(topics_list) if topics_list else "Not yet analyzed"}

## WHAT HAS ALREADY BEEN EXPLAINED
Use these as your knowledge base for follow-up questions:

### Web Explanations (GeeksForGeeks etc.):
{web_output[:1500] if web_output else "Not yet generated"}

### Notes-Based Explanations (from student PDF):
{notes_output[:1500] if notes_output else "Not yet generated"}

### Final Combined Explanation:
{final_output[:1500] if final_output else "Not yet generated"}

## STUDENT'S WEAK AREAS
{"Student struggled with: " + ", ".join(weak_topics) if weak_topics else "No quiz data yet"}
{"Be extra thorough explaining these topics." if weak_topics else ""}

## RELEVANT PDF CONTENT FOR CURRENT QUESTION
{pdf_context if pdf_context else "No specific PDF context found"}

## YOUR RULES
1. Answer based on the context above
2. If topic is NOT in PDF, say so but still help
3. Use simple language — student is learning this
4. Always provide Python code examples for CS topics
5. Remember entire conversation — refer back when relevant
6. If student got quiz question wrong, be extra thorough
7. Keep responses well structured with clear sections
"""
    return system


# ─────────────────────────────────────────────────────────────────────────────
# BUILD CONVERSATION HISTORY
# Converts SQLite messages into LangChain message objects
# ─────────────────────────────────────────────────────────────────────────────
def build_conversation_history(chat_id: int) -> list:
    """
    Load last N messages from SQLite and convert to LangChain format
    Returns list of HumanMessage/AIMessage objects
    """
    messages    = get_messages(chat_id, limit=MEMORY_WINDOW)
    lc_messages = []

    for msg in messages:
        role    = msg["role"]
        content = msg["content"]
        if role == "user":
            lc_messages.append(HumanMessage(content=content))
        elif role == "assistant":
            lc_messages.append(AIMessage(content=content))

    return lc_messages


# ─────────────────────────────────────────────────────────────────────────────
# STREAM RESPONSE — like ChatGPT word by word
# ─────────────────────────────────────────────────────────────────────────────
def stream_tutor_response(chat_id: int, user_question: str):
    """
    Generate streaming response from Agent 5
    This is a GENERATOR — yields chunks one by one
    Streamlit uses st.write_stream() to display live

    Usage in Streamlit:
        response = st.write_stream(
            stream_tutor_response(chat_id, question)
        )
    """

    # Build full context
    system_prompt = build_system_prompt(chat_id, user_question)
    history       = build_conversation_history(chat_id)

    # Build message list:
    # [SystemMessage, ...history..., HumanMessage(current question)]
    messages = (
        [SystemMessage(content=system_prompt)]
        + history
        + [HumanMessage(content=user_question)]
    )

    # Stream response chunk by chunk
    full_response = ""
    try:
        for chunk in llm.stream(messages):
            if chunk.content:
                full_response += chunk.content
                yield chunk.content    # Streamlit displays each chunk live

    except Exception as e:
        error_msg = f"Sorry, I encountered an error: {str(e)}. Please try again."
        yield error_msg
        full_response = error_msg

    # Save full conversation to SQLite after streaming completes
    save_message(chat_id, "user",      user_question)
    save_message(chat_id, "assistant", full_response)


# ─────────────────────────────────────────────────────────────────────────────
# NON-STREAMING RESPONSE
# Used internally when full text is needed before displaying
# ─────────────────────────────────────────────────────────────────────────────
def get_tutor_response(chat_id: int, user_question: str) -> str:
    """Get complete response from Agent 5 (non-streaming)"""

    system_prompt = build_system_prompt(chat_id, user_question)
    history       = build_conversation_history(chat_id)

    messages = (
        [SystemMessage(content=system_prompt)]
        + history
        + [HumanMessage(content=user_question)]
    )

    # Retry up to 3 times for rate limits
    for attempt in range(3):
        try:
            response      = llm.invoke(messages)
            full_response = response.content

            # Save to SQLite
            save_message(chat_id, "user",      user_question)
            save_message(chat_id, "assistant", full_response)

            return full_response

        except Exception as e:
            error_str = str(e)
            if "429" in error_str and attempt < 2:
                wait = 30 * (attempt + 1)
                print(f"   Rate limited, waiting {wait}s...")
                time.sleep(wait)
            else:
                error = f"Error: {error_str}"
                print(f" {error}")
                return error

    return "Could not generate response after 3 attempts."


# ─────────────────────────────────────────────────────────────────────────────
# MEMORY SUMMARY
# Called when student asks "what have we covered so far?"
# ─────────────────────────────────────────────────────────────────────────────
def get_memory_summary(chat_id: int) -> str:
    """Generate a summary of the entire conversation"""
    messages = get_messages(chat_id, limit=50)

    if not messages:
        return "No conversation history yet for this chat."

    history_text = ""
    for msg in messages:
        role    = "Student" if msg["role"] == "user" else "Tutor"
        content = msg["content"][:200]
        history_text += f"{role}: {content}\n\n"

    summary_prompt = f"""Based on this conversation, provide a brief summary of:
1. Topics discussed
2. What student understood well
3. What student struggled with
4. Key concepts explained

Conversation:
{history_text}

Provide a concise 3-4 sentence summary."""

    try:
        response = llm.invoke([HumanMessage(content=summary_prompt)])
        return response.content
    except Exception as e:
        return f"Could not generate summary: {str(e)}"


# ─────────────────────────────────────────────────────────────────────────────
# UTILITY
# ─────────────────────────────────────────────────────────────────────────────
def chat_has_context(chat_id: int) -> bool:
    """Check if a chat has agent outputs available"""
    outputs = get_agent_outputs(chat_id)
    return outputs is not None and bool(outputs.get("topics"))


# ─────────────────────────────────────────────────────────────────────────────
# QUICK TEST — python memory.py
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    from database import init_database, create_chat, save_agent_outputs, save_message as sm

    print(" Testing memory.py...")

    init_database()
    chat_id = create_chat("Memory Test", "test.pdf")

    save_agent_outputs(
        chat_id,
        topics       = ["Binary Search", "Recursion"],
        web_output   = "Binary Search: efficient search algorithm...",
        notes_output = "From PDF: binary search divides array...",
        final_output = "Combined: Binary Search works by..."
    )
    print(f" Created test chat: {chat_id}")

    # Test system prompt
    prompt = build_system_prompt(chat_id, "explain binary search")
    print(f" System prompt: {len(prompt)} chars")
    print(f"   Preview: {prompt[:200]}...")

    # Test history
    sm(chat_id, "user",      "what is binary search?")
    sm(chat_id, "assistant", "Binary search is an algorithm...")
    sm(chat_id, "user",      "give me an example")

    history = build_conversation_history(chat_id)
    print(f" History loaded: {len(history)} messages")

    # Test non-streaming
    print("\n Testing non-streaming response...")
    response = get_tutor_response(chat_id, "what is recursion in simple terms?")
    print(f" Response: {len(response)} chars")
    print(f"   Preview: {response[:300]}...")

    # Test streaming
    print("\n Testing streaming response...")
    print("Agent 5: ", end="", flush=True)
    for chunk in stream_tutor_response(chat_id, "give me a one line example of recursion"):
        print(chunk, end="", flush=True)
    print()

    # Test summary
    print("\n Testing memory summary...")
    summary = get_memory_summary(chat_id)
    print(f" Summary: {summary[:200]}...")

    print("\n memory.py tests complete!")
