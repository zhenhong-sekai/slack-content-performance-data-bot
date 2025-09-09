"""Proper LangGraph ReAct agent with MCP tools integration."""

import asyncio
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langchain.tools import Tool, StructuredTool
from pydantic import BaseModel, Field
from langchain.agents import AgentExecutor, create_openai_functions_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from src.config import settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


class SaveCSVInput(BaseModel):
    """Input schema for save_as_csv tool."""
    data_json: str = Field(description="JSON data string from execute_query to save as CSV")


class LangGraphMCPAgent:
    """Proper LangGraph ReAct agent with MCP integration."""
    
    def __init__(self):
        self.llm = ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            temperature=0.1,
        )
        self.mcp_client = None
        self.agent = None
    
    async def _initialize_mcp_agent(self):
        """Initialize MCP client and create LangGraph ReAct agent."""
        # Always attempt to create a new MCP connection - don't cache failures
        logger.info("Attempting to initialize LangGraph MCP agent", url=settings.mcp_server_url)
        
        try:
            # Reset agent to None to force recreation
            self.agent = None
            self.mcp_client = None
            
            # Configure MCP client (as per LangGraph docs)
            self.mcp_client = MultiServerMCPClient({
                "bigquery_sse": {
                    "url": settings.mcp_server_url,
                    "transport": "streamable_http",
                }
            })
            
            logger.info("MCP client created, retrieving tools...")
            
            # Get tools from MCP servers (this is the key step!)
            mcp_tools = await self.mcp_client.get_tools()
            logger.info("MCP tools retrieved", tool_count=len(mcp_tools))
            
            # Add CSV saving tool to the MCP tools
            all_tools = list(mcp_tools)
            all_tools.append(self._create_csv_tool())
            
            # Log available tools
            for tool in all_tools:
                tool_name = getattr(tool, 'name', 'unknown')
                tool_desc = getattr(tool, 'description', 'no description')
                logger.info("Available tool", name=tool_name, description=tool_desc[:100])
            
            # Create OpenAI functions agent (works with current versions)
            logger.info("Creating OpenAI functions agent with MCP tools...")
            
            # Create prompt template
            prompt = ChatPromptTemplate.from_messages([
                ("system", """You are OptiBot, a helpful BigQuery data assistant.

CRITICAL RULES:
1. ALWAYS use the available tools - never make up data or table names
2. When users ask for data, ALWAYS follow this sequence:
   - Use list_tables to see available tables
   - Use describe_table to understand table structure
   - Use execute_query to get actual data  
   - ALWAYS use save_as_csv to create downloadable files whenever you return data (mandatory for all data requests)
3. MANDATORY: For ANY data request, no matter how small, you MUST create a CSV file using save_as_csv tool
4. If tools return errors (like serialization issues), automatically fix and retry
5. ALWAYS provide a complete response even if tools fail
6. DATETIME ERROR AUTO-FIX: If execute_query returns "datetime is not JSON serializable":
   - IMMEDIATELY identify ALL datetime/timestamp columns: event_timestamp, created_at, updated_at
   - Replace with CAST(column AS STRING) AS column format  
   - Execute corrected query: SELECT user_id, CAST(event_timestamp AS STRING) AS event_timestamp, event_name, sekai_id, extra, row_num FROM table
   - Do NOT retry original query - MUST modify datetime columns first
   - Then call save_as_csv with the successful result

Available tools: list_tables, describe_table, execute_query, clear_cache, get_cache_stats, save_as_csv

CSV REQUIREMENT: 
- ONLY create CSV files when execute_query returns actual data
- If execute_query returns empty results [] or no data, do NOT call save_as_csv
- CSV files should only contain meaningful data, not empty result messages
- Only call save_as_csv when there is actual data to download

CRITICAL: HOW TO USE save_as_csv TOOL:
- Pass the EXACT JSON data string returned by execute_query
- Do NOT pass filenames, summaries, or formatted text
- Do NOT pass your own formatted response - only raw query results
- Example: If execute_query returns [{{"name":"John","age":25}}], call save_as_csv('[{{"name":"John","age":25}}]')
- The tool will automatically generate the filename - you don't provide it

EMPTY RESULTS HANDLING: When execute_query returns [] or no results:
1. Explain that no data was found matching the criteria
2. Do NOT create a CSV file for empty results
3. Suggest alternative queries or broader search criteria
4. Recommend checking if the data exists with different filters
5. Provide helpful suggestions for modifying the query

CRITICAL DATETIME FIX RULE:
If ANY query fails with "datetime is not JSON serializable", you MUST:

1. Find ALL datetime/timestamp columns (event_timestamp, created_at, updated_at, etc.)
2. Replace them with CAST(column AS STRING) AS column format
3. Execute the corrected query

MANDATORY TRANSFORMATIONS:
- event_timestamp → CAST(event_timestamp AS STRING) AS event_timestamp
- created_at → CAST(created_at AS STRING) AS created_at  
- updated_at → CAST(updated_at AS STRING) AS updated_at
- ANY datetime field → CAST(field_name AS STRING) AS field_name

EXAMPLE - Current broken query:
SELECT user_id, event_timestamp, event_name FROM table

MUST BECOME:
SELECT user_id, CAST(event_timestamp AS STRING) AS event_timestamp, event_name FROM table

NEVER retry without fixing datetime columns first!"""),
                ("user", "{input}"),
                MessagesPlaceholder(variable_name="agent_scratchpad"),
            ])
            
            # Create OpenAI functions agent
            agent = create_openai_functions_agent(self.llm, all_tools, prompt)
            
            # Create agent executor with better error handling
            self.agent = AgentExecutor(
                agent=agent,
                tools=all_tools,
                verbose=False,  # Reduce verbosity to prevent context issues
                max_iterations=4,  # Further reduced to prevent API issues
                handle_parsing_errors=True,
                return_intermediate_steps=False,  # Disable to reduce context size
                max_execution_time=90  # Shorter timeout
            )
            
            logger.info("LangGraph ReAct agent created successfully")
                
        except Exception as e:
            logger.error("Failed to initialize LangGraph MCP agent", error=str(e), exc_info=True)
            # Don't create fallback agent - let it retry on next query
            self.agent = None
            self.mcp_client = None
    
    def _create_csv_tool(self):
        """Create CSV saving tool."""
        def save_as_csv(data_json):
            """Save JSON data as CSV file."""
            try:
                logger.info("save_as_csv tool called", data_preview=data_json[:200], data_type=type(data_json).__name__)
                
                # Check if data_json contains an error message
                if "error" in data_json.lower() or "serializable" in data_json.lower():
                    return f"Cannot create CSV: Query returned error - {data_json[:500]}"
                
                # Check if this looks like a filename instead of JSON data
                if data_json.endswith('.csv') and not data_json.startswith('[') and not data_json.startswith('{'):
                    return f"Error: Received filename '{data_json}' instead of JSON data. Please pass the raw data returned by execute_query, not a filename."
                
                # Parse JSON data
                data = json.loads(data_json)
                
                # Handle different data structures
                df = None
                if isinstance(data, list):
                    if data:  # Non-empty list
                        df = pd.DataFrame(data)
                    else:  # Empty list - create empty DataFrame with message
                        df = pd.DataFrame({"message": ["No results found for this query"]})
                elif isinstance(data, dict):
                    # Check for error in response
                    if "error" in data:
                        return f"Cannot create CSV: Query error - {data.get('error', 'Unknown error')}"
                    if "rows" in data:
                        if data["rows"]:
                            df = pd.DataFrame(data["rows"])
                        else:
                            df = pd.DataFrame({"message": ["No results found for this query"]})
                    elif "data" in data:
                        if data["data"]:
                            df = pd.DataFrame(data["data"])
                        else:
                            df = pd.DataFrame({"message": ["No results found for this query"]})
                    elif "result" in data:
                        if data["result"]:
                            df = pd.DataFrame(data["result"])
                        else:
                            df = pd.DataFrame({"message": ["No results found for this query"]})
                    else:
                        df = pd.DataFrame([data])
                
                if df is None:
                    df = pd.DataFrame({"message": ["No valid data to convert to CSV"]})
                
                # Create CSV file
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"query_results_{timestamp}.csv"
                temp_dir = settings.temp_file_path
                os.makedirs(temp_dir, exist_ok=True)
                
                filepath = os.path.join(temp_dir, filename)
                df.to_csv(filepath, index=False)
                
                logger.info("CSV file created successfully", 
                           filepath=filepath, 
                           rows=len(df), 
                           columns=len(df.columns))
                
                return f"SUCCESS: CSV file '{filename}' created with {len(df)} rows and {len(df.columns)} columns"
                
            except Exception as e:
                error_msg = f"Failed to create CSV: {str(e)}"
                logger.error("CSV creation failed", error=error_msg)
                return error_msg
        
        return Tool(
            name="save_as_csv",
            description="Save JSON data as CSV file",
            func=save_as_csv
        )
    
    async def _create_fallback_agent(self):
        """Create fallback agent if MCP fails."""
        def create_error_csv(error_message: str) -> str:
            """Create a CSV file with error information."""
            try:
                # Create DataFrame with error info
                df = pd.DataFrame({
                    "status": ["ERROR"],
                    "message": [error_message],
                    "timestamp": [datetime.now().isoformat()],
                    "suggestion": ["Please try again later or contact support if this issue persists"]
                })
                
                # Create CSV file
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"error_report_{timestamp}.csv"
                temp_dir = settings.temp_file_path
                os.makedirs(temp_dir, exist_ok=True)
                
                filepath = os.path.join(temp_dir, filename)
                df.to_csv(filepath, index=False)
                
                logger.info("Error CSV created", filepath=filepath)
                return f"SUCCESS: Error report CSV file '{filename}' created"
                
            except Exception as e:
                logger.error("Failed to create error CSV", error=str(e))
                return f"Failed to create error report: {str(e)}"
        
        def fallback_response(query: str) -> str:
            error_msg = "🔌 **Data Server Unavailable**\n\n" \
                       "I'm currently unable to connect to the BigQuery data server. This could be due to:\n" \
                       "• Server maintenance\n" \
                       "• Network connectivity issues\n" \
                       "• Temporary service outage\n\n" \
                       f"**Your Query:** {query[:200]}{'...' if len(query) > 200 else ''}\n\n" \
                       "**What to do:**\n" \
                       "• Please try again in a few minutes\n" \
                       "• Check if the issue persists\n" \
                       "• Contact your system administrator if needed\n\n" \
                       "I'm creating an error report CSV for your reference."
            
            # Create error CSV
            create_error_csv("MCP BigQuery server unavailable - please try again later")
            
            return error_msg
        
        fallback_tool = Tool(
            name="fallback_response", 
            description="Fallback response when MCP unavailable - creates error report and CSV",
            func=fallback_response
        )
        
        logger.info("Creating fallback agent")
        
        # Improved prompt for fallback
        prompt = ChatPromptTemplate.from_messages([
            ("system", """You are OptiBot experiencing a temporary service disruption. 

SITUATION: The BigQuery data server is currently unavailable (500 error).

YOUR RESPONSE SHOULD:
1. Use the fallback_response tool to provide a helpful error message
2. Explain that the data server is temporarily unavailable  
3. Suggest the user try again later
4. Be professional and empathetic

Always use the fallback_response tool for any query when in fallback mode."""),
            ("user", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])
        
        agent = create_openai_functions_agent(self.llm, [fallback_tool], prompt)
        self.agent = AgentExecutor(
            agent=agent,
            tools=[fallback_tool],
            verbose=True,
            max_iterations=2,
            handle_parsing_errors=True
        )
    
    async def process_query(self, query: str, user_id: str) -> Dict[str, Any]:
        """Process user query with LangGraph ReAct agent."""
        logger.info("Processing query with LangGraph agent", query=query[:100], user_id=user_id)
        
        try:
            # Always try to initialize MCP agent on each query
            # This ensures we reconnect if MCP server was down before but is now up
            await self._initialize_mcp_agent()
            
            if self.agent is None:
                logger.warning("MCP agent initialization failed, attempting fallback")
                return {
                    "success": False,
                    "response": "I'm having trouble connecting to the data server right now. Please try again in a few minutes.",
                    "csv_files": [],
                    "error": "MCP agent initialization failed"
                }
            
            # Execute agent (standard AgentExecutor format)
            logger.info("Invoking MCP-enabled agent", user_id=user_id)
            
            # AgentExecutor expects input in this format
            try:
                response = await self.agent.ainvoke({
                    "input": query
                })
            except Exception as api_error:
                logger.error("Agent invocation failed", error=str(api_error), error_type=type(api_error).__name__)
                
                # Check if this is an OpenAI API error
                if "null" in str(api_error) or "content" in str(api_error):
                    return {
                        "success": False,
                        "response": "I encountered an API formatting issue while processing your query. The query was partially successful but I couldn't complete the final steps. Please try rephrasing your request.",
                        "csv_files": self._find_generated_files(),  # Still return any CSV files that were created
                        "error": "OpenAI API content formatting error"
                    }
                else:
                    raise api_error
            
            # Extract response from AgentExecutor format
            response_text = response.get("output", "No response generated")
            
            # Check for generated CSV files
            csv_files = self._find_generated_files()
            
            logger.info("LangGraph agent completed", 
                       user_id=user_id, 
                       csv_files_count=len(csv_files))
            
            return {
                "success": True,
                "response": response_text,
                "csv_files": csv_files,
                "error": None
            }
            
        except Exception as e:
            logger.error("LangGraph agent failed", 
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
_langgraph_agent: Optional[LangGraphMCPAgent] = None

async def get_langgraph_mcp_agent() -> LangGraphMCPAgent:
    """Get or create LangGraph MCP agent."""
    global _langgraph_agent
    
    if _langgraph_agent is None:
        _langgraph_agent = LangGraphMCPAgent()
    
    # Don't initialize here - let process_query handle MCP connection attempts
    return _langgraph_agent