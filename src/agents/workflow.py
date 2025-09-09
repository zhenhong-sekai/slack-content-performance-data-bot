"""LangGraph agent workflow definition."""

from typing import Dict, Any

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from src.agents.state import AgentState
from src.agents.nodes.query_understanding import understand_query_node
from src.agents.nodes.query_planning import plan_execution_node
from src.agents.nodes.data_retrieval import execute_data_retrieval_node
from src.agents.nodes.results_formatting import format_results_node
from src.utils.logging import get_logger

logger = get_logger(__name__)


def should_continue_to_planning(state: AgentState) -> str:
    """Determine if we should continue to planning or end with error."""
    if state.get("error"):
        return "error"
    if not state.get("intent"):
        return "error"
    return "continue"


def should_continue_to_execution(state: AgentState) -> str:
    """Determine if we should continue to execution or end with error."""
    if state.get("error"):
        return "error"
    if not state.get("execution_plan"):
        return "error"
    return "continue"


def should_continue_to_formatting(state: AgentState) -> str:
    """Determine if we should continue to formatting or end with error."""
    if state.get("error"):
        return "error"
    if not state.get("mcp_results"):
        return "error"
    return "continue"


def create_agent_workflow() -> StateGraph:
    """Create the LangGraph agent workflow."""
    
    # Create workflow graph
    workflow = StateGraph(AgentState)
    
    # Add nodes
    workflow.add_node("understand_query", understand_query_node)
    workflow.add_node("plan_execution", plan_execution_node)
    workflow.add_node("execute_data_retrieval", execute_data_retrieval_node)
    workflow.add_node("format_results", format_results_node)
    workflow.add_node("handle_error", handle_error_node)
    
    # Set entry point
    workflow.set_entry_point("understand_query")
    
    # Add conditional edges
    workflow.add_conditional_edges(
        "understand_query",
        should_continue_to_planning,
        {
            "continue": "plan_execution",
            "error": "handle_error"
        }
    )
    
    workflow.add_conditional_edges(
        "plan_execution",
        should_continue_to_execution,
        {
            "continue": "execute_data_retrieval",
            "error": "handle_error"
        }
    )
    
    workflow.add_conditional_edges(
        "execute_data_retrieval",
        should_continue_to_formatting,
        {
            "continue": "format_results",
            "error": "handle_error"
        }
    )
    
    # Add edges to end
    workflow.add_edge("format_results", END)
    workflow.add_edge("handle_error", END)
    
    return workflow


def handle_error_node(state: AgentState) -> AgentState:
    """Handle errors and prepare error response."""
    error = state.get("error", "Unknown error occurred")
    
    logger.error(
        "Agent workflow error",
        error=error,
        query=state.get("query"),
        user_id=state.get("user_id"),
        processing_steps=state.get("processing_steps", []),
    )
    
    # Add error handling step
    processing_steps = list(state.get("processing_steps", []))
    processing_steps.append("error_handling")
    
    # Create user-friendly error message
    if "validation" in error.lower():
        user_error = (
            "I couldn't understand your query. Could you please rephrase it? "
            "Try being more specific about what data you're looking for."
        )
    elif "timeout" in error.lower():
        user_error = (
            "Your query is taking longer than expected. "
            "Please try a more specific query or try again later."
        )
    elif "mcp" in error.lower() or "server" in error.lower():
        user_error = (
            "I'm having trouble accessing the data right now. "
            "Please try again in a few minutes."
        )
    else:
        user_error = (
            "Something went wrong while processing your query. "
            "Please try rephrasing your question or contact support if this continues."
        )
    
    return {
        **state,
        "result_summary": user_error,
        "processing_steps": processing_steps,
    }


def compile_workflow() -> StateGraph:
    """Compile the agent workflow with memory."""
    workflow = create_agent_workflow()
    
    # Add memory for state persistence
    memory = MemorySaver()
    
    # Compile the workflow
    compiled_workflow = workflow.compile(checkpointer=memory)
    
    logger.info("Agent workflow compiled successfully")
    
    return compiled_workflow


# Global workflow instance
_compiled_workflow = None


def get_agent_workflow() -> StateGraph:
    """Get or create compiled agent workflow."""
    global _compiled_workflow
    
    if _compiled_workflow is None:
        _compiled_workflow = compile_workflow()
    
    return _compiled_workflow