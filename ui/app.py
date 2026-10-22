import json
import os
import re
import sys

import streamlit as st

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.interview_agent import NOTES_ID, NOTES_QUESTION

st.set_page_config(page_title="AutoDiag AI", page_icon="🔧", layout="wide")

DTC_PATTERN = re.compile(r"[PCBU][0-9A-F]{4}")
FREEZE_FRAME_FIELDS = [
    ("rpm", "RPM at fault", "e.g. 2500", "Engine speed when the fault was stored."),
    ("coolant_temp", "Coolant temperature", "e.g. 90C", "Low values point to cold-start faults."),
    ("fuel_trim", "Fuel trim", "e.g. +15%", "Positive = engine running lean, negative = running rich."),
    ("map_sensor", "MAP sensor", "e.g. 45kPa", "Intake manifold pressure; unusual idle values suggest leaks or restrictions."),
]
EXAMPLES = {
    "Misfire + lean mixture": {"dtc": "P0301, P0171", "rpm": "2500", "coolant_temp": "90C",
                               "fuel_trim": "+15%", "map_sensor": "45kPa"},
    "Catalyst efficiency": {"dtc": "P0420, P0430"},
    "Engine overheating": {"dtc": "P0217", "rpm": "1800", "coolant_temp": "118C"},
    "Unknown code": {"dtc": "P9999"},
}
STEPS = ["Fault input", "Evidence", "Interview", "Diagnosis", "Report"]
CONFIDENCE_COLORS = {"High": "green", "Medium": "orange", "Low": "red"}


@st.cache_resource(show_spinner="Loading models and knowledge base...")
def load_pipeline():
    from pipeline.graph import build_graph
    return build_graph()


# ---------------------------------------------------------------- helpers
def parse_codes(text: str) -> list[str]:
    return [code.upper() for code in re.split(r"[,;\s]+", text) if code.strip()]


def stage_title(stage: str) -> str:
    return stage.replace("_", " ").replace("dtc", "DTC").capitalize()


def severity_color(severity: str) -> str:
    text = severity.lower()
    if "critical" in text or "high" in text:
        return "red"
    if "medium" in text or "moderate" in text:
        return "orange"
    if "low" in text:
        return "green"
    return "gray"


def badge(text: str, color: str) -> str:
    return f":{color}-badge[{text.replace(']', ')').replace('[', '(')}]"


def fresh_state(initial_state: dict) -> dict:
    """Copy the user inputs so every pipeline run starts from clean state."""
    state = dict(initial_state)
    state["freeze_frame"] = dict(initial_state.get("freeze_frame", {}))
    return state


def report_markdown(result: dict) -> str:
    response = result.get("response", {})
    lines = [
        "# AutoDiag AI diagnosis report",
        "",
        f"**DTC codes:** {', '.join(result.get('dtc_codes', []))}  ",
        f"**Severity:** {response.get('severity', 'Unknown')}  ",
        f"**Evidence confidence:** {response.get('confidence', 'Low')}",
        "",
    ]
    if result.get("freeze_frame"):
        lines += ["## Freeze frame", *[f"- {k}: {v}" for k, v in result["freeze_frame"].items()], ""]
    if response.get("warnings"):
        lines += ["## Warnings", *[f"- {w}" for w in response["warnings"]], ""]
    lines += ["## Fault summary", response.get("fault_summary", response.get("raw", "N/A")), ""]
    lines += ["## Immediate action", response.get("immediate_action", "N/A"), ""]
    lines += ["## Root causes", *[f"{i}. {c}" for i, c in enumerate(response.get("root_causes", []), 1)], ""]
    lines += ["## Diagnostic steps", *[f"{i}. {s}" for i, s in enumerate(response.get("diagnostic_steps", []), 1)], ""]
    lines += ["## Estimated repair", response.get("estimated_repair", "N/A"), ""]
    if result.get("interview_findings"):
        lines += ["## Follow-up answers", *[f"- {f['question']} {f['answer']}" for f in result["interview_findings"]], ""]
    lines += ["## Evidence", *[f"- {e['dtc_code']}: {e['fault_name']} ({e['source']})" for e in response.get("evidence", [])], ""]
    lines += ["---", "_Guidance only; verify with a qualified technician before any repair._"]
    return "\n".join(lines)


def run_pipeline(state: dict, label: str) -> dict | None:
    """Run the graph, streaming each agent's trace events into a live status panel."""
    with st.status(label, expanded=True) as status:
        result, shown = state, 0
        try:
            for result in load_pipeline().stream(state, stream_mode="values"):
                trace = result.get("trace", [])
                for event in trace[shown:]:
                    st.write(f"✓ **{stage_title(event['stage'])}** · {event['detail']}")
                shown = len(trace)
        except Exception as exc:  # surface configuration or network problems instead of a stack trace
            status.update(label="Investigation failed", state="error", expanded=True)
            st.error(f"The pipeline stopped: {exc}. Check the API keys in .env and your internet connection.")
            return None
        done = "Waiting for your answers" if result.get("needs_follow_up") else "Investigation complete"
        status.update(label=done, state="complete", expanded=False)
    return result


def load_example(name: str) -> None:
    example = EXAMPLES[name]
    st.session_state.dtc_input = example["dtc"]
    for key, *_ in FREEZE_FRAME_FIELDS:
        st.session_state[key] = example.get(key, "")
    st.session_state.investigation = None


def reset() -> None:
    st.session_state.investigation = None


# ---------------------------------------------------------------- render pieces
def render_stepper(active: int) -> None:
    columns = st.columns(len(STEPS))
    for index, (column, name) in enumerate(zip(columns, STEPS)):
        if index < active:
            column.markdown(f":green[:material/check_circle:] {name}")
        elif index == active:
            column.markdown(f":blue[:material/radio_button_checked:] **{name}**")
        else:
            column.markdown(f":gray[:material/radio_button_unchecked: {name}]")


def render_evidence_summary(result: dict) -> None:
    evidence = result.get("retrieved_evidence", [])
    confidence = result.get("confidence", "Low")
    found = " ".join(badge(e["dtc_code"], "blue") for e in evidence) or badge("no direct match", "gray")
    st.markdown(f"Evidence found: {found} &nbsp; {badge('Confidence: ' + confidence, CONFIDENCE_COLORS.get(confidence, 'gray'))}")
    for warning in result.get("warnings", []):
        st.warning(warning, icon=":material/warning:")


def render_interview(investigation: dict) -> None:
    result = investigation["result"]
    with st.container(border=True):
        st.subheader("A few questions to sharpen the diagnosis")
        render_evidence_summary(result)
        st.caption("Every answer is optional. Pick what applies, or skip straight to the diagnosis.")
        with st.form("interview"):
            answers = {}
            for question in result.get("follow_up_questions", []):
                key = f"follow_up_{question['id']}"
                if question.get("options"):
                    answers[question["id"]] = st.pills(
                        question["question"], question["options"],
                        selection_mode="multi" if question.get("multi") else "single", key=key)
                else:
                    answers[question["id"]] = st.text_input(question["question"], key=key, max_chars=200)
                st.caption(f":material/info: Why we ask: {question['reason']}")
            answers[NOTES_ID] = st.text_input(NOTES_QUESTION, max_chars=200, key="follow_up_notes",
                                              placeholder="e.g. started after refuelling, worse in the rain")
            left, right, _ = st.columns([1.3, 1.1, 3])
            go = left.form_submit_button("Continue investigation", type="primary", icon=":material/arrow_forward:")
            skip = right.form_submit_button("Skip questions", icon=":material/fast_forward:")
    if go or skip:
        next_state = fresh_state(investigation["initial_state"])
        next_state["symptom_answers"] = {} if skip else answers
        next_state["interview_complete"] = True
        completed = run_pipeline(next_state, "Diagnosing with your answers...")
        if completed is not None:
            st.session_state.investigation = {"initial_state": investigation["initial_state"], "result": completed}
            st.rerun()


def render_report(result: dict) -> None:
    response = result.get("response", {})
    severity = response.get("severity", "Unknown")
    confidence = response.get("confidence", "Low")
    with st.container(border=True):
        st.subheader("Diagnosis report")
        st.markdown(
            badge(f"Severity: {severity}", severity_color(severity)) + " "
            + badge(f"Evidence confidence: {confidence}", CONFIDENCE_COLORS.get(confidence, "gray"))
        )
        metrics = st.columns(4)
        metrics[0].metric("Codes analysed", len(result.get("dtc_codes", [])))
        metrics[1].metric("Evidence records", len(response.get("evidence", [])))
        metrics[2].metric("Follow-up answers", len(result.get("interview_findings", [])))
        metrics[3].metric("Warnings", len(response.get("warnings", [])))

        for warning in response.get("warnings", []):
            st.warning(warning, icon=":material/warning:")

        if "raw" in response and "fault_summary" not in response:
            st.info("The model's answer could not be structured, so it is shown as written.")
            st.markdown(response["raw"])
        else:
            left, right = st.columns(2)
            with left:
                st.markdown("**Fault summary**")
                st.info(response.get("fault_summary", "N/A"), icon=":material/troubleshoot:")
                if response.get("severity_explanation"):
                    st.caption(response["severity_explanation"])
            with right:
                st.markdown("**Immediate action**")
                st.error(response.get("immediate_action", "N/A"), icon=":material/emergency_home:")
                st.caption(f"Estimated repair: {response.get('estimated_repair', 'N/A')}")

        causes_tab, evidence_tab, answers_tab, trace_tab, json_tab = st.tabs(
            ["Causes & steps", "Evidence", "Your answers", "Decision trace", "Raw JSON"])
        with causes_tab:
            left, right = st.columns(2)
            with left:
                st.markdown("**Probable root causes**")
                for index, cause in enumerate(response.get("root_causes", []), 1):
                    st.markdown(f"{index}. {cause}")
            with right:
                st.markdown("**Diagnostic steps** (most likely first)")
                for index, step in enumerate(response.get("diagnostic_steps", []), 1):
                    st.markdown(f"{index}. {step}")
        with evidence_tab:
            evidence_list = response.get("evidence", [])
            if not evidence_list:
                st.info("No directly matching knowledge-base evidence was found.")
            for evidence in evidence_list:
                with st.expander(f"{evidence['dtc_code']} · {evidence['fault_name']}"):
                    st.markdown(badge(f"source: {evidence['source']}", "gray"))
                    for title, field in (("Causes", "candidate_causes"), ("Symptoms", "matching_symptoms"),
                                         ("Repair steps", "repair_steps")):
                        if evidence.get(field):
                            st.markdown(f"**{title}:** " + "; ".join(evidence[field]))
        with answers_tab:
            findings = result.get("interview_findings", [])
            if not findings:
                st.caption("No follow-up answers were given for this investigation.")
            for finding in findings:
                st.markdown(f"- **{finding['question']}** {finding['answer']}")
        with trace_tab:
            for index, event in enumerate(result.get("trace", []), 1):
                st.markdown(f"{index}. **{stage_title(event['stage'])}** · {event['detail']}")
        with json_tab:
            st.json(response)

        codes = "_".join(result.get("dtc_codes", [])) or "report"
        left, right, _ = st.columns([1.3, 1.1, 3])
        left.download_button("Markdown report", report_markdown(result), f"autodiag_{codes}.md",
                             "text/markdown", icon=":material/download:")
        right.download_button("Download JSON", json.dumps(response, indent=2), f"autodiag_{codes}.json",
                              "application/json", icon=":material/data_object:")
    st.button("Start a new investigation", on_click=reset, icon=":material/restart_alt:")


# ---------------------------------------------------------------- page
if "investigation" not in st.session_state:
    st.session_state.investigation = None

with st.sidebar:
    st.header("🔧 AutoDiag AI")
    st.caption("Evidence-linked OBD-II fault investigation")
    st.subheader("Try an example")
    for name in EXAMPLES:
        st.button(name, on_click=load_example, args=(name,), width="stretch")
    st.subheader("How it works")
    st.markdown(
        "1. **Retrieval agent** finds the exact knowledge-base record for each code.\n"
        "2. **Interview agent** asks targeted questions when context is missing.\n"
        "3. **Diagnosis agent** reasons only over the evidence.\n"
        "4. **Response agent** builds the report with evidence and trace."
    )
    st.divider()
    st.caption("Guidance only, not a confirmed repair diagnosis. Always verify with a qualified technician, "
               "especially for brakes, airbags, fuel, high-voltage or overheating faults.")

st.title("Automotive Fault Diagnosis Agent")
st.caption("Enter trouble codes from your scan tool. The agents gather evidence, ask what they need, and explain their reasoning.")

investigation = st.session_state.investigation
if investigation is None:
    active_step = 0
elif investigation["result"].get("needs_follow_up"):
    active_step = 2
else:
    active_step = len(STEPS)
render_stepper(active_step)

with st.form("fault_input", border=True):
    st.text_input("DTC codes", key="dtc_input", placeholder="e.g. P0301, P0171",
                  help="One or more OBD-II codes, separated by commas or spaces.")
    st.markdown("**Freeze-frame data** · optional, but it sharpens the diagnosis")
    for column, (key, label, placeholder, help_text) in zip(st.columns(4), FREEZE_FRAME_FIELDS):
        column.text_input(label, key=key, placeholder=placeholder, help=help_text)
    submitted = st.form_submit_button("Start investigation", type="primary", icon=":material/search:")

if submitted:
    codes = parse_codes(st.session_state.get("dtc_input", ""))
    if not codes:
        st.error("Please enter at least one DTC code.")
    else:
        invalid = [code for code in codes if not DTC_PATTERN.fullmatch(code)]
        if invalid:
            st.warning(f"{', '.join(invalid)} do not look like standard OBD-II codes (letter P/C/B/U + 4 hex digits). "
                       "They will be checked anyway.")
        freeze_frame = {key: st.session_state[key].strip() for key, *_ in FREEZE_FRAME_FIELDS
                        if st.session_state.get(key, "").strip()}
        initial_state = {"dtc_codes": codes, "freeze_frame": freeze_frame, "retrieved_docs": [],
                         "diagnosis": "", "response": {}}
        result = run_pipeline(fresh_state(initial_state), "Investigating " + ", ".join(codes) + "...")
        if result is not None:
            st.session_state.investigation = {"initial_state": initial_state, "result": result}
            st.rerun()

if investigation is not None:
    if investigation["result"].get("needs_follow_up"):
        render_interview(investigation)
    else:
        render_report(investigation["result"])
