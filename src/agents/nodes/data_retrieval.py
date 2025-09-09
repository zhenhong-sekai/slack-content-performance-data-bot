"""Data retrieval node implementation."""

import asyncio
import json
import time
from typing import Any, Dict, List

from src.agents.state import AgentState, ExecutionPlan, DataSource
from src.services.mcp_client import get_mcp_client, get_circuit_breaker, MCPError
from src.utils.logging import get_logger

logger = get_logger(__name__)


async def execute_data_retrieval_node(state: AgentState) -> AgentState:
    """Execute MCP calls to retrieve data."""
    execution_plan = state.get("execution_plan")
    data_sources = state.get("data_sources")
    user_id = state.get("user_id")
    
    if not execution_plan or not data_sources:
        return {
            **state,
            "error": "No execution plan or data sources available for retrieval",
        }
    
    plan = ExecutionPlan.model_validate(execution_plan)
    
    logger.info(
        "Starting data retrieval",
        plan_id=plan.plan_id,
        steps_count=len(plan.steps),
        parallel_execution=plan.parallel_execution,
        user_id=user_id,
    )
    
    # Add processing step
    processing_steps = list(state.get("processing_steps", []))
    processing_steps.append("data_retrieval")
    
    start_time = time.time()
    
    try:
        # Execute the plan
        if plan.parallel_execution:
            results = await execute_parallel_plan(plan)
        else:
            results = await execute_sequential_plan(plan)
        
        execution_time = time.time() - start_time
        
        # Validate results
        validation_result = validate_retrieval_results(results)
        if not validation_result["valid"]:
            return {
                **state,
                "error": f"Data retrieval validation failed: {validation_result['reason']}",
                "processing_steps": processing_steps,
            }
        
        logger.info(
            "Data retrieval completed",
            plan_id=plan.plan_id,
            execution_time=round(execution_time, 2),
            successful_steps=len([r for r in results.values() if r.get("success", False)]),
            total_steps=len(plan.steps),
        )
        
        return {
            **state,
            "mcp_results": results,
            "processing_steps": processing_steps,
        }
        
    except Exception as e:
        execution_time = time.time() - start_time
        
        logger.error(
            "Data retrieval failed",
            plan_id=plan.plan_id,
            execution_time=round(execution_time, 2),
            error=str(e),
            exc_info=True,
        )
        
        return {
            **state,
            "error": f"Data retrieval failed: {str(e)}",
            "processing_steps": processing_steps,
        }


async def execute_parallel_plan(plan: ExecutionPlan) -> Dict[str, Any]:
    """Execute plan steps in parallel."""
    
    logger.info("Executing parallel plan", plan_id=plan.plan_id)
    
    # Create tasks for all steps
    tasks = []
    step_mapping = {}
    
    for step in plan.steps:
        task = asyncio.create_task(execute_step(step))
        tasks.append(task)
        step_mapping[task] = step["step_id"]
    
    # Wait for all tasks to complete
    results = {}
    completed_tasks = await asyncio.gather(*tasks, return_exceptions=True)
    
    for task, result in zip(tasks, completed_tasks):
        step_id = step_mapping[task]
        
        if isinstance(result, Exception):
            results[step_id] = {
                "success": False,
                "error": str(result),
                "data": None,
            }
        else:
            results[step_id] = result
    
    return results


async def execute_sequential_plan(plan: ExecutionPlan) -> Dict[str, Any]:
    """Execute plan steps sequentially."""
    
    logger.info("Executing sequential plan", plan_id=plan.plan_id)
    
    results = {}
    
    for step in plan.steps:
        step_id = step["step_id"]
        
        # Check dependencies
        if not check_dependencies(step, results):
            results[step_id] = {
                "success": False,
                "error": "Dependencies not met",
                "data": None,
            }
            
            # If required step failed, stop execution
            if step.get("required", True):
                break
            
            continue
        
        # Execute step
        try:
            result = await execute_step(step)
            results[step_id] = result
            
            # If required step failed, stop execution
            if step.get("required", True) and not result.get("success", False):
                break
                
        except Exception as e:
            results[step_id] = {
                "success": False,
                "error": str(e),
                "data": None,
            }
            
            # If required step failed, stop execution
            if step.get("required", True):
                break
    
    return results


async def execute_step(step: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a single plan step."""
    
    step_id = step["step_id"]
    data_source = step["data_source"]
    mcp_tools = step["mcp_tools"]
    
    logger.info(
        "Executing step",
        step_id=step_id,
        data_source=data_source,
        tool_count=len(mcp_tools),
    )
    
    step_start_time = time.time()
    step_results = {}
    
    # Get MCP client and circuit breaker
    mcp_client = get_mcp_client()
    circuit_breaker = get_circuit_breaker()
    
    try:
        async with mcp_client:
            # Execute all MCP tool calls for this step
            for tool_call in mcp_tools:
                tool_name = tool_call["tool_name"]
                arguments = tool_call["arguments"]
                timeout = tool_call.get("timeout", 30)
                retry_count = tool_call.get("retry_count", 3)
                
                try:
                    # Execute with circuit breaker protection
                    tool_result = await circuit_breaker.call(
                        mcp_client.call_tool,
                        tool_name=tool_name,
                        arguments=arguments,
                        timeout=timeout,
                        retry_count=retry_count,
                    )
                    
                    step_results[tool_name] = {
                        "success": True,
                        "data": tool_result,
                        "arguments": arguments,
                    }
                    
                    logger.info(
                        "MCP tool completed",
                        step_id=step_id,
                        tool_name=tool_name,
                        data_size=len(json.dumps(tool_result)) if tool_result else 0,
                    )
                    
                except MCPError as e:
                    step_results[tool_name] = {
                        "success": False,
                        "error": str(e),
                        "arguments": arguments,
                    }
                    
                    logger.error(
                        "MCP tool failed",
                        step_id=step_id,
                        tool_name=tool_name,
                        error=str(e),
                    )
        
        execution_time = time.time() - step_start_time
        
        # Determine step success
        successful_tools = [r for r in step_results.values() if r.get("success", False)]
        step_success = len(successful_tools) > 0
        
        return {
            "success": step_success,
            "data": step_results,
            "execution_time": round(execution_time, 2),
            "tool_results": len(step_results),
            "successful_tools": len(successful_tools),
        }
        
    except Exception as e:
        execution_time = time.time() - step_start_time
        
        logger.error(
            "Step execution failed",
            step_id=step_id,
            data_source=data_source,
            execution_time=round(execution_time, 2),
            error=str(e),
            exc_info=True,
        )
        
        return {
            "success": False,
            "error": str(e),
            "execution_time": round(execution_time, 2),
            "data": step_results,
        }


def check_dependencies(step: Dict[str, Any], results: Dict[str, Any]) -> bool:
    """Check if step dependencies are satisfied."""
    
    dependencies = step.get("depends_on", [])
    
    for dep_step_id in dependencies:
        if dep_step_id not in results:
            logger.warning(
                "Dependency not found",
                step_id=step["step_id"],
                dependency=dep_step_id,
            )
            return False
        
        dep_result = results[dep_step_id]
        if not dep_result.get("success", False):
            logger.warning(
                "Dependency failed",
                step_id=step["step_id"],
                dependency=dep_step_id,
                error=dep_result.get("error"),
            )
            return False
    
    return True


def validate_retrieval_results(results: Dict[str, Any]) -> Dict[str, Any]:
    """Validate data retrieval results."""
    
    if not results:
        return {"valid": False, "reason": "No results returned"}
    
    # Check if at least one step succeeded
    successful_steps = [
        step_id for step_id, result in results.items()
        if result.get("success", False)
    ]
    
    if not successful_steps:
        return {"valid": False, "reason": "No steps completed successfully"}
    
    # Check if we have actual data
    has_data = False
    for step_id, result in results.items():
        if result.get("success", False) and result.get("data"):
            step_data = result["data"]
            if isinstance(step_data, dict):
                for tool_result in step_data.values():
                    if tool_result.get("success", False) and tool_result.get("data"):
                        has_data = True
                        break
            if has_data:
                break
    
    if not has_data:
        return {"valid": False, "reason": "No data found in results"}
    
    return {"valid": True, "reason": "Results are valid"}


async def test_mcp_connectivity() -> Dict[str, Any]:
    """Test connectivity to MCP server."""
    
    logger.info("Testing MCP connectivity")
    
    mcp_client = get_mcp_client()
    
    try:
        async with mcp_client:
            # Test health check
            health = await mcp_client.check_health()
            
            # Test listing tools
            tools = await mcp_client.list_tools()
            
            return {
                "success": True,
                "health": health,
                "tools_count": len(tools),
                "available_tools": [tool.get("name") for tool in tools],
            }
    
    except Exception as e:
        logger.error("MCP connectivity test failed", error=str(e))
        return {
            "success": False,
            "error": str(e),
        }