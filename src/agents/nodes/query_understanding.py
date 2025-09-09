"""Query understanding node implementation."""

import json
from typing import Dict, Any

from langchain_openai import ChatOpenAI

from src.agents.state import AgentState, QueryIntent
from src.agents.prompts.query_parser import get_query_understanding_prompt
from src.config import settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


async def understand_query_node(state: AgentState) -> AgentState:
    """Parse natural language query and extract intent."""
    query = state["query"]
    user_id = state["user_id"]
    
    logger.info(
        "Starting query understanding",
        query=query[:100] + "..." if len(query) > 100 else query,
        user_id=user_id,
    )
    
    # Add processing step
    processing_steps = list(state.get("processing_steps", []))
    processing_steps.append("query_understanding")
    
    try:
        # Initialize LLM
        llm = ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            temperature=0.1,  # Low temperature for consistent parsing
            timeout=30,
        )
        
        # Get understanding prompt
        prompt = get_query_understanding_prompt()
        
        # Format prompt with query
        messages = prompt.format_messages(query=query)
        
        # Get LLM response
        response = await llm.ainvoke(messages)
        
        # Parse response - handle markdown code blocks
        try:
            response_content = response.content.strip()
            
            # Remove markdown code block wrapper if present
            if response_content.startswith('```json'):
                # Extract JSON from markdown code block
                lines = response_content.split('\n')
                json_lines = []
                in_json_block = False
                
                for line in lines:
                    if line.strip() == '```json':
                        in_json_block = True
                        continue
                    elif line.strip() == '```':
                        in_json_block = False
                        break
                    elif in_json_block:
                        json_lines.append(line)
                
                response_content = '\n'.join(json_lines)
            elif response_content.startswith('```'):
                # Handle generic code blocks
                response_content = response_content.split('```', 2)[1]
                if response_content.startswith('json\n'):
                    response_content = response_content[5:]  # Remove 'json\n'
            
            intent_data = json.loads(response_content)
            intent = QueryIntent.model_validate(intent_data)
            
        except (json.JSONDecodeError, ValueError) as e:
            logger.error("Failed to parse intent response", error=str(e), response=response.content)
            return {
                **state,
                "error": f"Failed to parse query intent: {str(e)}",
                "processing_steps": processing_steps,
            }
        
        # Validate intent confidence
        if intent.confidence < 0.5:
            logger.warning(
                "Low confidence intent",
                confidence=intent.confidence,
                intent_type=intent.intent_type,
            )
            
            return {
                **state,
                "error": (
                    f"I'm not confident I understood your query correctly "
                    f"(confidence: {intent.confidence:.2f}). "
                    "Could you please be more specific about what data you're looking for?"
                ),
                "processing_steps": processing_steps,
            }
        
        # Extract entities and metadata
        entities = intent.entities
        query_type = intent.intent_type
        
        logger.info(
            "Query understanding completed",
            intent_type=query_type,
            confidence=intent.confidence,
            data_sources=intent.data_sources,
            time_range=intent.time_range,
            entities_count=len(entities),
        )
        
        return {
            **state,
            "intent": intent.model_dump(),
            "query_type": query_type,
            "entities": entities,
            "processing_steps": processing_steps,
        }
        
    except Exception as e:
        logger.error(
            "Query understanding failed",
            query=query,
            error=str(e),
            exc_info=True,
        )
        
        return {
            **state,
            "error": f"Failed to understand query: {str(e)}",
            "processing_steps": processing_steps,
        }


def validate_query_safety(query: str) -> tuple[bool, str]:
    """Validate query for safety and policy compliance."""
    
    # Check for potentially harmful patterns
    dangerous_patterns = [
        "drop table",
        "delete from",
        "truncate",
        "alter table",
        "exec",
        "execute",
        "union select",
        "script",
        "javascript:",
        "<script",
        "eval(",
    ]
    
    query_lower = query.lower()
    
    for pattern in dangerous_patterns:
        if pattern in query_lower:
            return False, f"Query contains potentially harmful pattern: {pattern}"
    
    # Check query length
    if len(query) > 1000:
        return False, "Query is too long (maximum 1000 characters)"
    
    # Check for minimum query length
    if len(query.strip()) < 5:
        return False, "Query is too short. Please provide more details."
    
    return True, ""


def extract_time_references(query: str) -> Dict[str, Any]:
    """Extract time references from query text."""
    import re
    from datetime import datetime, timedelta
    
    time_patterns = {
        "today": {"days": 0},
        "yesterday": {"days": 1},
        "this week": {"weeks": 0},
        "last week": {"weeks": 1},
        "this month": {"months": 0},
        "last month": {"months": 1},
        "this quarter": {"quarters": 0},
        "last quarter": {"quarters": 1},
        "this year": {"years": 0},
        "last year": {"years": 1},
    }
    
    # Look for relative time patterns
    query_lower = query.lower()
    
    for pattern, delta in time_patterns.items():
        if pattern in query_lower:
            return {
                "type": "relative",
                "pattern": pattern,
                "delta": delta,
            }
    
    # Look for specific date patterns
    date_patterns = [
        r"\b(\d{4}-\d{2}-\d{2})\b",  # YYYY-MM-DD
        r"\b(\d{1,2}/\d{1,2}/\d{4})\b",  # MM/DD/YYYY
        r"\b(\d{1,2}-\d{1,2}-\d{4})\b",  # MM-DD-YYYY
    ]
    
    for pattern in date_patterns:
        match = re.search(pattern, query)
        if match:
            return {
                "type": "absolute",
                "date_string": match.group(1),
            }
    
    # Look for duration patterns
    duration_patterns = [
        r"(\d+)\s*days?",
        r"(\d+)\s*weeks?",
        r"(\d+)\s*months?",
        r"(\d+)\s*quarters?",
    ]
    
    for pattern in duration_patterns:
        match = re.search(pattern, query_lower)
        if match:
            return {
                "type": "duration",
                "value": int(match.group(1)),
                "unit": pattern.split("\\")[0].replace("(\\d+)\\s*", ""),
            }
    
    return {"type": "none"}