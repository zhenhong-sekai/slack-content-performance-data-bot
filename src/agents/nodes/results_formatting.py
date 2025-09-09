"""Results formatting node implementation."""

import json
from typing import Any, Dict, List
import pandas as pd

from src.agents.state import AgentState
from src.services.csv_service import get_csv_service
from src.utils.logging import get_logger

logger = get_logger(__name__)


async def format_results_node(state: AgentState) -> AgentState:
    """Convert results to CSV and prepare for delivery."""
    mcp_results = state.get("mcp_results")
    query = state.get("query")
    user_id = state.get("user_id")
    
    if not mcp_results:
        return {
            **state,
            "error": "No MCP results available for formatting",
        }
    
    logger.info(
        "Starting results formatting",
        query=query[:100] + "..." if len(query) > 100 else query,
        user_id=user_id,
        result_steps=len(mcp_results),
    )
    
    # Add processing step
    processing_steps = list(state.get("processing_steps", []))
    processing_steps.append("results_formatting")
    
    try:
        # Combine and process all data
        combined_data = combine_mcp_results(mcp_results)
        
        if not combined_data:
            return {
                **state,
                "error": "No data found in MCP results",
                "processing_steps": processing_steps,
            }
        
        # Convert to DataFrame
        df = create_dataframe_from_results(combined_data)
        
        if df.empty:
            return {
                **state,
                "error": "Unable to create DataFrame from results",
                "processing_steps": processing_steps,
            }
        
        # Clean and format data
        df = clean_and_format_dataframe(df)
        
        # Generate CSV file
        csv_service = get_csv_service()
        csv_path = await csv_service.generate_csv(df, query)
        
        # Generate summary
        result_summary = generate_result_summary(df, query)
        
        logger.info(
            "Results formatting completed",
            csv_path=csv_path,
            rows=len(df),
            columns=len(df.columns),
            file_size=await csv_service.get_file_size(csv_path),
        )
        
        return {
            **state,
            "processed_data": {
                "dataframe_shape": df.shape,
                "columns": list(df.columns),
                "row_count": len(df),
            },
            "csv_path": csv_path,
            "result_summary": result_summary,
            "processing_steps": processing_steps,
        }
        
    except Exception as e:
        logger.error(
            "Results formatting failed",
            query=query,
            error=str(e),
            exc_info=True,
        )
        
        return {
            **state,
            "error": f"Failed to format results: {str(e)}",
            "processing_steps": processing_steps,
        }


def combine_mcp_results(mcp_results: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Combine MCP results from all steps into a unified data structure."""
    
    combined_data = []
    
    for step_id, step_result in mcp_results.items():
        if not step_result.get("success", False):
            logger.warning(f"Skipping failed step: {step_id}")
            continue
        
        step_data = step_result.get("data", {})
        
        for tool_name, tool_result in step_data.items():
            if not tool_result.get("success", False):
                logger.warning(f"Skipping failed tool: {tool_name} in step: {step_id}")
                continue
            
            tool_data = tool_result.get("data")
            if not tool_data:
                continue
            
            # Process different data formats
            processed_data = process_tool_data(tool_data, tool_name, step_id)
            combined_data.extend(processed_data)
    
    logger.info(f"Combined {len(combined_data)} records from MCP results")
    
    return combined_data


def process_tool_data(
    data: Any, 
    tool_name: str, 
    step_id: str
) -> List[Dict[str, Any]]:
    """Process data from a specific MCP tool."""
    
    processed_records = []
    
    try:
        if isinstance(data, list):
            # Data is already a list of records
            for record in data:
                if isinstance(record, dict):
                    record["_source_tool"] = tool_name
                    record["_source_step"] = step_id
                    processed_records.append(record)
        
        elif isinstance(data, dict):
            if "data" in data and isinstance(data["data"], list):
                # Data is wrapped in a container
                for record in data["data"]:
                    if isinstance(record, dict):
                        record["_source_tool"] = tool_name
                        record["_source_step"] = step_id
                        processed_records.append(record)
            
            elif "rows" in data:
                # Data has rows/columns format
                rows = data.get("rows", [])
                columns = data.get("columns", [])
                
                if columns:
                    for row in rows:
                        if isinstance(row, list) and len(row) == len(columns):
                            record = dict(zip(columns, row))
                            record["_source_tool"] = tool_name
                            record["_source_step"] = step_id
                            processed_records.append(record)
            
            else:
                # Single record
                data["_source_tool"] = tool_name
                data["_source_step"] = step_id
                processed_records.append(data)
        
        else:
            # Convert other types to string
            record = {
                "value": str(data),
                "_source_tool": tool_name,
                "_source_step": step_id,
            }
            processed_records.append(record)
    
    except Exception as e:
        logger.error(
            f"Failed to process data from {tool_name}",
            error=str(e),
            data_type=type(data).__name__,
        )
        
        # Create error record
        record = {
            "error": f"Failed to process data: {str(e)}",
            "_source_tool": tool_name,
            "_source_step": step_id,
        }
        processed_records.append(record)
    
    return processed_records


def create_dataframe_from_results(data: List[Dict[str, Any]]) -> pd.DataFrame:
    """Create a pandas DataFrame from processed results."""
    
    if not data:
        return pd.DataFrame()
    
    try:
        df = pd.DataFrame(data)
        
        # Ensure we have at least one column
        if df.empty or len(df.columns) == 0:
            return pd.DataFrame()
        
        logger.info(
            f"Created DataFrame with shape {df.shape}",
            columns=list(df.columns),
        )
        
        return df
    
    except Exception as e:
        logger.error(f"Failed to create DataFrame: {str(e)}")
        
        # Create a simple DataFrame with error info
        return pd.DataFrame([{
            "error": "Failed to create DataFrame",
            "details": str(e),
            "record_count": len(data),
        }])


def clean_and_format_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Clean and format DataFrame for CSV export."""
    
    try:
        # Make a copy to avoid modifying original
        df_clean = df.copy()
        
        # Remove completely empty columns
        df_clean = df_clean.dropna(how='all', axis=1)
        
        # Remove completely empty rows
        df_clean = df_clean.dropna(how='all', axis=0)
        
        # Clean column names
        df_clean.columns = [
            str(col).strip().replace('\n', ' ').replace('\r', ' ')
            for col in df_clean.columns
        ]
        
        # Handle missing values
        df_clean = df_clean.fillna('')
        
        # Format datetime columns
        for col in df_clean.columns:
            if df_clean[col].dtype == 'object':
                # Try to convert datetime-like strings
                try:
                    # Check if column looks like dates
                    sample_values = df_clean[col].dropna().head(5)
                    if any('T' in str(val) or '-' in str(val) for val in sample_values):
                        df_clean[col] = pd.to_datetime(df_clean[col], errors='ignore')
                        if df_clean[col].dtype.name.startswith('datetime'):
                            df_clean[col] = df_clean[col].dt.strftime('%Y-%m-%d %H:%M:%S')
                except:
                    pass  # Keep original format if conversion fails
        
        # Convert any remaining object types to strings
        for col in df_clean.columns:
            if df_clean[col].dtype == 'object':
                df_clean[col] = df_clean[col].astype(str)
        
        # Ensure reasonable column order (metadata columns last)
        regular_columns = [col for col in df_clean.columns if not col.startswith('_')]
        meta_columns = [col for col in df_clean.columns if col.startswith('_')]
        df_clean = df_clean[regular_columns + meta_columns]
        
        logger.info(
            f"Cleaned DataFrame",
            original_shape=df.shape,
            cleaned_shape=df_clean.shape,
        )
        
        return df_clean
    
    except Exception as e:
        logger.error(f"Failed to clean DataFrame: {str(e)}")
        return df  # Return original on error


def generate_result_summary(df: pd.DataFrame, query: str) -> str:
    """Generate a human-readable summary of the results."""
    
    try:
        row_count = len(df)
        col_count = len(df.columns)
        
        # Get column names (exclude metadata columns)
        data_columns = [col for col in df.columns if not col.startswith('_')]
        
        # Basic summary
        summary_parts = [
            f"Found {row_count:,} records with {col_count} columns for your query.",
        ]
        
        if data_columns:
            if len(data_columns) <= 5:
                columns_text = ", ".join(data_columns)
            else:
                columns_text = ", ".join(data_columns[:5]) + f", and {len(data_columns) - 5} more"
            
            summary_parts.append(f"Data includes: {columns_text}.")
        
        # Data source info
        if "_source_tool" in df.columns:
            sources = df["_source_tool"].unique()
            if len(sources) == 1:
                summary_parts.append(f"Data retrieved from: {sources[0]}.")
            else:
                summary_parts.append(f"Data retrieved from {len(sources)} sources: {', '.join(sources)}.")
        
        # Add helpful context
        if row_count > 1000:
            summary_parts.append("This is a large dataset - you may want to filter or aggregate the data for analysis.")
        elif row_count == 0:
            summary_parts.append("No data found matching your criteria. Try adjusting your query parameters.")
        
        return " ".join(summary_parts)
    
    except Exception as e:
        logger.error(f"Failed to generate summary: {str(e)}")
        return f"Successfully processed your query and generated {len(df)} records. Data is ready for download."