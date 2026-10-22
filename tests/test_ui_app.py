"""Drive the Streamlit app with a stub pipeline (no API keys or network needed)."""
import os
import sys
import types
import unittest

from streamlit.testing.v1 import AppTest

from agents.interview_agent import InterviewAgent

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ui", "app.py")


class StubPipeline:
    """Mimics the compiled graph: real interview agent, canned retrieval and report."""

    def stream(self, state, stream_mode="values"):
        state = dict(state)
        state["retrieved_docs"] = [{"dtc_code": "P0301", "symptoms": ["Rough idle"], "text": "P0301 misfire"}]
        state["retrieved_evidence"] = [{"dtc_code": "P0301", "fault_name": "Cylinder 1 Misfire Detected",
                                        "source": "exact_dtc", "matching_symptoms": ["Rough idle"],
                                        "candidate_causes": ["Faulty spark plug"], "repair_steps": ["Replace plug"]}]
        state["confidence"], state["warnings"] = "High", []
        state["trace"] = [{"stage": "exact_dtc_match", "status": "complete", "detail": "Found P0301."}]
        yield state
        state = InterviewAgent().run(state)
        yield state
        if state["needs_follow_up"]:
            return
        state["response"] = {"fault_summary": "Cylinder 1 misfire", "severity": "Medium", "root_causes": ["Spark plug"],
                             "diagnostic_steps": ["Swap coil"], "immediate_action": "Avoid heavy load",
                             "estimated_repair": "Simple", "evidence": state["retrieved_evidence"],
                             "confidence": "High", "warnings": []}
        yield state


class StreamlitAppTests(unittest.TestCase):
    def setUp(self):
        fake = types.ModuleType("pipeline.graph")
        fake.build_graph = StubPipeline
        sys.modules["pipeline.graph"] = fake
        self.addCleanup(sys.modules.pop, "pipeline.graph", None)

    def test_empty_input_shows_error(self):
        app = AppTest.from_file(APP, default_timeout=30).run()
        app.get("form_submit_button")[0].click().run()
        self.assertTrue(any("at least one DTC" in error.value for error in app.error))

    def test_full_investigation_with_follow_up_answers(self):
        app = AppTest.from_file(APP, default_timeout=30).run()
        app.text_input(key="dtc_input").set_value("p0301")
        app.get("form_submit_button")[0].click().run()
        self.assertIn("A few questions to sharpen the diagnosis", [header.value for header in app.subheader])

        app.text_input(key="follow_up_notes").set_value("worse when cold")
        app.get("form_submit_button")[1].click().run()  # Continue investigation
        self.assertIn("Diagnosis report", [header.value for header in app.subheader])
        findings = app.session_state.investigation["result"]["interview_findings"]
        self.assertEqual(findings, [{"question": "Anything else you noticed?", "answer": "worse when cold"}])

    def test_example_button_prefills_inputs(self):
        app = AppTest.from_file(APP, default_timeout=30).run()
        app.sidebar.button[0].click().run()
        self.assertEqual(app.text_input(key="dtc_input").value, "P0301, P0171")
        self.assertEqual(app.text_input(key="fuel_trim").value, "+15%")


if __name__ == "__main__":
    unittest.main()
