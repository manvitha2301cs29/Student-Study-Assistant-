# agents.py

# AGENT OVERVIEW:
# ┌─────────────────────────────────────────────────────────────┐
# │ Agent 1 — run_pdf_reader()     → extracts topics from PDF   │
# │ Agent 2 — run_web_researcher() → explains from web content  │
# │ Agent 3 — run_notes_analyst()  → explains from PDF notes    │
# │ Agent 4 — run_synthesizer()    → combines + quiz + code     │
# │ Agent 5 — in memory.py         → handles follow-up chat     │
# └─────────────────────────────────────────────────────────────┘
#
# Each agent is a function that:
# 1. Takes input (text/topics/content)
# 2. Builds a detailed prompt
# 3. Calls Groq LLM
# 4. Returns structured output


import os
import json
import time
from typing import List, Optional
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage

load_dotenv()

# ── Groq LLM ─────────────────────────────────────────────────────────────────
llm = ChatGroq(
    model       = "llama-3.1-8b-instant",
    temperature = 0.3,
    api_key     = os.getenv("GROQ_API_KEY"),
)


# ─────────────────────────────────────────────────────────────────────────────
# HELPER: Call LLM with retry logic
# ─────────────────────────────────────────────────────────────────────────────
def call_llm(system_prompt: str, user_prompt: str,
             max_retries: int = 3) -> str:
    """
    Call Groq LLM with automatic retry on rate limits
    Returns the response text as a string
    """
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt)
    ]

    for attempt in range(max_retries):
        try:
            response = llm.invoke(messages)
            return response.content

        except Exception as e:
            error_str = str(e)
            if "429" in error_str and attempt < max_retries - 1:
                wait = 30 * (attempt + 1)
                print(f"  ⏳ Rate limited, waiting {wait}s (attempt {attempt+1})...")
                time.sleep(wait)
            else:
                print(f"  ❌ LLM error: {error_str[:100]}")
                return f"Error: {error_str[:200]}"

    return "Error: Max retries exceeded"


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 1 — PDF READER
# ─────────────────────────────────────────────────────────────────────────────
def run_pdf_reader(chunks: List[str], chat_id: int) -> dict:
    """
    Agent 1: Reads all PDF chunks and extracts CS topics

    Input:  list of text chunks from the student's PDF
    Output: dict with:
            - topics: list of CS topic names
            - difficulty: dict mapping topic → difficulty level
            - prerequisites: dict mapping topic → prerequisites
            - knowledge_gaps: list of topics mentioned but not explained
            - study_order: recommended order to study topics

    HOW IT WORKS:
    We combine all chunks into one big text
    Then ask Groq to identify all CS topics in it
    Groq returns a structured JSON response
    We parse it and return the topics list
    """
    print("\n Agent 1 — PDF Reader starting...")

    # Combine all chunks into one text for analysis
    full_text = "\n\n".join(chunks)

    # Truncate if too long (Groq has token limits)
    if len(full_text) > 8000:
        full_text = full_text[:8000] + "\n...[truncated]"

    system_prompt = """You are an expert CS professor analyzing student notes.
Your job is to identify ALL computer science topics in the provided text.

You must respond with ONLY a valid JSON object — no other text, no markdown, no explanation.
The JSON must follow this exact structure:
{
  "topics": ["topic1", "topic2", "topic3"],
  "difficulty": {"topic1": "beginner", "topic2": "intermediate"},
  "prerequisites": {"topic2": ["topic1"]},
  "knowledge_gaps": ["topic mentioned but not explained"],
  "study_order": ["topic1", "topic2", "topic3"]
}

difficulty values: "beginner", "intermediate", "advanced"
If you find no CS topics, return: {"topics": [], "difficulty": {}, "prerequisites": {}, "knowledge_gaps": [], "study_order": []}"""

    user_prompt = f"""Analyze this student's PDF content and extract all CS topics:

{full_text}

Remember: respond with ONLY the JSON object, nothing else."""

    print("   Analyzing PDF content for topics...")
    response = call_llm(system_prompt, user_prompt)

    # Parse JSON response
    try:
        # Clean response — remove any markdown code blocks if present
        clean = response.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        clean = clean.strip()

        result = json.loads(clean)
        topics = result.get("topics", [])
        print(f"   Found {len(topics)} topics: {topics}")
        return result

    except json.JSONDecodeError as e:
        print(f"   JSON parse failed: {e}")
        print(f"  Raw response: {response[:200]}")

        # Fallback: extract topics manually from response
        topics = extract_topics_fallback(response, full_text)
        return {
            "topics"        : topics,
            "difficulty"    : {},
            "prerequisites" : {},
            "knowledge_gaps": [],
            "study_order"   : topics
        }


def extract_topics_fallback(llm_response: str, text: str) -> List[str]:
    """Fallback topic extraction if JSON parsing fails"""
    # Try to find anything that looks like a topic list in the response
    topics = []
    lines  = llm_response.split('\n')
    for line in lines:
        line = line.strip()
        if line.startswith('-') or line.startswith('•') or line.startswith('*'):
            topic = line.lstrip('-•* ').strip()
            if topic and len(topic) > 2:
                topics.append(topic)
    return topics if topics else ["General CS Concepts"]


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 2 — WEB RESEARCHER
# ─────────────────────────────────────────────────────────────────────────────
def run_web_researcher(topics: List[str],
                       web_results: dict) -> str:
    """
    Agent 2: Processes pre-fetched web content into clean explanations

    Input:  - topics: list of topic names
            - web_results: dict from web_search.py
              {topic: {content, source, url}}
    Output: formatted string with web explanation per topic

    HOW IT WORKS:
    web_search.py already fetched the raw web content
    This agent processes that content into clean explanations
    It extracts: definition, how it works, complexity, examples
    """
    print("\n Agent 2 — Web Researcher starting...")

    if not web_results:
        return "No web content available."

    all_explanations = []

    for topic in topics:
        print(f"   Processing web content for: {topic}")

        web_data = web_results.get(topic, {})
        content  = web_data.get("content", "")
        source   = web_data.get("source",  "web")
        url      = web_data.get("url",     "")

        if not content or not web_data.get("success"):
            all_explanations.append(
                f"## {topic}\nNo web content available for this topic.\n"
            )
            continue

        # Truncate content if too long
        if len(content) > 3000:
            content = content[:3000] + "...[truncated]"

        system_prompt = """You are a CS education specialist.
Extract a clear, structured explanation from the provided web content.
Format your response in Markdown with these exact sections:
### Definition
(1-2 sentence definition)
### How It Works
(step by step explanation)
### Example
(simple concrete example)
### Complexity
(time/space complexity if applicable, otherwise skip)
### Key Points
(3-5 bullet points of most important things to remember)

Be concise and student-friendly. Focus on what matters most."""

        user_prompt = f"""Topic: {topic}
Source: {source}
URL: {url}

Web Content:
{content}

Extract a clear explanation for a CS student."""

        explanation = call_llm(system_prompt, user_prompt)
        all_explanations.append(f"## {topic}\n**Source:** {source}\n\n{explanation}\n")

        # Small delay between topics
        time.sleep(0.5)

    result = "\n\n" + "─" * 50 + "\n\n".join(all_explanations)
    print(f"   Web explanations ready for {len(topics)} topics")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 3 — NOTES ANALYST
# ─────────────────────────────────────────────────────────────────────────────
def run_notes_analyst(topics: List[str], chat_id: int) -> str:
    """
    Agent 3: Explains topics using student's OWN PDF content

    Input:  - topics: list of topic names
            - chat_id: to search FAISS for relevant chunks
    Output: personalized notes-based explanation per topic

    HOW IT WORKS:
    For each topic, searches FAISS for relevant PDF chunks
    Then asks Groq to explain using ONLY that content
    Result feels personal — "your notes say..."
    """
    print("\n Agent 3 — Notes Analyst starting...")

    all_explanations = []

    for topic in topics:
        print(f"   Analyzing notes for: {topic}")

        # Search FAISS for relevant chunks (lazy import)
        try:
            from rag_engine import search_faiss
            chunks = search_faiss(topic, chat_id, k=3)
            notes_context = "\n\n".join(chunks) if chunks else ""
        except Exception as e:
            print(f"   FAISS search failed: {e}")
            notes_context = ""

        if not notes_context.strip():
            all_explanations.append(
                f"## {topic}\n"
                f"This topic was not found in your PDF notes.\n"
            )
            continue

        system_prompt = """You are a personal tutor explaining a student's own notes back to them.
Use ONLY the provided notes content — don't add external information.
Always refer to the notes directly: "Your notes explain...", "According to your PDF...", "Your professor described..."
Format in Markdown:
### What Your Notes Say
(explain the topic using their exact notes)
### Key Concepts from Your Notes
(bullet points of important concepts mentioned)
### Example from Your Notes
(any example or diagram mentioned in the notes)
### What to Remember
(most important takeaway from their notes)"""

        user_prompt = f"""Topic: {topic}

Student's PDF Notes:
{notes_context}

Explain this topic to the student using their own notes."""

        explanation = call_llm(system_prompt, user_prompt)
        all_explanations.append(f"## {topic}\n{explanation}\n")

        time.sleep(0.5)

    result = "\n\n" + "─" * 50 + "\n\n".join(all_explanations)
    print(f"   Notes explanations ready for {len(topics)} topics")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 4 — SYNTHESIZER
# ─────────────────────────────────────────────────────────────────────────────
def run_synthesizer(topics: List[str],
                    web_explanation: str,
                    notes_explanation: str) -> str:
    """
    Agent 4: Combines web + notes explanations into final output + quiz

    Input:  - topics: list of topic names
            - web_explanation: Agent 2 output
            - notes_explanation: Agent 3 output
    Output: per topic:
            - ELI5 simple explanation
            - Combined explanation
            - Python code example
            - Common mistakes
            - 3-5 quiz questions with answers

    This is the FINAL output the student sees
    """
    print("\n Agent 4 — Synthesizer starting...")

    all_output = []

    for topic in topics:
        print(f"   Synthesizing: {topic}")

        # Extract relevant section for this topic from agent outputs
        web_section   = extract_topic_section(web_explanation,   topic)
        notes_section = extract_topic_section(notes_explanation, topic)

        system_prompt = """You are the world's best CS teacher.
Combine the provided web explanation and notes explanation into one perfect study guide.
Format your response in Markdown with these EXACT sections:

###  Simple Explanation (ELI5)
(explain like the student is hearing this for the first time — use a real-life analogy)

###  Complete Explanation
(thorough explanation combining web + notes content)

###  Common Mistakes
(2-3 mistakes students commonly make with this topic)

###  Python Code Example
(working Python code demonstrating the concept with comments)

###  Quiz Questions
Q1: (question)
Answer: (answer)

Q2: (question)
Answer: (answer)

Q3: (question)
Answer: (answer)

Q4: (question)
Answer: (answer)

Q5: (question)
Answer: (answer)

Make explanations clear, code working, and quiz questions test real understanding."""

        user_prompt = f"""Topic: {topic}

Web Explanation:
{web_section[:2000] if web_section else "Not available"}

Notes Explanation:
{notes_section[:2000] if notes_section else "Not available"}

Create the perfect study guide for this CS topic."""

        explanation = call_llm(system_prompt, user_prompt)
        all_output.append(f"# {topic}\n\n{explanation}\n")

        time.sleep(0.5)

    result = "\n\n" + "═" * 60 + "\n\n".join(all_output)
    print(f"   Final synthesis complete for {len(topics)} topics")
    return result


def extract_topic_section(text: str, topic: str) -> str:
    """
    Extract the section for a specific topic from agent output text
    Looks for '## topic' heading and extracts until next '## ' heading
    """
    if not text:
        return ""

    lines       = text.split('\n')
    in_section  = False
    section     = []
    topic_lower = topic.lower()

    for line in lines:
        if line.startswith('## ') and topic_lower in line.lower():
            in_section = True
            section.append(line)
        elif line.startswith('## ') and in_section:
            break   # reached next topic section
        elif in_section:
            section.append(line)

    return '\n'.join(section)


# ─────────────────────────────────────────────────────────────────────────────
# QUICK TEST — python agents.py
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(" Testing agents.py...")

    # Test LLM connection
    print("\n Testing Groq LLM connection...")
    test_response = call_llm(
        "You are a helpful assistant.",
        "Say 'Groq is working!' and nothing else."
    )
    print(f"   LLM response: {test_response[:100]}")

    # Test Agent 1 with sample text
    print("\n Testing Agent 1 — PDF Reader...")
    sample_chunks = [
        """Binary Search is an efficient algorithm for finding an element
        in a sorted array. It works by repeatedly dividing the search space in half.
        Time complexity: O(log n). Space complexity: O(1).""",

        """Recursion is a technique where a function calls itself.
        Every recursive function needs a base case to stop.
        Example: factorial(n) = n * factorial(n-1), base case: factorial(0) = 1"""
    ]

    result = run_pdf_reader(sample_chunks, chat_id=1)
    print(f"   Topics found: {result.get('topics', [])}")

    print("\n agents.py tests complete!")
    print("\nNote: Agent 2, 3, 4 tests skipped here")
    print("They will be tested when the full pipeline runs in graph.py")
