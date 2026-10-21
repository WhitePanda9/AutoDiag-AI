"""Deterministic follow-up questions for incomplete investigations.

Questions are deliberately generated locally, rather than by the LLM, so the
application can clearly explain why it is requesting more information.
"""

from typing import Any


class InterviewAgent:
    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        answers = state.get("symptom_answers", {})
        if state.get("interview_complete") or answers:
            state["needs_follow_up"] = False
            state.setdefault("trace", []).append({
                "stage": "interview",
                "status": "complete",
                "detail": "Used the supplied follow-up answers.",
            })
            return state

        questions = []
        codes = state.get("dtc_codes", [])
        text = " ".join(doc.get("text", "") for doc in state.get("retrieved_docs", [])).lower()

        if not state.get("freeze_frame"):
            questions.append({
                "id": "operating_condition",
                "question": "When does the fault occur: at idle, while accelerating, under load, or all the time?",
                "reason": "Operating conditions help distinguish intermittent, load-related, and idle-related faults.",
            })
        if any(code.startswith("P03") for code in codes):
            questions.append({
                "id": "misfire_behavior",
                "question": "Does the engine shake at idle, only when accelerating, or continuously?",
                "reason": "Misfire behavior helps narrow ignition, fuel, and air-intake causes.",
            })
        if "lean" in text or any(code in {"P0171", "P0174"} for code in codes):
            questions.append({
                "id": "air_leak_signs",
                "question": "Do you hear a hissing sound, have a rough idle, or notice reduced fuel economy?",
                "reason": "These symptoms help assess a possible vacuum or unmetered-air leak.",
            })

        state["follow_up_questions"] = questions
        state["needs_follow_up"] = bool(questions)
        state.setdefault("trace", []).append({
            "stage": "interview",
            "status": "questions_requested" if questions else "not_needed",
            "detail": f"Requested {len(questions)} targeted follow-up question(s).",
        })
        return state
