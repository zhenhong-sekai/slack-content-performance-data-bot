"""Function-calling MCP agent that works better with Gemini."""

import asyncio
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
from langchain.agents import initialize_agent, AgentType
from langchain_openai import ChatOpenAI
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.tools import Tool

from src.config import settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


class FunctionMCPAgent:
    """Function-calling MCP agent that forces tool usage."""
    
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
        """Initialize MCP client and create agent."""
        if self.mcp_client is None:
            logger.info("Initializing MCP client", url=settings.mcp_server_url)
            
            try:
                # Configure MCP server
                self.mcp_client = MultiServerMCPClient({
                    "bigquery_sse": {
                        "url": settings.mcp_server_url,
                        "transport": "streamable_http",
                    }
                })
                
                # Get tools from MCP server
                self.mcp_tools = await self.mcp_client.get_tools()
                logger.info("MCP tools loaded", tool_count=len(self.mcp_tools))
                
                # Create agent
                await self._create_agent()
                
            except Exception as e:
                logger.error("Failed to initialize MCP client", error=str(e), exc_info=True)
                await self._create_fallback_agent()
    
    async def _create_agent(self):
        """Create function-calling agent."""
        # Add CSV tool to MCP tools
        enhanced_tools = list(self.mcp_tools)
        enhanced_tools.append(self._create_csv_tool())
        
        logger.info("Creating function-calling agent with tools", tool_count=len(enhanced_tools))
        
        # Log all available tools
        for tool in enhanced_tools:
            logger.info("Tool available", name=getattr(tool, 'name', 'unknown'))
        
        # Create function-calling agent (better than ReAct for Gemini)
        self.agent_executor = initialize_agent(
            tools=enhanced_tools,
            llm=self.llm,
            agent=AgentType.OPENAI_FUNCTIONS,
            verbose=True,
            max_iterations=3,
            handle_parsing_errors=True,
            agent_kwargs={
                "system_message": """You are OptiBot, a BigQuery data assistant.

MANDATORY BEHAVIOR:
1. ALWAYS use tools - never make up data or table names
2. For data requests, follow this exact sequence:
   a) Use list_tables first to see what tables exist
   b) Use describe_table to understand table structure  
   c) Use execute_query to get real data
   d) Use save_as_csv to create downloadable files
3. Only mention CSV files after successfully using save_as_csv tool
4. Never hallucinate or invent data

You have these tools: list_tables, describe_table, execute_query, clear_cache, get_cache_stats, save_as_csv"""
            }
        )
        
        logger.info("Function-calling agent created successfully")
    
    def _create_csv_tool(self):
        """Create CSV saving tool."""
        def save_as_csv(data_json: str) -> str:
            """Save JSON data as CSV file."""
            try:
                logger.info("save_as_csv tool called", data_preview=data_json[:100])
                
                data = json.loads(data_json)
                
                # Handle different data formats
                if isinstance(data, list) and data:
                    df = pd.DataFrame(data)
                elif isinstance(data, dict):
                    if "rows" in data:
                        df = pd.DataFrame(data["rows"])
                    elif "data" in data:
                        df = pd.DataFrame(data["data"])
                    else:
                        df = pd.DataFrame([data])
                else:
                    return "Error: No valid data to convert to CSV"
                
                # Create file
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"query_results_{timestamp}.csv"
                temp_dir = getattr(settings, 'temp_file_path', '/tmp/slack_bot_files')
                os.makedirs(temp_dir, exist_ok=True)
                
                filepath = os.path.join(temp_dir, filename)
                df.to_csv(filepath, index=False)
                
                logger.info("CSV file created", filepath=filepath, rows=len(df))
                
                return f"CSV file created successfully: {filename} with {len(df)} rows"
                
            except Exception as e:
                error = f"Failed to create CSV: {str(e)}"
                logger.error("CSV creation failed", error=error)
                return error
        
        return Tool(
            name="save_as_csv",
            description="Save JSON data as CSV file. Use after getting data from execute_query.",
            func=save_as_csv
        )
    
    async def _create_fallback_agent(self):
        """Create fallback agent when MCP fails."""
        def fallback_response(query: str) -> str:
            return f"Sorry, I cannot connect to the data server. Query: {query}"
        
        fallback_tool = Tool(
            name="fallback_response",
            description="Fallback when MCP unavailable",
            func=fallback_response
        )
        
        self.agent_executor = initialize_agent(
            tools=[fallback_tool],
            llm=self.llm,
            agent=AgentType.OPENAI_FUNCTIONS,
            verbose=True,
            max_iterations=1
        )
    
    async def process_query(self, query: str, user_id: str) -> Dict[str, Any]:
        """Process user query."""
        logger.info("Processing query with function agent", query=query[:100], user_id=user_id)
        
        try:
            # Initialize if needed
            await self._initialize_mcp_client()
            
            if self.agent_executor is None:
                return {
                    "success": False,
                    "response": "Agent not initialized",
                    "csv_files": [],
                    "error": "Initialization failed"
                }
            
            # Run agent
            logger.info("Executing function agent", user_id=user_id)
            result = await self.agent_executor.ainvoke({"input": query})
            
            response_text = result["output"]
            csv_files = self._find_generated_files()
            
            logger.info("Function agent completed", user_id=user_id, csv_files=len(csv_files))
            
            return {
                "success": True,
                "response": response_text,
                "csv_files": csv_files,
                "error": None
            }
            
        except Exception as e:
            logger.error("Function agent failed", error=str(e), exc_info=True)
            return {
                "success": False,
                "response": f"Error processing query: {str(e)}",
                "csv_files": [],
                "error": str(e)
            }
    
    def _find_generated_files(self) -> List[Dict[str, str]]:
        """Find recently created CSV files."""
        try:
            temp_dir = getattr(settings, 'temp_file_path', '/tmp/slack_bot_files')
            if not os.path.exists(temp_dir):
                return []
            
            files = []
            cutoff = datetime.now().timestamp() - 300  # 5 minutes
            
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
            logger.error("Failed to find files", error=str(e))
            return []


# Global instance
_function_agent: Optional[FunctionMCPAgent] = None

async def get_function_agent() -> FunctionMCPAgent:
    """Get or create function agent."""
    global _function_agent
    
    if _function_agent is None:
        _function_agent = FunctionMCPAgent()
        await _function_agent._initialize_mcp_client()
    
    return _function_agent