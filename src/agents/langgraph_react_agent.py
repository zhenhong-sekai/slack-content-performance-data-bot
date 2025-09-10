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
# from langgraph.prebuilt import ToolNode  # Temporarily disabled due to version compatibility
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


# Global MCP client instance
_mcp_client: Optional[MultiServerMCPClient] = None


async def get_mcp_client() -> MultiServerMCPClient:
    """Get or create MCP client instance with proper connection to BigQuery server."""
    global _mcp_client
    
    if _mcp_client is None:
        logger.info("Initializing MCP client", server_url=settings.mcp_server_url)
        _mcp_client = MultiServerMCPClient({
            "bigquery": {
                "url": settings.mcp_server_url,
                "transport": "streamable_http",
            }
        })
        
        # Test connection and log available tools
        try:
            tools = await _mcp_client.get_tools()
            tool_names = [tool.name for tool in tools if hasattr(tool, 'name')]
            logger.info("MCP client initialized successfully", 
                       server_url=settings.mcp_server_url,
                       available_tools=tool_names)
        except Exception as e:
            logger.error("Failed to connect to MCP server", 
                        server_url=settings.mcp_server_url, 
                        error=str(e))
            raise
    
    return _mcp_client


def save_as_csv_local(data: Any, filename: str) -> Dict[str, Any]:
    """Save data as CSV file locally."""
    try:
        logger.info("Creating CSV file", filename=filename)
        
        # Create CSV file
        temp_dir = settings.temp_file_path
        os.makedirs(temp_dir, exist_ok=True)
        
        filepath = os.path.join(temp_dir, filename)
        
        # Handle different data structures
        df = None
        if isinstance(data, pd.DataFrame):
            df = data
        elif isinstance(data, list):
            if data:
                df = pd.DataFrame(data)
            else:
                return {"success": False, "error": "No data to save - empty result set"}
        elif isinstance(data, dict):
            if "error" in data:
                return {"success": False, "error": f"Cannot create CSV: {data.get('error', 'Unknown error')}"}
            if "rows" in data:
                if data["rows"]:
                    df = pd.DataFrame(data["rows"])
                else:
                    return {"success": False, "error": "No data to save - empty result set"}
            elif "data" in data:
                if data["data"]:
                    df = pd.DataFrame(data["data"])
                else:
                    return {"success": False, "error": "No data to save - empty result set"}
            else:
                df = pd.DataFrame([data])
        
        if df is None or df.empty:
            return {"success": False, "error": "No data to save - empty result set"}
        
        # Save to CSV
        df.to_csv(filepath, index=False)
        
        logger.info("CSV file created", filename=filename, rows=len(df), columns=len(df.columns))
        
        return {
            "success": True,
            "filename": filename,
            "filepath": filepath,
            "rows": len(df),
            "columns": list(df.columns)
        }
        
    except Exception as e:
        error_msg = f"Failed to create CSV: {str(e)}"
        logger.error("CSV creation failed", error=error_msg)
        return {"success": False, "error": error_msg}


@tool
def save_as_csv(json_data: str) -> str:
    """Save JSON data as CSV file for download.
    
    Args:
        json_data: JSON string containing the data to save as CSV
    """
    try:
        import json
        logger.info("Creating CSV file from JSON data", data_preview=json_data[:200])
        
        # Parse JSON data
        data = json.loads(json_data)
        
        # Create filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"query_results_{timestamp}.csv"
        
        # Use the local CSV creation function
        result = save_as_csv_local(data, filename)
        
        if result["success"]:
            return f"SUCCESS: Created {result['filename']} with {result['rows']} rows and {len(result['columns'])} columns"
        else:
            return f"ERROR: {result['error']}"
        
    except Exception as e:
        error_msg = f"Failed to create CSV: {str(e)}"
        logger.error("CSV tool failed", error=error_msg)
        return error_msg


# Define the ReAct agent
class LangGraphReActAgent:
    """Modern LangGraph ReAct agent with MCP tools integration."""
    
    def __init__(self):
        self.llm = ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            temperature=0.1,
        )
        
        # MCP client will be initialized async
        self.mcp_client = None
        self.tools = []
        self.tool_node = None
        self.graph = None
    
    async def initialize(self):
        """Initialize MCP client and build the graph."""
        try:
            # Get MCP client with discovered tools
            self.mcp_client = await get_mcp_client()
            mcp_tools = await self.mcp_client.get_tools()
            
            # Combine MCP tools with local CSV tool
            self.tools = list(mcp_tools) + [save_as_csv]
            
            # Create tool execution function (custom implementation due to version compatibility)
            self.tool_node = self._execute_mcp_tools
            
            # Build the graph
            self.graph = await self._build_graph()
            
            logger.info("LangGraph ReAct agent initialized", 
                       tool_count=len(self.tools),
                       tool_names=[tool.name for tool in self.tools if hasattr(tool, 'name')])
            
        except Exception as e:
            logger.error("Failed to initialize LangGraph ReAct agent", error=str(e))
            raise
    
    async def _build_graph(self) -> StateGraph:
        """Build the ReAct agent graph with MCP tools."""
        workflow = StateGraph(AgentState)
        
        # Create the agent node with MCP tools bound to LLM
        llm_with_tools = self.llm.bind_tools(self.tools)
        
        # Add nodes
        workflow.add_node("agent", self._agent_node)
        workflow.add_node("tools", self.tool_node)  # Use LangGraph's ToolNode with MCP tools
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
        """Main agent reasoning node with MCP tools."""
        try:
            # Get tool names dynamically from MCP
            tool_names = [tool.name for tool in self.tools if hasattr(tool, 'name')]
            
            system_prompt = f"""You are OptiBot, a BigQuery data assistant with access to MCP tools.

CRITICAL WORKFLOW:
1. FIRST: Parse user query and COUNT all content IDs mentioned (e.g., "798651, 1028967, 1028956" = 3 IDs)
2. For data queries, follow this sequence:
   - First: List available tables to understand what data is available
   - Then: Describe relevant table structures 
   - Next: Execute SQL queries INCLUDING ALL CONTENT IDs - never skip any!
   - MANDATORY: Use save_as_csv tool to convert JSON results to downloadable CSV file
   
BEFORE WRITING SQL: Count content IDs in user request and ensure your WHERE clause includes ALL of them!

CONTENT ID VALIDATION:
- Use EXACT content IDs from user request - never modify, truncate, or guess them
- For analytics tables: contentId is STRING, use quotes: IN ('943625', '939354')
- For events table: sekai_id is INTEGER, no quotes: IN (943625, 939354)
- If query returns empty results, check BOTH data sources before concluding no data exists

2. DATETIME SERIALIZATION FIX:
   If you get "Object of type datetime is not JSON serializable" error:
   - CAST all datetime columns to STRING in your SQL
   - Common datetime columns: created_at, updated_at, timestamp, date, event_timestamp
   - Example: SELECT CAST(created_at AS STRING) AS created_at, other_columns FROM table
   - ALWAYS use CAST(datetime_column AS STRING) AS datetime_column format

3. ALWAYS be helpful and provide clear explanations of what you're doing.

4. CSV CREATION RULE:
   - WHENEVER execute_query returns JSON data (even small amounts), you MUST call save_as_csv
   - Pass the EXACT JSON string returned by execute_query to save_as_csv tool
   - Do NOT skip CSV creation - users always want downloadable files
   - Example: If execute_query returns JSON like [{{"user_id": 123, "event": "like"}}], call save_as_csv with that JSON

5. ERROR HANDLING:
   - If tools fail, explain the issue clearly
   - Provide helpful suggestions for fixing queries
   - Always be professional and helpful
   - If query returns empty results [], check if:
     * Content IDs are correct and match user request exactly
     * Data exists in other tables (analytics vs events)
     * Date range is appropriate for available tables
     * Table names are correct and exist

TIPS FOR PERFORMANCE DATA:
1. Use dwd.prod_sekai_all_event table for engagement metrics over date ranges
2. Key metrics to aggregate:
   - Daily unique users (COUNT DISTINCT user_id)
   - Chat metrics (event_name = 'chat_sekai')
   - Like metrics (event_name = 'like_sekai')

BIGQUERY CONTENT PERFORMANCE DATA RETRIEVAL:

CRITICAL QUERY RULES:
1. ALWAYS check available tables first using list_tables
2. Use EXACT content IDs provided by user - never modify or guess them
3. Query BOTH data sources: analytics tables AND events table
4. Handle data type differences: contentId (string) vs sekai_id (integer)
5. Check data availability before querying - tables may not exist for recent dates

Table Sources for Content Metrics:
1. analytics_407461028.events_YYYYMMDD - Content-specific impression & click data
2. dwd.prod_sekai_all_event - Chat & like interaction data

QUERY WORKFLOW:
1. First: List available tables to find most recent analytics tables
2. Query analytics tables for impressions/clicks (may return empty results)
3. Query events table for chat/likes (may have data even if analytics don't)
4. Combine results from both sources

Analytics Table Query (Impressions & Clicks):
```sql
SELECT 
  param.value.string_value as content_id,
  COUNT(DISTINCT user_pseudo_id) as daily_users,
  COUNT(DISTINCT CASE WHEN event_name LIKE '%expose%' THEN user_pseudo_id END) as impression_uv,
  COUNT(CASE WHEN event_name LIKE '%expose%' THEN 1 END) as impression_pv,
  COUNT(DISTINCT CASE WHEN event_name LIKE '%click%' THEN user_pseudo_id END) as click_uv,
  COUNT(CASE WHEN event_name LIKE '%click%' THEN 1 END) as click_pv,
  COUNT(DISTINCT CASE WHEN event_name = 'sekai_page_click_send_message' THEN user_pseudo_id END) as chat_uv,
  COUNT(CASE WHEN event_name = 'sekai_page_click_send_message' THEN 1 END) as chat_pv
FROM analytics_407461028.events_YYYYMMDD,
UNNEST(event_params) as param
WHERE param.key = 'contentId'
  AND param.value.string_value IS NOT NULL
  AND param.value.string_value != ''
  AND param.value.string_value IN ('CONTENT_IDS_HERE')
GROUP BY content_id
ORDER BY content_id
```

Event Data Table Query (Chat & Likes):
```sql
SELECT 
  sekai_id,
  COUNT(DISTINCT user_id) as daily_users,
  COUNT(DISTINCT CASE WHEN event_name = 'chat_sekai' THEN user_id END) as chat_uv,
  COUNT(CASE WHEN event_name = 'chat_sekai' THEN 1 END) as chat_pv,
  COUNT(DISTINCT CASE WHEN event_name = 'like_sekai' THEN user_id END) as like_uv,
  COUNT(CASE WHEN event_name = 'like_sekai' THEN 1 END) as like_pv
FROM dwd.prod_sekai_all_event
WHERE sekai_id IN (CONTENT_IDS_HERE)
  AND DATE(event_timestamp) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY sekai_id
ORDER BY sekai_id
```

Key Parameters:
- Analytics: Use contentId (string) from event_params
- Events: Use sekai_id (integer) as direct column
- Date Format: Replace YYYYMMDD with actual date (e.g., 20250830)

Available Event Types:
- Impressions: foryou_page_expose_sekai_card, search_result_page_expose_roleplay, sekai_page_expose
- Clicks: foryou_page_click_sekai_card, sekai_page_click_send_message, sekai_page_click_like
- Chat: chat_sekai, sekai_page_click_send_message
- Likes: like_sekai, sekai_page_click_like

Usage Instructions:
1. Replace CONTENT_IDS_HERE with comma-separated content IDs (use EXACT IDs from user)
2. Replace YYYYMMDD with target date (check available tables first)
3. Run both queries and combine results (even if one returns empty)
4. Use CAST(event_timestamp AS STRING) to avoid datetime serialization errors

EXAMPLE WORKFLOW:
User requests: "Get data for content 943625"
1. list_tables to find available analytics tables
2. Query analytics_407461028.events_20250830 for contentId = '943625' (may return empty)
3. Query dwd.prod_sekai_all_event for sekai_id = 943625 (may have chat data)
4. Combine results showing 0 impressions/clicks, 1 chat PV/UV

AGGREGATION EXAMPLES:

1. Daily Breakdown:
```sql
SELECT 
  FORMAT_DATE('%Y-%m-%d', DATE(event_timestamp)) as date,
  COUNT(DISTINCT user_id) as daily_users,
  COUNT(DISTINCT CASE WHEN event_name = 'chat_sekai' THEN user_id END) as chat_users,
  COUNT(CASE WHEN event_name = 'chat_sekai' THEN 1 END) as chat_count,
  COUNT(DISTINCT CASE WHEN event_name = 'like_sekai' THEN user_id END) as like_users,
  COUNT(CASE WHEN event_name = 'like_sekai' THEN 1 END) as like_count
FROM dwd.prod_sekai_all_event
WHERE sekai_id = [ID]
  AND DATE(event_timestamp) BETWEEN [START_DATE] AND [END_DATE]
GROUP BY 1
ORDER BY date DESC;
```

2. Period Summary:
```sql
SELECT 
  MIN(DATE(event_timestamp)) as period_start,
  MAX(DATE(event_timestamp)) as period_end,
  COUNT(DISTINCT user_id) as total_unique_users,
  COUNT(DISTINCT CASE WHEN event_name = 'chat_sekai' THEN user_id END) as total_chat_users,
  COUNT(CASE WHEN event_name = 'chat_sekai' THEN 1 END) as total_chats,
  COUNT(DISTINCT CASE WHEN event_name = 'like_sekai' THEN user_id END) as total_like_users,
  COUNT(CASE WHEN event_name = 'like_sekai' THEN 1 END) as total_likes,
  ROUND(COUNT(DISTINCT CASE WHEN event_name = 'chat_sekai' THEN user_id END) / 
    COUNT(DISTINCT user_id) * 100, 1) as chat_user_ratio,
  ROUND(COUNT(DISTINCT CASE WHEN event_name = 'like_sekai' THEN user_id END) / 
    COUNT(DISTINCT user_id) * 100, 1) as like_user_ratio
FROM dwd.prod_sekai_all_event
WHERE sekai_id = [ID]
  AND DATE(event_timestamp) BETWEEN [START_DATE] AND [END_DATE];
```

3. Multi-Content Analysis:
```sql
-- For multiple sekai_ids, use IN clause and GROUP BY sekai_id
SELECT 
  sekai_id,
  FORMAT_DATE('%Y-%m-%d', DATE(event_timestamp)) as date,
  COUNT(DISTINCT user_id) as daily_users,
  COUNT(DISTINCT CASE WHEN event_name = 'chat_sekai' THEN user_id END) as chat_users,
  COUNT(CASE WHEN event_name = 'chat_sekai' THEN 1 END) as chat_count,
  COUNT(DISTINCT CASE WHEN event_name = 'like_sekai' THEN user_id END) as like_users,
  COUNT(CASE WHEN event_name = 'like_sekai' THEN 1 END) as like_count
FROM dwd.prod_sekai_all_event
WHERE sekai_id IN (798651, 1028967, 1028956)
  AND DATE(event_timestamp) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY sekai_id, date
ORDER BY sekai_id, date DESC;
```

FEW-SHOT EXAMPLES:

Query: "engagement data for content 798651, 1028967, 1028956 last 7 days"
Response: I'll get engagement data for all three content IDs for the last 7 days.
1. Use IN clause: WHERE sekai_id IN (798651, 1028967, 1028956)
2. Use DATE_SUB for last 7 days: DATE(event_timestamp) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
3. GROUP BY sekai_id, date to separate each content by day

Query: "performance data for content 123456 last 30 days"
Response: I'll get performance data for content 123456 for the last 30 days.
1. Single ID: WHERE sekai_id = 123456
2. Use INTERVAL 30 DAY for date range

Query: "daily breakdown for contents 111, 222, 333"
Response: I'll provide daily breakdown for all three contents.
1. Multiple IDs: WHERE sekai_id IN (111, 222, 333)
2. Include sekai_id in SELECT to distinguish between contents
3. Generate comprehensive daily breakdown with all metrics

CRITICAL MULTI-CONTENT RULES:
- When user provides MULTIPLE content IDs (like 798651, 1028967, 1028956), you MUST include ALL of them
- COUNT all IDs mentioned: If user says "798651, 1028967, 1028956" that's exactly 3 IDs
- VERIFY in your SQL: WHERE sekai_id IN (798651, 1028967, 1028956) - all 3 IDs must be there
- DO NOT truncate or skip any IDs - include every single one mentioned by the user
- Double-check your WHERE clause contains the complete list

EXAMPLE VERIFICATION:
User asks: "data for 798651, 1028967, 1028956, 1234567, 9876543"
Your SQL MUST have: WHERE sekai_id IN (798651, 1028967, 1028956, 1234567, 9876543)
Count: 5 IDs requested = 5 IDs in query ✓

Remember:
- For MULTIPLE content IDs: Use IN clause and include sekai_id in SELECT and GROUP BY
- ALWAYS include ALL content IDs mentioned by the user - never skip any
- For date ranges: Use DATE_SUB(CURRENT_DATE(), INTERVAL X DAY) format
- ALWAYS provide both daily breakdown and period summary for better insights
- Use FORMAT_DATE for datetime columns to avoid serialization errors
- Generate CSV files for both aggregated views

Your available tools from MCP server: {', '.join(tool_names)}
"""
            
            # Get the LLM with MCP tools bound
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
    
    async def _execute_mcp_tools(self, state: AgentState) -> AgentState:
        """Execute MCP tool calls from the agent."""
        try:
            last_message = state["messages"][-1]
            
            if not hasattr(last_message, 'tool_calls') or not last_message.tool_calls:
                logger.warning("No tool calls found in last message")
                return state
            
            # Create a tool map for easy lookup
            tool_map = {tool.name: tool for tool in self.tools if hasattr(tool, 'name')}
            
            # Execute each tool call
            for tool_call in last_message.tool_calls:
                tool_name = tool_call["name"]
                tool_args = tool_call["args"]
                tool_id = tool_call["id"]
                
                # Enhanced logging with full arguments
                logger.info("=== EXECUTING TOOL CALL ===", 
                           tool_name=tool_name, 
                           tool_id=tool_id)
                
                # Log the complete arguments in a readable format
                print(f"\n🔧 TOOL CALL: {tool_name}")
                print(f"📋 TOOL ID: {tool_id}")
                print(f"📝 FULL ARGUMENTS:")
                try:
                    import json
                    formatted_args = json.dumps(tool_args, indent=2, ensure_ascii=False)
                    print(formatted_args)
                except Exception as json_err:
                    print(f"Raw args (JSON formatting failed): {tool_args}")
                print(f"{'='*50}")
                
                logger.info("Tool arguments logged", 
                           tool_name=tool_name,
                           args_preview=str(tool_args)[:200] + "..." if len(str(tool_args)) > 200 else str(tool_args))
                
                if tool_name in tool_map:
                    tool = tool_map[tool_name]
                    try:
                        # Execute the MCP tool
                        if hasattr(tool, 'ainvoke'):
                            result = await tool.ainvoke(tool_args)
                        elif hasattr(tool, 'invoke'):
                            result = tool.invoke(tool_args)
                        else:
                            result = f"Tool {tool_name} is not properly callable"
                        
                        # Add tool message
                        tool_message = ToolMessage(
                            content=str(result),
                            tool_call_id=tool_id,
                            name=tool_name
                        )
                        state["messages"].append(tool_message)
                        
                        logger.info("MCP tool executed successfully", 
                                   tool_name=tool_name, 
                                   result_preview=str(result)[:200])
                        
                        # Print full result for debugging with enhanced formatting
                        print(f"\n✅ TOOL EXECUTION SUCCESS: {tool_name}")
                        print(f"📋 TOOL ID: {tool_id}")
                        print(f"📤 RESULT:")
                        print(f"{'='*50}")
                        print(str(result))
                        print(f"{'='*50}")
                        print(f"📊 RESULT LENGTH: {len(str(result))} characters")
                        print("✨ TOOL EXECUTION COMPLETE\n")
                        
                    except Exception as e:
                        error_msg = f"MCP tool {tool_name} failed: {str(e)}"
                        logger.error("MCP tool execution failed", 
                                   tool_name=tool_name, 
                                   error=str(e))
                        
                        # Enhanced error logging
                        print(f"\n❌ TOOL EXECUTION FAILED: {tool_name}")
                        print(f"📋 TOOL ID: {tool_id}")
                        print(f"❗ ERROR: {str(e)}")
                        print(f"{'='*50}")
                        
                        tool_message = ToolMessage(
                            content=error_msg,
                            tool_call_id=tool_id,
                            name=tool_name
                        )
                        state["messages"].append(tool_message)
                else:
                    error_msg = f"Unknown MCP tool: {tool_name}"
                    logger.error("Unknown MCP tool requested", tool_name=tool_name)
                    
                    # Enhanced unknown tool logging
                    print(f"\n⚠️  UNKNOWN TOOL REQUESTED: {tool_name}")
                    print(f"📋 TOOL ID: {tool_id}")
                    print(f"🔍 AVAILABLE TOOLS: {list(tool_map.keys())}")
                    print(f"{'='*50}")
                    
                    tool_message = ToolMessage(
                        content=error_msg,
                        tool_call_id=tool_id,
                        name=tool_name
                    )
                    state["messages"].append(tool_message)
            
        except Exception as e:
            logger.error("MCP tool execution node failed", error=str(e))
            state["error"] = f"MCP tool execution failed: {str(e)}"
        
        return state
    
    def _should_continue(self, state: AgentState) -> str:
        """Decide whether to continue with tools, process results, or end."""
        if state.get("error"):
            return "end"
        
        last_message = state["messages"][-1]
        
        # If the last message has tool calls, continue with tools
        if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
            return "continue"
        
        # Check for query results that need CSV processing
        tool_messages = [msg for msg in state["messages"] if isinstance(msg, ToolMessage)]
        if tool_messages and any("data" in str(msg.content).lower() for msg in tool_messages):
            return "process"
        
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
            logger.info("CSV file search results", 
                       csv_files_found=len(csv_files),
                       csv_files=csv_files if csv_files else "No CSV files found")
            
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
            logger.info("Searching for CSV files", temp_dir=temp_dir)
            
            if not os.path.exists(temp_dir):
                logger.warning("Temp directory does not exist", temp_dir=temp_dir)
                return []
            
            files = []
            cutoff = datetime.now().timestamp() - 300  # 5 minutes ago
            
            # List all files in directory
            all_files = os.listdir(temp_dir)
            logger.info("Found files in temp dir", 
                       file_count=len(all_files),
                       files=all_files[:10])  # Log first 10 files
            
            csv_files = []
            for filename in all_files:
                if filename.endswith('.csv'):
                    filepath = os.path.join(temp_dir, filename)
                    mtime = os.path.getmtime(filepath)
                    size = os.path.getsize(filepath)
                    
                    if mtime > cutoff:
                        csv_files.append({
                            "filepath": filepath,
                            "filename": filename,
                            "size": size,
                            "mtime": mtime
                        })
                        logger.info("Found matching CSV file",
                                  filename=filename,
                                  size=size,
                                  mtime=datetime.fromtimestamp(mtime).isoformat())
            
            if not csv_files:
                logger.warning("No matching CSV files found", 
                             temp_dir=temp_dir,
                             cutoff_time=datetime.fromtimestamp(cutoff).isoformat())
            else:
                logger.info("Found CSV files",
                          count=len(csv_files),
                          files=[f["filename"] for f in csv_files])
            
            return csv_files
            
        except Exception as e:
            logger.error("Failed to find generated files", error=str(e))
            return []


# Global instance
_react_agent: Optional[LangGraphReActAgent] = None


async def get_langgraph_react_agent() -> LangGraphReActAgent:
    """Get or create LangGraph ReAct agent with MCP initialization."""
    global _react_agent
    
    if _react_agent is None:
        _react_agent = LangGraphReActAgent()
        # Initialize MCP client and tools
        await _react_agent.initialize()
    
    return _react_agent