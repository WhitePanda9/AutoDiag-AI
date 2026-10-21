import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langgraph.graph import StateGraph, END
from agents.retrieval_agent import RetrievalAgent, AgentState
from agents.diagnosis_agent import DiagnosisAgent
from agents.response_agent import ResponseAgent
from agents.interview_agent import InterviewAgent

def build_graph():
    # Initialize agents
    retrieval_agent = RetrievalAgent()
    diagnosis_agent = DiagnosisAgent()
    response_agent = ResponseAgent()
    interview_agent = InterviewAgent()
    
    # Build graph
    graph = StateGraph(AgentState)
    
    # Add nodes
    graph.add_node("retrieval", retrieval_agent.run)
    graph.add_node("diagnosis", diagnosis_agent.run)
    graph.add_node("response", response_agent.run)
    graph.add_node("interview", interview_agent.run)
    
    # Add edges
    graph.set_entry_point("retrieval")
    graph.add_edge("retrieval", "interview")
    graph.add_conditional_edges(
        "interview",
        lambda state: "follow_up" if state.get("needs_follow_up") else "diagnosis",
        {"follow_up": END, "diagnosis": "diagnosis"},
    )
    graph.add_edge("diagnosis", "response")
    graph.add_edge("response", END)
    
    return graph.compile()

if __name__ == "__main__":
    pipeline = build_graph()
    
    # Test run
    result = pipeline.invoke({
        "dtc_codes": ["P0301"],
        "freeze_frame": {
            "rpm": "2500",
            "coolant_temp": "90C",
            "fuel_trim": "+15%",
            "map_sensor": "45kPa"
        },
        "retrieved_docs": [],
        "diagnosis": "",
        "response": {}
    })
    
    import json
    print(json.dumps(result["response"], indent=2))
