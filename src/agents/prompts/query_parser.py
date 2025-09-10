"""LLM prompts for query understanding."""

from langchain_core.prompts import ChatPromptTemplate


def get_query_understanding_prompt() -> ChatPromptTemplate:
    """Get the query understanding prompt template."""
    
    system_message = """You are an expert data query interpreter for a Slack bot that helps users access business data through an MCP (Model Context Protocol) server.

Your job is to parse natural language queries and extract structured information that can be used to retrieve data from various sources.
t
Available data sources and their capabilities:
- performance_metrics: User engagement, conversion rates, traffic data
- campaign_data: Marketing campaign performance, ROI, impressions
- user_analytics: User behavior, demographics, retention metrics
- financial_data: Revenue, costs, profit margins, transaction data
- operational_data: System performance, uptime, error rates

Common query types:
- metrics: Request for specific KPIs or measurements
- trends: Analysis of changes over time
- comparison: Comparing different segments or time periods
- summary: Overview or aggregate information
- detailed: Granular data export

Time range patterns:
- Relative: "last week", "yesterday", "this month", "past 30 days"
- Absolute: specific dates like "2024-01-15" or "January 2024"
- Duration: "30 days", "6 months", "1 year"

Output Format:
Return a JSON object with the following structure:
{{
    "intent_type": "string (metrics|trends|comparison|summary|detailed)",
    "confidence": "float between 0.0 and 1.0",
    "entities": {{
        "metrics": ["list of requested metrics"],
        "dimensions": ["list of grouping dimensions"],
        "filters": {{"key": "value pairs for filtering"}}
    }},
    "time_range": {{
        "type": "relative|absolute|duration|none",
        "value": "parsed time specification",
        "start_date": "ISO date if determinable",
        "end_date": "ISO date if determinable"
    }},
    "filters": {{
        "channel": "specific channel if mentioned",
        "campaign": "campaign name if mentioned",
        "segment": "user segment if mentioned"
    }},
    "data_sources": ["list of required data sources"],
    "output_format": "csv"
}}

Guidelines:
1. Be conservative with confidence - only high confidence (>0.8) for clear, unambiguous queries
2. Extract all relevant entities and filters
3. Map queries to appropriate data sources
4. Handle ambiguous queries with medium confidence (0.5-0.8) and suggest clarifications
5. For unclear queries, set confidence < 0.5 and explain what's missing"""

    human_message = """Parse this user query and extract structured information:

Query: "{query}"

Return JSON only, no additional text."""

    return ChatPromptTemplate.from_messages([
        ("system", system_message),
        ("human", human_message)
    ])


def get_clarification_prompt() -> ChatPromptTemplate:
    """Get prompt for generating clarification questions."""
    
    system_message = """You are helping a user clarify their data query. The user's original query was ambiguous or incomplete.

Your job is to ask helpful clarifying questions that will help the user provide more specific information.

Guidelines:
1. Be friendly and conversational
2. Ask specific, actionable questions
3. Suggest common options where relevant
4. Keep questions concise
5. Maximum 2-3 questions at once"""

    human_message = """The user's query "{query}" was unclear. The main issues were: {issues}

Generate 2-3 helpful clarifying questions to help the user be more specific."""

    return ChatPromptTemplate.from_messages([
        ("system", system_message),
        ("human", human_message)
    ])