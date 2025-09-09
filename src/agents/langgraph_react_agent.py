"""Modern LangGraph ReAct agent with MCP tools and structured outputs."""

import asyncio
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Annotated, Literal
from typing_extensions import TypedDict

import pandas as pd
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from src.config import settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


class DataProcessingResult(BaseModel):
    """Result of data processing operation."""
    success: bool = Field(description="Whether the operation was successful")
    row_count: int = Field(default=0, description="Number of rows processed")
    columns: List[str] = Field(default=[], description="Column names in the result")
    csv_filename: Optional[str] = Field(default=None, description="Generated CSV filename")
    error_message: Optional[str] = Field(default=None, description="Error message if failed")


# Define the agent state
class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    processing_result: Optional[DataProcessingResult]
    error: Optional[str]
    user_id: str
    channel_id: str
    thread_ts: Optional[str]


# Create MCP tools using direct function definitions
async def list_tables_func() -> str:
    """List available tables in BigQuery."""
    try:
        client = MultiServerMCPClient({
            "bigquery_sse": {
                "url": settings.mcp_server_url,
                "transport": "streamable_http",
            }
        })
        
        tools = await client.get_tools()
        list_tables_tool = None
        
        for tool_obj in tools:
            if hasattr(tool_obj, 'name') and tool_obj.name == 'list_tables':
                list_tables_tool = tool_obj
                break
        
        if list_tables_tool:
            result = await list_tables_tool.ainvoke({})
            return str(result)
        else:
            return "list_tables tool not found in MCP server"
            
    except Exception as e:
        logger.error("Failed to list tables", error=str(e))
        return f"Error listing tables: {str(e)}"


async def describe_table_func(table_name: str) -> str:
    """Describe the structure of a specific table.
    
    Args:
        table_name: Name of the table to describe
    """
    try:
        client = MultiServerMCPClient({
            "bigquery_sse": {
                "url": settings.mcp_server_url,
                "transport": "streamable_http",
            }
        })
        
        tools = await client.get_tools()
        describe_tool = None
        
        for tool_obj in tools:
            if hasattr(tool_obj, 'name') and tool_obj.name == 'describe_table':
                describe_tool = tool_obj
                break
        
        if describe_tool:
            result = await describe_tool.ainvoke({"table_name": table_name})
            return str(result)
        else:
            return "describe_table tool not found in MCP server"
            
    except Exception as e:
        logger.error("Failed to describe table", table_name=table_name, error=str(e))
        return f"Error describing table {table_name}: {str(e)}"


async def execute_query_func(sql_query: str) -> str:
    """Execute a SQL query against BigQuery.
    
    Args:
        sql_query: The SQL query to execute
    """
    try:
        client = MultiServerMCPClient({
            "bigquery_sse": {
                "url": settings.mcp_server_url,
                "transport": "streamable_http",
            }
        })
        
        tools = await client.get_tools()
        execute_tool = None
        
        for tool_obj in tools:
            if hasattr(tool_obj, 'name') and tool_obj.name == 'execute_query':
                execute_tool = tool_obj
                break
        
        if execute_tool:
            result = await execute_tool.ainvoke({"sql_query": sql_query})
            return str(result)
        else:
            return "execute_query tool not found in MCP server"
            
    except Exception as e:
        logger.error("Failed to execute query", sql_query=sql_query[:100], error=str(e))
        
        # Auto-fix datetime serialization issues
        if "not JSON serializable" in str(e) and "datetime" in str(e):
            logger.info("Attempting to fix datetime serialization issue")
            
            # Common datetime column names to fix
            datetime_columns = ['event_timestamp', 'created_at', 'updated_at', 'timestamp', 'date']
            
            fixed_query = sql_query
            for col in datetime_columns:
                if col in sql_query.lower():
                    # Replace with CAST AS STRING
                    import re
                    pattern = rf'\b{col}\b'
                    replacement = f'CAST({col} AS STRING) AS {col}'
                    fixed_query = re.sub(pattern, replacement, fixed_query, flags=re.IGNORECASE)
            
            if fixed_query != sql_query:
                logger.info("Retrying query with datetime casting", original=sql_query[:100], fixed=fixed_query[:100])
                try:
                    result = await execute_tool.ainvoke({"sql_query": fixed_query})
                    return str(result)
                except Exception as retry_error:
                    logger.error("Fixed query also failed", error=str(retry_error))
                    return f"Query failed even after datetime fix: {str(retry_error)}"
        
        return f"Error executing query: {str(e)}"

# Create tool objects manually
from langchain_core.tools import Tool, StructuredTool

list_tables = StructuredTool.from_function(
    func=list_tables_func,
    name="list_tables",
    description="List available tables in BigQuery"
)

describe_table = StructuredTool.from_function(
    func=describe_table_func,
    name="describe_table", 
    description="Describe the structure of a specific table"
)

execute_query = StructuredTool.from_function(
    func=execute_query_func,
    name="execute_query",
    description="Execute a SQL query against BigQuery"
)


@tool
def save_as_csv(json_data: str) -> str:
    """Save JSON data as CSV file for download.
    
    Args:
        json_data: JSON string containing the data to save
    """
    try:
        logger.info("Creating CSV file", data_preview=json_data[:200])
        
        # Parse JSON data
        data = json.loads(json_data)
        
        # Handle different data structures
        df = None
        if isinstance(data, list):
            if data:
                df = pd.DataFrame(data)
            else:
                return "No data to save - empty result set"
        elif isinstance(data, dict):
            if "error" in data:
                return f"Cannot create CSV: {data.get('error', 'Unknown error')}"
            if "rows" in data:
                if data["rows"]:
                    df = pd.DataFrame(data["rows"])
                else:
                    return "No data to save - empty result set"
            elif "data" in data:
                if data["data"]:
                    df = pd.DataFrame(data["data"])
                else:
                    return "No data to save - empty result set"
            else:
                df = pd.DataFrame([data])
        
        if df is None or df.empty:
            return "No data to save - empty result set"
        
        # Create CSV file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"query_results_{timestamp}.csv"
        temp_dir = settings.temp_file_path
        os.makedirs(temp_dir, exist_ok=True)
        
        filepath = os.path.join(temp_dir, filename)
        df.to_csv(filepath, index=False)
        
        logger.info("CSV file created", filename=filename, rows=len(df), columns=len(df.columns))
        
        return f"SUCCESS: Created {filename} with {len(df)} rows and {len(df.columns)} columns"
        
    except Exception as e:
        error_msg = f"Failed to create CSV: {str(e)}"
        logger.error("CSV creation failed", error=error_msg)
        return error_msg


# Define the ReAct agent
class LangGraphReActAgent:
    """Modern LangGraph ReAct agent with structured outputs."""
    
    def __init__(self):
        self.llm = ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            temperature=0.1,
        )
        
        
        # Define tools
        self.tools = [list_tables, describe_table, execute_query, save_as_csv]
        self.tool_map = {tool.name: tool for tool in self.tools}
        
        # Build the graph
        self.graph = self._build_graph()
    
    def _build_graph(self) -> StateGraph:
        """Build the ReAct agent graph."""
        workflow = StateGraph(AgentState)
        
        # Add nodes
        workflow.add_node("agent", self._agent_node)
        workflow.add_node("tools", self._execute_tools)
        workflow.add_node("process_results", self._process_results)
        
        # Add edges
        workflow.add_edge(START, "agent")
        workflow.add_conditional_edges(
            "agent",
            self._should_continue,
            {
                "continue": "tools",
                "process": "process_results",
                "end": END,
            },
        )
        workflow.add_edge("tools", "agent")
        workflow.add_edge("process_results", END)
        
        return workflow.compile()
    
    async def _agent_node(self, state: AgentState) -> AgentState:
        """Main agent reasoning node."""
        try:
            system_prompt = """You are OptiBot, a BigQuery data assistant.

CRITICAL RULES:
1. ALWAYS use tools in this order for data queries:
   - list_tables: See available tables
   - describe_table: Understand table structure  
   - execute_query: Get the actual data
   - save_as_csv: Create downloadable file (MANDATORY for all data requests)

2. DATETIME FIX PROTOCOL:
   If execute_query fails with "datetime is not JSON serializable":
   - Identify datetime columns: event_timestamp, created_at, updated_at, timestamp, date
   - Use CAST(column AS STRING) AS column format
   - Example: SELECT user_id, CAST(event_timestamp AS STRING) AS event_timestamp FROM table

3. CSV REQUIREMENT:
   - ONLY call save_as_csv when execute_query returns actual data (not empty results)
   - Pass the EXACT JSON returned by execute_query to save_as_csv
   - Do NOT call save_as_csv for empty results or errors

4. ERROR HANDLING:
   - If tools fail, explain the issue clearly
   - Provide helpful suggestions for fixing queries
   - Always be professional and helpful

Available tools: list_tables, describe_table, execute_query, save_as_csv
"""
            
            # Get the LLM with tool calling
            llm_with_tools = self.llm.bind_tools(self.tools)
            
            # Create messages for the LLM
            messages = [HumanMessage(content=system_prompt)] + state["messages"]
            
            # Get response
            response = await llm_with_tools.ainvoke(messages)
            
            # Add to messages
            state["messages"].append(response)
            
        except Exception as e:
            logger.error("Agent node failed", error=str(e))
            state["error"] = f"Agent reasoning failed: {str(e)}"
        
        return state
    
    async def _execute_tools(self, state: AgentState) -> AgentState:
        """Execute tool calls from the agent."""
        try:
            last_message = state["messages"][-1]
            
            if not hasattr(last_message, 'tool_calls') or not last_message.tool_calls:
                logger.warning("No tool calls found in last message")
                return state
            
            # Execute each tool call
            for tool_call in last_message.tool_calls:
                tool_name = tool_call["name"]
                tool_args = tool_call["args"]
                tool_id = tool_call["id"]
                
                logger.info("Executing tool", tool_name=tool_name, args=str(tool_args)[:100])
                
                if tool_name in self.tool_map:
                    tool = self.tool_map[tool_name]
                    try:
                        # Execute the tool
                        if hasattr(tool, 'ainvoke'):
                            result = await tool.ainvoke(tool_args)
                        elif asyncio.iscoroutinefunction(tool.func):
                            result = await tool.func(**tool_args)
                        else:
                            result = tool.func(**tool_args)
                        
                        # Add tool message
                        tool_message = ToolMessage(
                            content=str(result),
                            tool_call_id=tool_id,
                            name=tool_name
                        )
                        state["messages"].append(tool_message)
                        
                        logger.info("Tool executed successfully", 
                                   tool_name=tool_name, 
                                   result_preview=str(result)[:200])
                        
                    except Exception as e:
                        error_msg = f"Tool {tool_name} failed: {str(e)}"
                        logger.error("Tool execution failed", 
                                   tool_name=tool_name, 
                                   error=str(e))
                        
                        tool_message = ToolMessage(
                            content=error_msg,
                            tool_call_id=tool_id,
                            name=tool_name
                        )
                        state["messages"].append(tool_message)
                else:
                    error_msg = f"Unknown tool: {tool_name}"
                    logger.error("Unknown tool requested", tool_name=tool_name)
                    
                    tool_message = ToolMessage(
                        content=error_msg,
                        tool_call_id=tool_id,
                        name=tool_name
                    )
                    state["messages"].append(tool_message)
            
        except Exception as e:
            logger.error("Tool execution node failed", error=str(e))
            state["error"] = f"Tool execution failed: {str(e)}"
        
        return state
    
    def _should_continue(self, state: AgentState) -> str:
        """Decide whether to continue with tools, process results, or end."""
        if state.get("error"):
            return "end"
        
        last_message = state["messages"][-1]
        
        # If the last message has tool calls, continue with tools
        if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
            return "continue"
        
        # If we have data from execute_query, process results
        if any("SUCCESS: Created" in str(msg.content) for msg in state["messages"] 
               if isinstance(msg, ToolMessage)):
            return "process"
        
        # Otherwise, end
        return "end"
    
    async def _process_results(self, state: AgentState) -> AgentState:
        """Process the final results and prepare response."""
        try:
            # Look for CSV creation success messages
            csv_messages = [
                msg for msg in state["messages"] 
                if isinstance(msg, ToolMessage) and "SUCCESS: Created" in str(msg.content)
            ]
            
            if csv_messages:
                # Extract filename and details from the last successful CSV creation
                last_csv_msg = csv_messages[-1]
                content = str(last_csv_msg.content)
                
                # Parse the success message to extract details
                import re
                filename_match = re.search(r'Created (\S+\.csv)', content)
                rows_match = re.search(r'with (\d+) rows', content)
                cols_match = re.search(r'and (\d+) columns', content)
                
                result = DataProcessingResult(
                    success=True,
                    csv_filename=filename_match.group(1) if filename_match else "unknown.csv",
                    row_count=int(rows_match.group(1)) if rows_match else 0,
                    columns=[],  # Could extract from describe_table if needed
                )
                
                state["processing_result"] = result
                
                # Add final success message
                success_msg = f"✅ Query completed successfully! Created CSV file with {result.row_count} rows."
                state["messages"].append(AIMessage(content=success_msg))
                
            else:
                # No CSV was created - check for other successful operations
                state["processing_result"] = DataProcessingResult(
                    success=True,
                    error_message="Query completed but no data file was generated"
                )
                
                state["messages"].append(AIMessage(content="Query completed, but no data was available to download."))
        
        except Exception as e:
            logger.error("Result processing failed", error=str(e))
            state["error"] = f"Failed to process results: {str(e)}"
        
        return state
    
    async def process_query(self, query: str, user_id: str, channel_id: str = "", thread_ts: str = None) -> Dict[str, Any]:
        """Process a user query through the ReAct agent."""
        logger.info("Processing query with LangGraph ReAct agent", 
                   query=query[:100], user_id=user_id)
        
        try:
            # Create initial state
            initial_state = AgentState(
                messages=[HumanMessage(content=query)],
                processing_result=None,
                error=None,
                user_id=user_id,
                channel_id=channel_id,
                thread_ts=thread_ts,
            )
            
            # Run the graph
            final_state = await self.graph.ainvoke(initial_state)
            
            # Extract results
            if final_state.get("error"):
                return {
                    "success": False,
                    "response": f"I encountered an error: {final_state['error']}",
                    "csv_files": [],
                    "error": final_state["error"]
                }
            
            # Get the final AI message
            ai_messages = [msg for msg in final_state["messages"] if isinstance(msg, AIMessage)]
            final_response = ai_messages[-1].content if ai_messages else "Query completed"
            
            # Check for generated CSV files
            csv_files = self._find_generated_files()
            
            processing_result = final_state.get("processing_result")
            
            logger.info("LangGraph ReAct agent completed",
                       user_id=user_id,
                       success=processing_result.success if processing_result else True,
                       csv_files_count=len(csv_files))
            
            return {
                "success": True,
                "response": final_response,
                "csv_files": csv_files,
                "error": None
            }
            
        except Exception as e:
            logger.error("LangGraph ReAct agent failed",
                        query=query[:100],
                        user_id=user_id,
                        error=str(e),
                        exc_info=True)
            
            return {
                "success": False,
                "response": f"I encountered an error: {str(e)}",
                "csv_files": [],
                "error": str(e)
            }
    
    def _find_generated_files(self) -> List[Dict[str, str]]:
        """Find recently created CSV files."""
        try:
            temp_dir = settings.temp_file_path
            if not os.path.exists(temp_dir):
                return []
            
            files = []
            cutoff = datetime.now().timestamp() - 300  # 5 minutes ago
            
            for filename in os.listdir(temp_dir):
                if filename.endswith('.csv'):
                    filepath = os.path.join(temp_dir, filename)
                    if os.path.getmtime(filepath) > cutoff:
                        files.append({
                            "filepath": filepath,
                            "filename": filename,
                            "size": os.path.getsize(filepath)
                        })
            
            return files
            
        except Exception as e:
            logger.error("Failed to find generated files", error=str(e))
            return []


# Global instance
_react_agent: Optional[LangGraphReActAgent] = None


async def get_langgraph_react_agent() -> LangGraphReActAgent:
    """Get or create LangGraph ReAct agent."""
    global _react_agent
    
    if _react_agent is None:
        _react_agent = LangGraphReActAgent()
    
    return _react_agent