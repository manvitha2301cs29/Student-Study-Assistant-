# review_session.py
# ─────────────────────────────────────────────────────────────────────────────
# Handles review sessions for spaced repetition
#
# WHAT THIS FILE DOES:
# When student clicks "Start Review" for a topic:
# 1. Loads the topic's previous explanation from SQLite
# 2. Generates fresh quiz questions using Groq (focused on weak points)
# 3. Evaluates student's answers
# 4. Updates SM-2 schedule based on score
# 5. Shows personalized feedback
# ─────────────────────────────────────────────────────────────────────────────

import os
import time
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage

from database import (
    get_agent_outputs,
    get_latest_quiz_score,
    save_quiz_score,
)
from spaced_repetition import process_quiz_result

load_dotenv()

# ── Groq LLM ──────────────────────────────────────────────────────────────────
llm = ChatGroq(
    model       = "llama-3.1-8b-instant",
    temperature = 0.4,
    api_key     = os.getenv("GROQ_API_KEY"),
)


# ─────────────────────────────────────────────────────────────────────────────
# GENERATE REVIEW QUIZ
# Creates fresh questions focused on student's weak points
# ─────────────────────────────────────────────────────────────────────────────
def generate_review_quiz(chat_id: int, topic: str) -> dict:
    """
    Generate a fresh quiz for a review session

    Checks previous quiz scores to focus on weak points
    Returns dict with questions list
    """
    print(f"\n Generating review quiz for: {topic}")

    # Get previous quiz performance for this topic
    last_score = get_latest_quiz_score(chat_id, topic)
    weak_focus = ""
    if last_score:
        score_pct  = round(last_score["score"] / max(last_score["total_questions"], 1) * 100)
        wrong      = last_score.get("wrong_topics", [])
        weak_focus = f"""
Previous score: {last_score['score']}/{last_score['total_questions']} ({score_pct}%)
Student struggled with: {', '.join(wrong) if wrong else 'general concepts'}
Focus your questions on these weak areas."""

    # Get topic explanation from database for context
    outputs  = get_agent_outputs(chat_id)
    context  = ""
    if outputs:
        final = outputs.get("final_output", "")
        # Extract section for this topic
        if topic in final:
            start = final.find(f"# {topic}")
            end   = final.find("\n# ", start + 1) if start != -1 else -1
            if start != -1:
                context = final[start:end][:2000] if end != -1 else final[start:start+2000]

    system = """You are a CS quiz generator creating review questions.
Generate exactly 5 questions to test understanding of the topic.
Mix question types: definition, application, code output, comparison.

Respond with ONLY this JSON format (no markdown, no extra text):
{
  "questions": [
    {
      "id": 1,
      "question": "question text here",
      "type": "definition|application|code|comparison",
      "answer": "correct answer here",
      "explanation": "why this answer is correct"
    }
  ]
}"""

    user = f"""Topic: {topic}
{weak_focus}

Context from student's notes:
{context if context else "Use general CS knowledge for this topic"}

Generate 5 review questions for this topic."""

    try:
        response = llm.invoke([
            SystemMessage(content=system),
            HumanMessage(content=user)
        ])
        content = response.content.strip()

        # Clean JSON
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        content = content.strip()

        import json
        result = json.loads(content)
        questions = result.get("questions", [])
        print(f"  ✅ Generated {len(questions)} questions")
        return {"questions": questions, "topic": topic}

    except Exception as e:
        print(f"   Quiz generation failed: {e}")
        # Fallback questions
        return {
            "topic": topic,
            "questions": [
                {
                    "id": 1,
                    "question": f"What is {topic}? Explain in your own words.",
                    "type": "definition",
                    "answer": f"A comprehensive explanation of {topic}",
                    "explanation": "Understanding the core concept is fundamental."
                },
                {
                    "id": 2,
                    "question": f"What is the main use case of {topic}?",
                    "type": "application",
                    "answer": "Depends on the specific topic",
                    "explanation": "Practical application shows deep understanding."
                },
                {
                    "id": 3,
                    "question": f"What are the advantages of {topic}?",
                    "type": "comparison",
                    "answer": "Multiple advantages depending on context",
                    "explanation": "Knowing trade-offs is important for interviews."
                }
            ]
        }


# ─────────────────────────────────────────────────────────────────────────────
# EVALUATE ANSWERS
# Uses Groq to grade student's answers intelligently
# ─────────────────────────────────────────────────────────────────────────────
def evaluate_answers(topic: str, questions: list,
                     student_answers: dict) -> dict:
    """
    Evaluate student's answers using Groq

    questions      = list of question dicts
    student_answers = {question_id: answer_text}

    Returns evaluation with score + feedback per question
    """
    print(f"\n Evaluating answers for: {topic}")

    evaluations = []
    correct     = 0

    for q in questions:
        qid            = str(q["id"])
        student_answer = student_answers.get(qid, "").strip()
        correct_answer = q.get("answer", "")
        explanation    = q.get("explanation", "")

        if not student_answer:
            evaluations.append({
                "question_id" : q["id"],
                "question"    : q["question"],
                "your_answer" : "(no answer)",
                "correct"     : False,
                "feedback"    : f"No answer provided. Correct answer: {correct_answer}"
            })
            continue

        # Use Groq to evaluate answer intelligently
        eval_prompt = f"""Topic: {topic}
Question: {q['question']}
Correct Answer: {correct_answer}
Student's Answer: {student_answer}

Is the student's answer correct or mostly correct?
Respond with ONLY: CORRECT or INCORRECT
Then on a new line, provide one sentence of feedback."""

        try:
            response = llm.invoke([HumanMessage(content=eval_prompt)])
            eval_text = response.content.strip()
            lines     = eval_text.split('\n')
            is_correct = "CORRECT" in lines[0].upper() and "INCORRECT" not in lines[0].upper()
            feedback   = lines[1].strip() if len(lines) > 1 else explanation

        except Exception:
            # Fallback: simple string matching
            is_correct = any(
                word in student_answer.lower()
                for word in correct_answer.lower().split()[:3]
            )
            feedback = f"Correct answer: {correct_answer}"

        if is_correct:
            correct += 1

        evaluations.append({
            "question_id"    : q["id"],
            "question"       : q["question"],
            "your_answer"    : student_answer,
            "correct_answer" : correct_answer,
            "is_correct"     : is_correct,
            "feedback"       : feedback
        })

        time.sleep(0.3)   # small delay between evaluations

    score_pct = round(correct / len(questions) * 100) if questions else 0
    print(f"   Score: {correct}/{len(questions)} ({score_pct}%)")

    return {
        "topic"       : topic,
        "score"       : correct,
        "total"       : len(questions),
        "score_pct"   : score_pct,
        "evaluations" : evaluations,
    }


# ─────────────────────────────────────────────────────────────────────────────
# COMPLETE REVIEW SESSION
# Full flow: generate → evaluate → update SM-2 → save score
# ─────────────────────────────────────────────────────────────────────────────
def complete_review_session(chat_id: int, topic: str,
                            questions: list,
                            student_answers: dict) -> dict:
    """
    Complete a full review session:
    1. Evaluate student's answers
    2. Save quiz score to SQLite
    3. Update SM-2 schedule
    4. Return full results + next review info

    Called when student submits their answers
    """
    print(f"\n Completing review session: {topic}")

    # Evaluate answers
    evaluation = evaluate_answers(topic, questions, student_answers)

    # Find wrong topics for targeted future review
    wrong_topics = [
        e["question"] for e in evaluation["evaluations"]
        if not e.get("is_correct")
    ]

    # Save to SQLite
    save_quiz_score(
        chat_id         = chat_id,
        topic           = topic,
        score           = evaluation["score"],
        total_questions = evaluation["total"],
        wrong_topics    = wrong_topics[:3]   # save up to 3 wrong areas
    )

    # Update SM-2 schedule
    sr_result = process_quiz_result(
        chat_id = chat_id,
        topic   = topic,
        score   = evaluation["score"],
        total   = evaluation["total"]
    )

    # Build result
    return {
        "topic"        : topic,
        "score"        : evaluation["score"],
        "total"        : evaluation["total"],
        "score_pct"    : evaluation["score_pct"],
        "evaluations"  : evaluation["evaluations"],
        "next_review"  : sr_result.get("next_review_date", ""),
        "is_mastered"  : sr_result.get("is_mastered", False),
        "sr_message"   : sr_result.get("message", ""),
    }
