import os
import sys

import streamlit as st

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

st.set_page_config(page_title="Automotive Fault Diagnosis Agent", page_icon="Wrench", layout="wide")
st.title("Automotive Fault Diagnosis Agent")
st.markdown("Evidence-linked OBD-II fault investigation")


@st.cache_resource(show_spinner="Loading pipeline...")
def load_pipeline():
    from pipeline.graph import build_graph
    return build_graph()


pipeline = load_pipeline()
if "investigation" not in st.session_state:
    st.session_state.investigation = None


def display_report(result: dict) -> None:
    """Render a completed, evidence-linked diagnostic report."""
    response = result["response"]
    st.header("Diagnosis Report")
    severity = response.get("severity", "Unknown")
    st.subheader(f"Severity: {severity}")
    st.caption(f"Evidence confidence: {response.get('confidence', 'Low')}")
    st.write(response.get("severity_explanation", ""))

    for warning in response.get("warnings", []):
        st.warning(warning)

    left, right = st.columns(2)
    with left:
        st.subheader("Fault Summary")
        st.info(response.get("fault_summary", "N/A"))
        st.subheader("Immediate Action")
        st.warning(response.get("immediate_action", "N/A"))
        st.subheader("Estimated Repair")
        st.write(response.get("estimated_repair", "N/A"))
    with right:
        st.subheader("Root Causes")
        for index, cause in enumerate(response.get("root_causes", []), 1):
            st.write(f"{index}. {cause}")
        st.subheader("Diagnostic Steps")
        for index, step in enumerate(response.get("diagnostic_steps", []), 1):
            st.write(f"{index}. {step}")

    with st.expander("Evidence used for this diagnosis"):
        evidence_list = response.get("evidence", [])
        if not evidence_list:
            st.info("No directly matching knowledge-base evidence was found.")
        for evidence in evidence_list:
            st.markdown(f"**{evidence['dtc_code']} - {evidence['fault_name']}** ({evidence['source']})")
            if evidence.get("candidate_causes"):
                st.write("Knowledge-base causes: " + ", ".join(evidence["candidate_causes"]))
            if evidence.get("matching_symptoms"):
                st.write("Knowledge-base symptoms: " + ", ".join(evidence["matching_symptoms"]))
            st.divider()

    with st.expander("Diagnostic decision trace"):
        for index, event in enumerate(result.get("trace", []), 1):
            st.write(f"{index}. **{event['stage'].replace('_', ' ').title()}** - {event['detail']}")

    with st.expander("View raw JSON response"):
        st.json(response)


st.header("Input Fault Data")
left, right = st.columns(2)
with left:
    dtc_input = st.text_input("DTC codes (comma separated)", placeholder="e.g. P0301, P0171")
with right:
    rpm = st.text_input("RPM at fault", placeholder="e.g. 2500")
    coolant_temp = st.text_input("Coolant temperature", placeholder="e.g. 90C")
    fuel_trim = st.text_input("Fuel trim", placeholder="e.g. +15%")
    map_sensor = st.text_input("MAP sensor", placeholder="e.g. 45kPa")

if st.button("Start investigation", type="primary"):
    if not dtc_input.strip():
        st.error("Please enter at least one DTC code.")
    else:
        freeze_frame = {
            key: value for key, value in {
                "rpm": rpm,
                "coolant_temp": coolant_temp,
                "fuel_trim": fuel_trim,
                "map_sensor": map_sensor,
            }.items() if value
        }
        initial_state = {
            "dtc_codes": [code.strip().upper() for code in dtc_input.split(",") if code.strip()],
            "freeze_frame": freeze_frame,
            "retrieved_docs": [],
            "diagnosis": "",
            "response": {},
        }
        with st.spinner("Retrieving fault evidence..."):
            result = pipeline.invoke(initial_state)
        st.session_state.investigation = {"initial_state": initial_state, "result": result}

if st.session_state.investigation:
    investigation = st.session_state.investigation
    result = investigation["result"]
    if result.get("needs_follow_up"):
        st.subheader("A few targeted questions before diagnosis")
        st.caption("Answers are optional, but they improve diagnostic confidence.")
        answers = {}
        for question in result.get("follow_up_questions", []):
            answers[question["id"]] = st.text_input(
                question["question"], help=question["reason"], key=f"follow_up_{question['id']}"
            )
        if st.button("Continue investigation", type="primary"):
            next_state = dict(investigation["initial_state"])
            next_state["symptom_answers"] = answers
            next_state["interview_complete"] = True
            with st.spinner("Investigating the evidence..."):
                completed = pipeline.invoke(next_state)
            st.session_state.investigation = {"initial_state": investigation["initial_state"], "result": completed}
            st.rerun()
    else:
        display_report(result)
        if st.button("Start a new investigation"):
            st.session_state.investigation = None
            st.rerun()
