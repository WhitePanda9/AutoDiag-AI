from retrieval.hybrid_retriever import HybridRetriever
from typing import TypedDict, List, NotRequired
import re

class AgentState(TypedDict):
    dtc_codes: List[str]
    freeze_frame: dict
    retrieved_docs: List[dict]
    diagnosis: str
    response: dict
    retrieved_evidence: NotRequired[List[dict]]
    confidence: NotRequired[str]
    warnings: NotRequired[List[str]]
    trace: NotRequired[List[dict]]
    follow_up_questions: NotRequired[List[dict]]
    symptom_answers: NotRequired[dict]
    interview_findings: NotRequired[List[dict]]
    interview_complete: NotRequired[bool]
    needs_follow_up: NotRequired[bool]

class RetrievalAgent:
    def __init__(self):
        self.retriever = HybridRetriever()
    
    def run(self, state: AgentState) -> AgentState:
        """Retrieve relevant docs for given DTC codes"""
        dtc_codes = [code.strip().upper() for code in state["dtc_codes"] if code.strip()]
        freeze_frame = state.get("freeze_frame", {})
        trace = state.setdefault("trace", [])
        warnings = state.setdefault("warnings", [])

        invalid_codes = [code for code in dtc_codes if not re.fullmatch(r"[PCBU][0-9A-F]{4}", code)]
        if invalid_codes:
            warnings.append(f"Unsupported DTC format: {', '.join(invalid_codes)}.")
        
        # Build query from DTC codes + freeze frame context
        query_parts = dtc_codes.copy()
        
        if freeze_frame:
            if freeze_frame.get("rpm"):
                query_parts.append(f"RPM {freeze_frame['rpm']}")
            if freeze_frame.get("coolant_temp"):
                query_parts.append(f"coolant temperature {freeze_frame['coolant_temp']}")
            if freeze_frame.get("fuel_trim"):
                query_parts.append(f"fuel trim {freeze_frame['fuel_trim']}")
        
        query = " ".join(query_parts)
        print(f"Retrieval query: {query}")
        
        # Exact code matching is intentionally the first retrieval stage. It
        # prevents semantically similar, but unrelated, codes (e.g. P30D8 for
        # P0300) from displacing authoritative code-specific evidence.
        all_docs = []
        seen_codes = set()
        exact_codes = []
        
        for code in dtc_codes:
            results = self.retriever.exact_dtc_search(code)
            for doc in results:
                if doc["dtc_code"] not in seen_codes:
                    all_docs.append(doc)
                    seen_codes.add(doc["dtc_code"])
                    exact_codes.append(doc["dtc_code"])

        trace.append({
            "stage": "exact_dtc_match",
            "status": "complete",
            "detail": f"Found direct knowledge-base matches for: {', '.join(exact_codes) or 'none'}.",
        })

        # Only use fuzzy retrieval if no direct DTC record exists. Exact
        # matches already contain the most relevant evidence and this guard
        # avoids leaking visually similar fault codes into the diagnosis.
        if not all_docs:
            context_results = self.retriever.hybrid_search(query, top_k=3)
            for doc in context_results:
                if doc["dtc_code"] not in seen_codes:
                    all_docs.append(doc)
                    seen_codes.add(doc["dtc_code"])
            trace.append({
                "stage": "fallback_retrieval",
                "status": "used",
                "detail": f"No exact match; retrieved {len(all_docs)} contextual record(s).",
            })
        else:
            trace.append({
                "stage": "fallback_retrieval",
                "status": "skipped",
                "detail": "Exact DTC evidence was available, so unrelated fuzzy matches were excluded.",
            })
        
        missing_codes = [code for code in dtc_codes if code not in exact_codes]
        if missing_codes:
            warnings.append(
                "No direct OBD-II knowledge-base match for: " + ", ".join(missing_codes) + "."
            )
        
        print(f"Retrieved {len(all_docs)} relevant documents")
        state["retrieved_docs"] = all_docs
        state["retrieved_evidence"] = [
            {
                "dtc_code": doc["dtc_code"],
                "fault_name": doc["fault_name"],
                "source": doc.get("source", "knowledge_base"),
                "matching_symptoms": doc.get("symptoms", []),
                "candidate_causes": doc.get("causes", []),
                "repair_steps": doc.get("repair_steps", []),
            }
            for doc in all_docs
        ]
        safety_terms = ("high voltage", "electric shock", "airbag", "brake", "fuel leak", "overheat")
        evidence_text = " ".join(doc.get("text", "") for doc in all_docs).lower()
        if any(term in evidence_text for term in safety_terms):
            warnings.append(
                "Safety-critical system or symptom detected. Do not perform high-voltage, airbag, brake, fuel-system, or overheating repairs without qualified inspection."
            )
        state["confidence"] = "High" if len(exact_codes) == len(dtc_codes) else ("Medium" if all_docs else "Low")
        trace.append({
            "stage": "evidence_assessment",
            "status": state["confidence"].lower(),
            "detail": f"Prepared {len(all_docs)} evidence record(s); confidence is {state['confidence']}.",
        })
        return state
