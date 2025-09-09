"""Agent state management for LangGraph workflows."""

from datetime import datetime
from typing import Any, Dict, List, Optional, TypedDict

from pydantic import BaseModel, Field


class AgentState(TypedDict):
    """State object passed between agent nodes."""
    
    # Input
    query: str
    user_id: str
    channel_id: str
    thread_ts: Optional[str]
    
    # Query understanding
    intent: Optional[Dict[str, Any]]
    query_type: Optional[str]
    entities: Optional[Dict[str, Any]]
    
    # Planning
    data_sources: Optional[List[Dict[str, Any]]]
    execution_plan: Optional[Dict[str, Any]]
    
    # Execution
    mcp_results: Optional[Dict[str, Any]]
    processed_data: Optional[Dict[str, Any]]
    
    # Output
    csv_path: Optional[str]
    result_summary: Optional[str]
    
    # Error handling
    error: Optional[str]
    warnings: Optional[List[str]]
    
    # Metadata
    created_at: str
    processing_steps: List[str]


class QueryIntent(BaseModel):
    """Structured representation of query intent."""
    
    intent_type: str = Field(description="Type of query (metrics, performance, trends, etc.)")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score")
    entities: Dict[str, Any] = Field(default_factory=dict, description="Extracted entities")
    time_range: Optional[Dict[str, str]] = Field(default=None, description="Time period specification")
    filters: Dict[str, Any] = Field(default_factory=dict, description="Query filters")
    data_sources: List[str] = Field(default_factory=list, description="Required data sources")
    output_format: str = Field(default="csv", description="Desired output format")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class ExecutionPlan(BaseModel):
    """Plan for executing data retrieval."""
    
    plan_id: str = Field(description="Unique plan identifier")
    steps: List[Dict[str, Any]] = Field(description="Execution steps")
    estimated_time: int = Field(description="Estimated execution time in seconds")
    complexity: str = Field(description="Query complexity (simple, medium, complex)")
    parallel_execution: bool = Field(default=False, description="Can steps run in parallel")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class MCPToolCall(BaseModel):
    """Represents an MCP tool call."""
    
    tool_name: str = Field(description="Name of the MCP tool")
    arguments: Dict[str, Any] = Field(description="Tool arguments")
    timeout: int = Field(default=30, description="Timeout in seconds")
    retry_count: int = Field(default=8, description="Number of retries")


class DataSource(BaseModel):
    """Configuration for a data source."""
    
    name: str = Field(description="Data source name")
    type: str = Field(description="Data source type")
    mcp_tools: List[MCPToolCall] = Field(description="Required MCP tool calls")
    priority: int = Field(default=1, description="Execution priority")
    required: bool = Field(default=True, description="Is this data source required")


class ProcessingResult(BaseModel):
    """Result of data processing."""
    
    success: bool = Field(description="Processing success status")
    data: Optional[Dict[str, Any]] = Field(default=None, description="Processed data")
    row_count: Optional[int] = Field(default=None, description="Number of data rows")
    column_count: Optional[int] = Field(default=None, description="Number of columns")
    warnings: List[str] = Field(default_factory=list, description="Processing warnings")
    errors: List[str] = Field(default_factory=list, description="Processing errors")
    processing_time: Optional[float] = Field(default=None, description="Processing time in seconds")


def create_initial_state(
    query: str,
    user_id: str,
    channel_id: str,
    thread_ts: Optional[str] = None
) -> AgentState:
    """Create initial agent state."""
    return AgentState(
        query=query,
        user_id=user_id,
        channel_id=channel_id,
        thread_ts=thread_ts,
        intent=None,
        query_type=None,
        entities=None,
        data_sources=None,
        execution_plan=None,
        mcp_results=None,
        processed_data=None,
        csv_path=None,
        result_summary=None,
        error=None,
        warnings=[],
        created_at=datetime.utcnow().isoformat(),
        processing_steps=[],
    )