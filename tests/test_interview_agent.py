import unittest

from agents.interview_agent import MAX_ANSWER_CHARS, MAX_QUESTIONS, NOTES_ID, InterviewAgent, plan_questions


def evidence(code: str, symptoms=(), text: str = "") -> dict:
    return {"dtc_code": code, "symptoms": list(symptoms), "text": text or f"{code} test fault"}


def ids(questions: list[dict]) -> list[str]:
    return [question["id"] for question in questions]


class InterviewPlanningTests(unittest.TestCase):
    def test_misfire_without_freeze_frame_asks_prioritised_questions(self):
        questions = plan_questions({"dtc_codes": ["P0301"], "freeze_frame": {}, "retrieved_docs": [evidence("P0301")]})
        self.assertEqual(ids(questions), ["mil_state", "operating_condition", "misfire_behavior", "recent_work"])
        self.assertTrue(all(question["options"] for question in questions))

    def test_safety_question_comes_first_and_list_is_capped(self):
        questions = plan_questions({
            "dtc_codes": ["P0301", "P0171", "P0217"],
            "freeze_frame": {},
            "retrieved_docs": [evidence("P0217", text="engine overheat condition")],
        })
        self.assertEqual(questions[0]["id"], "safety_check")
        self.assertEqual(len(questions), MAX_QUESTIONS)

    def test_freeze_frame_drops_operating_condition_question(self):
        questions = plan_questions({"dtc_codes": ["P0301"], "freeze_frame": {"rpm": "2500"}, "retrieved_docs": []})
        self.assertNotIn("operating_condition", ids(questions))

    def test_no_primary_rule_means_no_interview(self):
        questions = plan_questions({
            "dtc_codes": ["P0505"],
            "freeze_frame": {"rpm": "800"},
            "retrieved_docs": [evidence("P0505")],
        })
        self.assertEqual(questions, [])

    def test_symptom_checklist_comes_from_retrieved_evidence(self):
        questions = plan_questions({
            "dtc_codes": ["P0420"],
            "freeze_frame": {"rpm": "2500"},
            "retrieved_docs": [evidence("P0420", symptoms=["Check engine light", "Reduced power"])],
        })
        self.assertEqual(ids(questions), ["catalyst_signs", "evidence_symptoms", "recent_work"])
        checklist = questions[1]
        self.assertEqual(checklist["options"], ["Check engine light", "Reduced power", "None of these"])
        self.assertTrue(checklist["multi"])

    def test_codes_without_own_rule_still_get_questions(self):
        for code in ("P0131", "P0135", "P0325", "P0340", "P0500", "P2135"):
            with self.subTest(code=code):
                questions = plan_questions({"dtc_codes": [code], "freeze_frame": {"rpm": "2500"},
                                            "retrieved_docs": [evidence(code)]})
                self.assertTrue(questions)

    def test_documented_symptoms_alone_start_an_interview(self):
        questions = plan_questions({"dtc_codes": ["P0505"], "freeze_frame": {"rpm": "800"},
                                    "retrieved_docs": [evidence("P0505", symptoms=["Unstable idle"])]})
        self.assertEqual(ids(questions), ["evidence_symptoms", "recent_work"])

    def test_unknown_code_asks_for_vehicle_details_as_free_text(self):
        questions = plan_questions({"dtc_codes": ["P9999"], "freeze_frame": {"rpm": "2500"}, "retrieved_docs": []})
        self.assertEqual(questions[0]["id"], "vehicle_details")
        self.assertEqual(questions[0]["options"], [])

    def test_code_family_ranges(self):
        cases = {"P0442": "fuel_cap", "P0730": "shift_quality", "U0100": "battery_history", "P0128": "temperature_gauge"}
        for code, expected in cases.items():
            with self.subTest(code=code):
                questions = plan_questions({"dtc_codes": [code], "freeze_frame": {"rpm": "1"}, "retrieved_docs": []})
                self.assertIn(expected, ids(questions))


class InterviewAnswerTests(unittest.TestCase):
    def test_answers_become_readable_findings(self):
        state = InterviewAgent().run({
            "dtc_codes": ["P0301"],
            "freeze_frame": {},
            "retrieved_docs": [],
            "interview_complete": True,
            "symptom_answers": {
                "mil_state": "Flashing",
                "misfire_behavior": "Not sure",
                "operating_condition": ["At idle", "While accelerating"],
                NOTES_ID: "  started   after refuelling ",
                "recent_work": None,
            },
        })
        self.assertFalse(state["needs_follow_up"])
        self.assertEqual(state["interview_findings"], [
            {"question": "Is the check-engine light steady or flashing?", "answer": "Flashing"},
            {"question": "When does the fault occur?", "answer": "At idle; While accelerating"},
            {"question": "Anything else you noticed?", "answer": "started after refuelling"},
        ])

    def test_long_answers_are_truncated(self):
        state = InterviewAgent().run({"dtc_codes": ["P0301"], "symptom_answers": {NOTES_ID: "x" * 1000}})
        self.assertEqual(len(state["interview_findings"][0]["answer"]), MAX_ANSWER_CHARS)

    def test_skipped_interview_completes_without_findings(self):
        state = InterviewAgent().run({"dtc_codes": ["P0301"], "symptom_answers": {}, "interview_complete": True})
        self.assertFalse(state["needs_follow_up"])
        self.assertEqual(state["interview_findings"], [])
        self.assertIn("skipped", state["trace"][-1]["detail"])


if __name__ == "__main__":
    unittest.main()
