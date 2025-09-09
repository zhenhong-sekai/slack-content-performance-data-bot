"""Simple MCP-connected AI agent for direct query processing."""

import asyncio
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
from langchain.agents import initialize_agent, AgentType
from langchain_core.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
from langchain_mcp_adapters.client import MultiServerMCPClient

from src.config import settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


class SimpleMCPAgent:
    """Simple AI agent with direct MCP tool access via LangChain adapters."""
    
    def __init__(self):
        self.llm = ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            temperature=0.1,
        )
        self.mcp_client = None
        self.agent_executor = None
    
    async def _initialize_mcp_client(self):
        """Initialize MCP client if not already done."""
        if self.mcp_client is None:
            logger.info("Initializing MCP client", url=settings.mcp_server_url)
            
            try:
                # Configure MCP server with HTTP transport
                self.mcp_client = MultiServerMCPClient({
                    "bigquery_sse": {
                        "url": settings.mcp_server_url,
                        "transport": "streamable_http",
                    }
                })
                
                logger.info("MCP client created, getting tools...")
                
                # Get tools from MCP server
                self.mcp_tools = await self.mcp_client.get_tools()
                logger.info("MCP tools loaded", tool_count=len(self.mcp_tools))
                
                # Log available tools
                for tool in self.mcp_tools:
                    logger.info("Available MCP tool", name=getattr(tool, 'name', 'unknown'), description=getattr(tool, 'description', 'no description'))
                
                # Create agent with MCP tools
                logger.info("Creating agent with MCP tools...")
                self.agent_executor = await self._create_agent()
                logger.info("Agent created successfully")
                
            except Exception as e:
                logger.error("Failed to initialize MCP client", error=str(e), exc_info=True)
                # Don't re-raise, instead create a fallback agent
                logger.warning("Creating fallback agent without MCP tools")
                await self._create_fallback_agent()
    
    async def _create_fallback_agent(self):
        """Create a fallback agent when MCP connection fails."""
        try:
            from langchain.tools import Tool
            
            def fallback_tool(query: str) -> str:
                return f"I'm sorry, I'm currently unable to connect to the data server. Please try again later or contact support. Your query was: {query}"
            
            fallback_tools = [Tool(
                name="fallback_response",
                description="Provides fallback response when MCP is unavailable",
                func=fallback_tool
            )]
            
            # Simple prompt for fallback
            prompt = PromptTemplate.from_template("""
You are OptiBot. Unfortunately, I'm currently unable to connect to the data server.

Available tools:
{tools}

Tool names: {tool_names}

Please use the fallback_response tool to explain the situation to the user.

Question: {input}
Thought: {agent_scratchpad}""")
            
            # Create ReAct agent
            agent = create_react_agent(self.llm, fallback_tools, prompt)
            
            # Create agent executor
            self.agent_executor = AgentExecutor(
                agent=agent,
                tools=fallback_tools,
                verbose=True,
                max_iterations=3,
                handle_parsing_errors=True
            )
            
            logger.info("Fallback agent created")
            
        except Exception as e:
            logger.error("Failed to create fallback agent", error=str(e), exc_info=True)
            raise
    
    async def _create_agent(self) -> AgentExecutor:
        """Create the ReAct agent with MCP tools."""
        
        # Add CSV saving functionality to the existing MCP tools
        enhanced_tools = list(self.mcp_tools)
        enhanced_tools.append(self._create_csv_tool())
        
        # Simple prompt for the agent
        prompt = PromptTemplate.from_template("""
You are OptiBot, a helpful assistant that can access BigQuery data through MCP tools.

Available tools:
{tools}

Tool names: {tool_names}

IMPORTANT RULES:
1. ALWAYS use tools to get real data - never make up data
2. When returning tabular data, ALWAYS use save_as_csv tool to create downloadable files
3. Only mention CSV files in your response if you successfully used the save_as_csv tool
4. Be specific about which tools you're using

When users ask for data:
1. Use list_tables to see available tables
2. Use describe_table to understand table structure  
3. Use execute_query to get the actual data
4. Use save_as_csv to save query results as downloadable files
5. Tell the user what data you found and that the CSV is ready

Use the following format:

Question: the input question you must answer
Thought: you should always think about what to do
Action: the action to take, should be one of [{tool_names}]
Action Input: the input to the action
Observation: the result of the action
... (this Thought/Action/Action Input/Observation can repeat N times)
Thought: I now know the final answer
Final Answer: the final answer to the original input question

Begin!

Question: {input}
Thought: {agent_scratchpad}""")
        
        # Create ReAct agent
        agent = create_react_agent(self.llm, enhanced_tools, prompt)
        
        # Create agent executor
        agent_executor = AgentExecutor(
            agent=agent,
            tools=enhanced_tools,
            verbose=True,
            max_iterations=10,
            handle_parsing_errors=True
        )
        
        return agent_executor
    
    def _create_csv_tool(self):
        """Create a tool for saving data as CSV files."""
        from langchain.tools import Tool
        
        def save_as_csv(data_json: str) -> str:
            """Save JSON data as CSV file and return file details.
            
            Args:
                data_json: JSON string with tabular data (array of objects or nested data)
                
            Returns:
                JSON string with success/error status and file details
            """
            try:
                logger.info("save_as_csv called with data", data_preview=data_json[:200])
                
                # Parse the JSON data
                data = json.loads(data_json)
                
                # Handle different data structures
                df = None
                if isinstance(data, list) and data:
                    # Array of objects
                    df = pd.DataFrame(data)
                elif isinstance(data, dict):
                    if "rows" in data:
                        df = pd.DataFrame(data["rows"])
                    elif "data" in data:
                        df = pd.DataFrame(data["data"])
                    elif "result" in data:
                        df = pd.DataFrame(data["result"])
                    else:
                        # Single object as row
                        df = pd.DataFrame([data])
                else:
                    return json.dumps({
                        "error": "Invalid data format. Expected JSON array or object with data.",
                        "data_type": str(type(data))
                    })
                
                if df is None or df.empty:
                    return json.dumps({"error": "No data found to convert to CSV"})
                
                # Generate unique filename
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"query_results_{timestamp}.csv"
                
                # Ensure temp directory exists
                temp_dir = getattr(settings, 'temp_file_path', '/tmp/slack_bot_files')
                os.makedirs(temp_dir, exist_ok=True)
                
                # Save CSV file
                filepath = os.path.join(temp_dir, filename)
                df.to_csv(filepath, index=False)
                
                # Verify file was created
                if not os.path.exists(filepath):
                    return json.dumps({"error": "Failed to create CSV file"})
                
                file_size = os.path.getsize(filepath)
                
                logger.info(
                    "CSV file saved successfully", 
                    filepath=filepath, 
                    rows=len(df), 
                    columns=len(df.columns),
                    file_size=file_size
                )
                
                return json.dumps({
                    "success": True,
                    "filepath": filepath,
                    "filename": filename,
                    "rows": len(df),
                    "columns": list(df.columns),
                    "file_size": file_size,
                    "message": f"CSV file created successfully with {len(df)} rows and {len(df.columns)} columns"
                })
                
            except json.JSONDecodeError as e:
                error_msg = f"Invalid JSON data: {str(e)}"
                logger.error("CSV save failed - JSON decode error", error=error_msg, data=data_json[:100])
                return json.dumps({"error": error_msg})
            except Exception as e:
                error_msg = f"Failed to save CSV: {str(e)}"
                logger.error("CSV save failed", error=error_msg, exc_info=True)
                return json.dumps({"error": error_msg})
        
        return Tool(
            name="save_as_csv",
            description="Save JSON data as a CSV file. Use this after getting data to create downloadable files for users. Pass the JSON data as a string.",
            func=save_as_csv
        )
    
    async def _create_agent(self) -> AgentExecutor:
        """Create the ReAct agent with MCP tools."""
        
        # Add CSV saving functionality to the existing MCP tools
        enhanced_tools = list(self.mcp_tools)
        enhanced_tools.append(self._create_csv_tool())
        
        # Simple prompt for the agent
        prompt = PromptTemplate.from_template("""
You are OptiBot, a helpful assistant that can access business data through MCP (Model Context Protocol) tools.

Your job is to help users get the data they need by:
1. Understanding what data they want
2. Using the available tools to query the MCP server
3. Formatting and saving results as CSV files when appropriate
4. Providing clear, helpful responses

Available tools:
{tools}

Tool names: {tool_names}

When users ask for data:
1. First check what data sources are available if needed
2. Query the appropriate data with relevant filters  
3. Save results as CSV if it's tabular data
4. Provide a summary of what you found

Be conversational and helpful. If a query is unclear, ask for clarification.

Use the following format:

Question: the input question you must answer
Thought: you should always think about what to do
Action: the action to take, should be one of [{tool_names}]
Action Input: the input to the action
Observation: the result of the action
... (this Thought/Action/Action Input/Observation can repeat N times)
Thought: I now know the final answer
Final Answer: the final answer to the original input question

Begin!

Question: {input}
Thought: {agent_scratchpad}""")
        
        # Create ReAct agent
        agent = create_react_agent(self.llm, enhanced_tools, prompt)
        
        # Create agent executor
        agent_executor = AgentExecutor(
            agent=agent,
            tools=enhanced_tools,
            verbose=True,
            max_iterations=10,
            handle_parsing_errors=True
        )
        
        return agent_executor
    
    async def process_query(self, query: str, user_id: str) -> Dict[str, Any]:
        """Process user query using the simple agent.
        
        Args:
            query: User's natural language query
            user_id: Slack user ID for logging
            
        Returns:
            Dict with response and any generated files
        """
        logger.info("Processing query with simple agent", query=query[:100], user_id=user_id)
        
        try:
            # Initialize MCP client if needed
            await self._initialize_mcp_client()
            
            # Check if agent executor was created
            if self.agent_executor is None:
                logger.error("Agent executor is None after initialization")
                return {
                    "success": False,
                    "response": "I'm experiencing technical difficulties connecting to the data server. Please try again later.",
                    "csv_files": [],
                    "error": "Agent executor not initialized"
                }
            
            # Run the agent
            logger.info("Running agent executor", user_id=user_id)
            result = await self.agent_executor.ainvoke({
                "input": query
            })
            
            response_text = result["output"]
            
            # Check if any CSV files were generated
            csv_files = self._find_generated_files()
            
            logger.info(
                "Simple agent completed", 
                user_id=user_id,
                csv_files_count=len(csv_files),
                success=True
            )
            
            return {
                "success": True,
                "response": response_text,
                "csv_files": csv_files,
                "error": None
            }
            
        except Exception as e:
            logger.error(
                "Simple agent failed",
                query=query[:100],
                user_id=user_id,
                error=str(e),
                exc_info=True
            )
            
            return {
                "success": False,
                "response": f"I encountered an error processing your request: {str(e)}",
                "csv_files": [],
                "error": str(e)
            }
    
    def _find_generated_files(self) -> List[Dict[str, str]]:
        """Find recently generated CSV files."""
        try:
            temp_dir = getattr(settings, 'temp_file_path', '/tmp/slack_bot_files')
            if not os.path.exists(temp_dir):
                return []
            
            files = []
            cutoff_time = datetime.now().timestamp() - 300  # 5 minutes ago
            
            for filename in os.listdir(temp_dir):
                if filename.endswith('.csv'):
                    filepath = os.path.join(temp_dir, filename)
                    if os.path.getmtime(filepath) > cutoff_time:
                        files.append({
                            "filepath": filepath,
                            "filename": filename,
                            "size": os.path.getsize(filepath)
                        })
            
            return files
            
        except Exception as e:
            logger.error("Failed to find generated files", error=str(e))
            return []


# Global agent instance
_simple_agent: Optional[SimpleMCPAgent] = None


async def get_simple_agent() -> SimpleMCPAgent:
    """Get or create the simple MCP agent."""
    global _simple_agent
    
    if _simple_agent is None:
        _simple_agent = SimpleMCPAgent()
        # Initialize MCP client on first access
        await _simple_agent._initialize_mcp_client()
    
    return _simple_agent