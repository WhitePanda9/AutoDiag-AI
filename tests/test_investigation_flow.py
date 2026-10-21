import unittest

from agents.interview_agent import InterviewAgent
from agents.retrieval_agent import RetrievalAgent


def document(code: str) -> dict:
    return {
        "dtc_code": code,
        "fault_name": "Test fault",
        "symptoms": ["rough idle"],
        "causes": ["test cause"],
        "repair_steps": ["test step"],
        "text": f"{code} test fault rough idle",
        "source": "exact_dtc",
        "score": 1.0,
    }


class StubRetriever:
    def __init__(self, exact=None, fallback=None):
        self.exact = exact or {}
        self.fallback = fallback or []
        self.fallback_calls = 0

    def exact_dtc_search(self, code):
        return self.exact.get(code, [])

    def hybrid_search(self, query, top_k=3):
        self.fallback_calls += 1
        return self.fallback


class InvestigationFlowTests(unittest.TestCase):
    def make_agent(self, retriever):
        agent = RetrievalAgent.__new__(RetrievalAgent)
        agent.retriever = retriever
        return agent

    def test_exact_dtc_match_excludes_fuzzy_neighbours(self):
        retriever = StubRetriever(
            exact={"P0300": [document("P0300")]},
            fallback=[document("P30D8"), document("P30DD")],
        )
        result = self.make_agent(retriever).run({
            "dtc_codes": ["P0300"], "freeze_frame": {}, "retrieved_docs": [], "diagnosis": "", "response": {}
        })
        self.assertEqual([item["dtc_code"] for item in result["retrieved_docs"]], ["P0300"])
        self.assertEqual(retriever.fallback_calls, 0)
        self.assertEqual(result["confidence"], "High")

    def test_unknown_code_has_warning_and_low_confidence(self):
        result = self.make_agent(StubRetriever()).run({
            "dtc_codes": ["P9999"], "freeze_frame": {}, "retrieved_docs": [], "diagnosis": "", "response": {}
        })
        self.assertEqual(result["confidence"], "Low")
        self.assertTrue(any("No direct" in warning for warning in result["warnings"]))

    def test_interview_requests_questions_then_accepts_answers(self):
        agent = InterviewAgent()
        waiting = agent.run({"dtc_codes": ["P0301"], "freeze_frame": {}, "retrieved_docs": []})
        self.assertTrue(waiting["needs_follow_up"])
        self.assertTrue(waiting["follow_up_questions"])
        complete = agent.run({"dtc_codes": ["P0301"], "symptom_answers": {"misfire_behavior": "at idle"}})
        self.assertFalse(complete["needs_follow_up"])


if __name__ == "__main__":
    unittest.main()
