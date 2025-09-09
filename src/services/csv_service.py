"""CSV generation and file management service."""

import asyncio
import hashlib
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from src.config import settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


class CSVService:
    """Service for generating and managing CSV files."""
    
    def __init__(self, storage_path: str = None):
        self.storage_path = Path(storage_path or settings.temp_file_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.max_file_size = settings.max_file_size_mb * 1024 * 1024  # Convert to bytes
        self.cleanup_hours = settings.file_cleanup_hours
    
    async def generate_csv(
        self, 
        df: pd.DataFrame, 
        query: str = None,
        filename: str = None
    ) -> str:
        """Generate CSV file from DataFrame."""
        
        if df.empty:
            raise ValueError("Cannot generate CSV from empty DataFrame")
        
        # Generate filename if not provided
        if not filename:
            if query:
                # Create filename from query (sanitized)
                query_hash = hashlib.md5(query.encode()).hexdigest()[:8]
                filename = f"query_results_{query_hash}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            else:
                filename = f"data_export_{uuid.uuid4().hex[:8]}.csv"
        
        # Ensure .csv extension
        if not filename.endswith('.csv'):
            filename += '.csv'
        
        csv_path = self.storage_path / filename
        
        logger.info(
            "Generating CSV file",
            filename=filename,
            rows=len(df),
            columns=len(df.columns),
            query_preview=query[:50] + "..." if query and len(query) > 50 else query,
        )
        
        try:
            # Write CSV with proper settings
            df.to_csv(
                csv_path,
                index=False,
                encoding='utf-8',
                quoting=1,  # QUOTE_ALL
                lineterminator='\n',
                float_format='%.6g',  # Avoid scientific notation for small numbers
            )
            
            # Check file size
            file_size = os.path.getsize(csv_path)
            
            if file_size > self.max_file_size:
                os.remove(csv_path)
                raise ValueError(
                    f"Generated CSV file is too large ({file_size / 1024 / 1024:.1f}MB). "
                    f"Maximum allowed is {settings.max_file_size_mb}MB. "
                    "Try filtering your query to return fewer results."
                )
            
            # Schedule cleanup
            asyncio.create_task(self.schedule_cleanup(csv_path))
            
            logger.info(
                "CSV file generated successfully",
                path=str(csv_path),
                size_mb=round(file_size / 1024 / 1024, 2),
            )
            
            return str(csv_path)
        
        except Exception as e:
            # Clean up partial file if it exists
            if csv_path.exists():
                try:
                    os.remove(csv_path)
                except:
                    pass
            
            logger.error(
                "CSV generation failed",
                filename=filename,
                error=str(e),
                exc_info=True,
            )
            raise
    
    async def get_file_size(self, file_path: str) -> int:
        """Get file size in bytes."""
        try:
            return os.path.getsize(file_path)
        except OSError:
            return 0
    
    async def get_file_info(self, file_path: str) -> dict:
        """Get comprehensive file information."""
        path = Path(file_path)
        
        if not path.exists():
            return {"exists": False}
        
        try:
            stat = path.stat()
            return {
                "exists": True,
                "size_bytes": stat.st_size,
                "size_mb": round(stat.st_size / 1024 / 1024, 2),
                "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "name": path.name,
            }
        except OSError as e:
            logger.error(f"Failed to get file info for {file_path}: {str(e)}")
            return {"exists": True, "error": str(e)}
    
    async def validate_dataframe(self, df: pd.DataFrame) -> dict:
        """Validate DataFrame before CSV generation."""
        
        if df.empty:
            return {
                "valid": False,
                "reason": "DataFrame is empty",
                "suggestions": ["Check your query filters", "Verify data sources are available"]
            }
        
        # Check dimensions
        rows, cols = df.shape
        
        if rows > 1000000:  # 1 million rows
            return {
                "valid": False,
                "reason": f"Too many rows ({rows:,}). Maximum is 1,000,000.",
                "suggestions": ["Add date filters to limit the time range", "Use more specific filters"]
            }
        
        if cols > 1000:  # 1000 columns
            return {
                "valid": False,
                "reason": f"Too many columns ({cols}). Maximum is 1,000.",
                "suggestions": ["Select specific metrics instead of all available data"]
            }
        
        # Estimate file size (rough calculation)
        estimated_size_mb = (rows * cols * 20) / 1024 / 1024  # Assume ~20 bytes per cell
        
        if estimated_size_mb > settings.max_file_size_mb:
            return {
                "valid": False,
                "reason": f"Estimated file size ({estimated_size_mb:.1f}MB) exceeds limit ({settings.max_file_size_mb}MB)",
                "suggestions": ["Reduce the date range", "Apply more specific filters", "Select fewer columns"]
            }
        
        # Check for problematic data
        warnings = []
        
        # Check for very wide text columns
        for col in df.columns:
            if df[col].dtype == 'object':
                max_length = df[col].astype(str).str.len().max()
                if max_length > 10000:
                    warnings.append(f"Column '{col}' has very long text values (max {max_length} characters)")
        
        return {
            "valid": True,
            "rows": rows,
            "columns": cols,
            "estimated_size_mb": round(estimated_size_mb, 2),
            "warnings": warnings,
        }
    
    async def schedule_cleanup(self, file_path: Path, delay_hours: int = None) -> None:
        """Schedule automatic file cleanup."""
        
        delay_hours = delay_hours or self.cleanup_hours
        delay_seconds = delay_hours * 3600
        
        logger.info(
            "Scheduling file cleanup",
            file_path=str(file_path),
            delay_hours=delay_hours,
        )
        
        try:
            await asyncio.sleep(delay_seconds)
            
            if file_path.exists():
                os.remove(file_path)
                logger.info(f"Cleaned up file: {file_path}")
            
        except asyncio.CancelledError:
            logger.info(f"Cleanup cancelled for: {file_path}")
        except Exception as e:
            logger.error(f"Failed to cleanup file {file_path}: {str(e)}")
    
    async def cleanup_expired_files(self) -> int:
        """Clean up expired files manually."""
        
        logger.info("Starting manual file cleanup")
        
        cleaned_count = 0
        cutoff_time = datetime.now().timestamp() - (self.cleanup_hours * 3600)
        
        try:
            for file_path in self.storage_path.glob("*.csv"):
                try:
                    if file_path.stat().st_mtime < cutoff_time:
                        os.remove(file_path)
                        cleaned_count += 1
                        logger.debug(f"Cleaned up expired file: {file_path}")
                
                except OSError as e:
                    logger.warning(f"Failed to clean up {file_path}: {str(e)}")
        
        except Exception as e:
            logger.error(f"File cleanup failed: {str(e)}")
        
        logger.info(f"Manual cleanup completed. Removed {cleaned_count} files.")
        
        return cleaned_count
    
    def get_storage_stats(self) -> dict:
        """Get storage directory statistics."""
        
        try:
            total_files = 0
            total_size = 0
            csv_files = 0
            
            for file_path in self.storage_path.rglob("*"):
                if file_path.is_file():
                    total_files += 1
                    total_size += file_path.stat().st_size
                    
                    if file_path.suffix == '.csv':
                        csv_files += 1
            
            return {
                "storage_path": str(self.storage_path),
                "total_files": total_files,
                "csv_files": csv_files,
                "total_size_mb": round(total_size / 1024 / 1024, 2),
                "max_file_size_mb": settings.max_file_size_mb,
                "cleanup_hours": self.cleanup_hours,
            }
        
        except Exception as e:
            logger.error(f"Failed to get storage stats: {str(e)}")
            return {"error": str(e)}


# Global service instance
_csv_service: Optional[CSVService] = None


def get_csv_service() -> CSVService:
    """Get or create CSV service instance."""
    global _csv_service
    
    if _csv_service is None:
        _csv_service = CSVService()
    
    return _csv_service