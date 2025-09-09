"""Query planning node implementation."""

import uuid
from typing import Dict, Any, List

from src.agents.state import AgentState, ExecutionPlan, DataSource, MCPToolCall
from src.agents.mappers.intent_to_mcp import get_mcp_mapping
from src.utils.logging import get_logger

logger = get_logger(__name__)


async def plan_execution_node(state: AgentState) -> AgentState:
    """Plan MCP tool calls based on intent."""
    intent = state.get("intent")
    query_type = state.get("query_type")
    user_id = state.get("user_id")
    
    if not intent:
        return {
            **state,
            "error": "No intent available for planning",
        }
    
    logger.info(
        "Starting execution planning",
        query_type=query_type,
        intent_type=intent.get("intent_type"),
        user_id=user_id,
    )
    
    # Add processing step
    processing_steps = list(state.get("processing_steps", []))
    processing_steps.append("execution_planning")
    
    try:
        # Map intent to data sources and MCP tools
        data_sources = await map_intent_to_data_sources(intent)
        
        if not data_sources:
            return {
                **state,
                "error": "No suitable data sources found for this query",
                "processing_steps": processing_steps,
            }
        
        # Create execution plan
        execution_plan = create_execution_plan(data_sources, intent)
        
        # Validate execution plan
        validation_result = validate_execution_plan(execution_plan)
        if not validation_result["valid"]:
            return {
                **state,
                "error": f"Invalid execution plan: {validation_result['reason']}",
                "processing_steps": processing_steps,
            }
        
        logger.info(
            "Execution planning completed",
            plan_id=execution_plan.plan_id,
            steps_count=len(execution_plan.steps),
            complexity=execution_plan.complexity,
            estimated_time=execution_plan.estimated_time,
        )
        
        return {
            **state,
            "data_sources": [ds.model_dump() for ds in data_sources],
            "execution_plan": execution_plan.model_dump(),
            "processing_steps": processing_steps,
        }
        
    except Exception as e:
        logger.error(
            "Execution planning failed",
            query_type=query_type,
            error=str(e),
            exc_info=True,
        )
        
        return {
            **state,
            "error": f"Failed to create execution plan: {str(e)}",
            "processing_steps": processing_steps,
        }


async def map_intent_to_data_sources(intent: Dict[str, Any]) -> List[DataSource]:
    """Map query intent to required data sources."""
    intent_type = intent.get("intent_type")
    data_sources_needed = intent.get("data_sources", [])
    entities = intent.get("entities", {})
    filters = intent.get("filters", {})
    
    # Get MCP mapping configuration
    mcp_mapping = get_mcp_mapping()
    
    data_sources = []
    
    # Map each required data source to MCP tools
    for source_name in data_sources_needed:
        if source_name not in mcp_mapping:
            logger.warning(f"Unknown data source: {source_name}")
            continue
        
        source_config = mcp_mapping[source_name]
        
        # Create MCP tool calls based on intent
        mcp_tools = []
        
        for tool_config in source_config.get("tools", []):
            # Check if tool is relevant for this intent type
            if intent_type in tool_config.get("intent_types", []):
                
                # Build tool arguments
                arguments = build_tool_arguments(
                    tool_config,
                    intent,
                    entities,
                    filters
                )
                
                mcp_tool = MCPToolCall(
                    tool_name=tool_config["name"],
                    arguments=arguments,
                    timeout=tool_config.get("timeout", 30),
                    retry_count=tool_config.get("retry_count", 3),
                )
                
                mcp_tools.append(mcp_tool)
        
        if mcp_tools:
            data_source = DataSource(
                name=source_name,
                type=source_config["type"],
                mcp_tools=mcp_tools,
                priority=source_config.get("priority", 1),
                required=source_config.get("required", True),
            )
            
            data_sources.append(data_source)
    
    # Sort by priority (higher priority first)
    data_sources.sort(key=lambda ds: ds.priority, reverse=True)
    
    return data_sources


def create_execution_plan(
    data_sources: List[DataSource], 
    intent: Dict[str, Any]
) -> ExecutionPlan:
    """Create execution plan from data sources."""
    plan_id = str(uuid.uuid4())
    
    steps = []
    total_estimated_time = 0
    
    # Determine if we can run steps in parallel
    parallel_execution = len(data_sources) > 1 and all(
        not ds.required or len(ds.mcp_tools) == 1 for ds in data_sources
    )
    
    # Create execution steps
    for i, data_source in enumerate(data_sources):
        step = {
            "step_id": f"step_{i+1}",
            "data_source": data_source.name,
            "mcp_tools": [tool.model_dump() for tool in data_source.mcp_tools],
            "required": data_source.required,
            "estimated_time": sum(tool.timeout for tool in data_source.mcp_tools),
            "depends_on": [] if parallel_execution else [f"step_{i}"] if i > 0 else [],
        }
        
        steps.append(step)
        
        if parallel_execution:
            total_estimated_time = max(total_estimated_time, step["estimated_time"])
        else:
            total_estimated_time += step["estimated_time"]
    
    # Determine complexity
    complexity = determine_complexity(data_sources, intent)
    
    return ExecutionPlan(
        plan_id=plan_id,
        steps=steps,
        estimated_time=total_estimated_time,
        complexity=complexity,
        parallel_execution=parallel_execution,
    )


def build_tool_arguments(
    tool_config: Dict[str, Any],
    intent: Dict[str, Any],
    entities: Dict[str, Any],
    filters: Dict[str, Any]
) -> Dict[str, Any]:
    """Build arguments for MCP tool call."""
    arguments = {}
    
    # Add base arguments from tool config
    if "default_args" in tool_config:
        arguments.update(tool_config["default_args"])
    
    # Map intent fields to tool arguments
    argument_mapping = tool_config.get("argument_mapping", {})
    
    for arg_name, mapping in argument_mapping.items():
        if mapping["source"] == "intent":
            value = intent.get(mapping["field"])
        elif mapping["source"] == "entities":
            value = entities.get(mapping["field"])
        elif mapping["source"] == "filters":
            value = filters.get(mapping["field"])
        else:
            continue
        
        if value is not None:
            # Apply transformation if specified
            if "transform" in mapping:
                value = apply_argument_transform(value, mapping["transform"])
            
            arguments[arg_name] = value
    
    # Add time range if specified
    time_range = intent.get("time_range")
    if time_range and time_range.get("type") != "none":
        arguments.update(format_time_range_for_tool(time_range))
    
    return arguments


def apply_argument_transform(value: Any, transform: str) -> Any:
    """Apply transformation to argument value."""
    if transform == "lowercase":
        return str(value).lower()
    elif transform == "uppercase":
        return str(value).upper()
    elif transform == "list":
        return [value] if not isinstance(value, list) else value
    elif transform == "string":
        return str(value)
    elif transform == "int":
        return int(value)
    elif transform == "float":
        return float(value)
    else:
        return value


def format_time_range_for_tool(time_range: Dict[str, Any]) -> Dict[str, Any]:
    """Format time range for MCP tool arguments."""
    from datetime import datetime, timedelta
    
    time_args = {}
    
    if time_range.get("type") == "relative":
        # Handle relative time ranges
        pattern = time_range.get("pattern", "")
        
        if "today" in pattern:
            start_date = datetime.utcnow().replace(hour=0, minute=0, second=0)
            end_date = datetime.utcnow()
        elif "yesterday" in pattern:
            start_date = datetime.utcnow() - timedelta(days=1)
            start_date = start_date.replace(hour=0, minute=0, second=0)
            end_date = start_date.replace(hour=23, minute=59, second=59)
        elif "week" in pattern:
            days_back = 7 if "last week" in pattern else 0
            start_date = datetime.utcnow() - timedelta(days=days_back, weeks=1)
            end_date = datetime.utcnow()
        elif "month" in pattern:
            months_back = 1 if "last month" in pattern else 0
            start_date = datetime.utcnow() - timedelta(days=months_back * 30)
            end_date = datetime.utcnow()
        else:
            # Default to last 7 days
            start_date = datetime.utcnow() - timedelta(days=7)
            end_date = datetime.utcnow()
        
        time_args["start_date"] = start_date.isoformat()
        time_args["end_date"] = end_date.isoformat()
    
    elif time_range.get("type") == "absolute":
        if "start_date" in time_range:
            time_args["start_date"] = time_range["start_date"]
        if "end_date" in time_range:
            time_args["end_date"] = time_range["end_date"]
    
    elif time_range.get("type") == "duration":
        value = time_range.get("value", 7)
        unit = time_range.get("unit", "days")
        
        end_date = datetime.utcnow()
        
        if unit == "days":
            start_date = end_date - timedelta(days=value)
        elif unit == "weeks":
            start_date = end_date - timedelta(weeks=value)
        elif unit == "months":
            start_date = end_date - timedelta(days=value * 30)
        else:
            start_date = end_date - timedelta(days=7)  # Default
        
        time_args["start_date"] = start_date.isoformat()
        time_args["end_date"] = end_date.isoformat()
    
    return time_args


def determine_complexity(data_sources: List[DataSource], intent: Dict[str, Any]) -> str:
    """Determine query complexity based on data sources and intent."""
    total_tools = sum(len(ds.mcp_tools) for ds in data_sources)
    source_count = len(data_sources)
    
    # Consider filters and entities
    entities_count = len(intent.get("entities", {}))
    filters_count = len(intent.get("filters", {}))
    
    complexity_score = (
        total_tools * 2 +
        source_count * 3 +
        entities_count +
        filters_count
    )
    
    if complexity_score <= 5:
        return "simple"
    elif complexity_score <= 15:
        return "medium"
    else:
        return "complex"


def validate_execution_plan(plan: ExecutionPlan) -> Dict[str, Any]:
    """Validate execution plan for feasibility."""
    
    # Check if plan has steps
    if not plan.steps:
        return {"valid": False, "reason": "No execution steps defined"}
    
    # Check estimated time
    if plan.estimated_time > 300:  # 5 minutes
        return {"valid": False, "reason": "Query estimated to take too long"}
    
    # Check for circular dependencies
    step_ids = {step["step_id"] for step in plan.steps}
    for step in plan.steps:
        for dep in step.get("depends_on", []):
            if dep not in step_ids:
                return {"valid": False, "reason": f"Invalid dependency: {dep}"}
    
    # Check for required steps
    required_steps = [step for step in plan.steps if step.get("required", True)]
    if not required_steps:
        return {"valid": False, "reason": "No required execution steps"}
    
    return {"valid": True, "reason": "Plan is valid"}