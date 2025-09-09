#!/usr/bin/env python3
"""
Validation script for OptiBot simplified version.
Run this to check if all dependencies and imports work correctly.
"""

import sys
import os

def test_imports():
    """Test all required imports for simplified version."""
    print("🔍 Testing imports for OptiBot simplified version...")
    
    # Add src to path
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))
    
    try:
        # Test external dependencies
        print("  📦 Testing external dependencies...")
        import slack_bolt
        import fastapi
        import uvicorn
        import pandas
        import aiohttp
        import structlog
        print("    ✅ External dependencies OK")
        
        # Test internal modules
        print("  🏠 Testing internal modules...")
        from src.workers.simple_socket_worker import start_simple_socket_worker
        from src.services.slack_socket_simple import get_simple_slack_service
        from src.utils.logging import configure_logging, get_logger
        print("    ✅ Internal modules OK")
        
        return True
        
    except ImportError as e:
        print(f"    ❌ Import error: {e}")
        print(f"    💡 Try: pip install -r requirements-simple.txt")
        return False
    except Exception as e:
        print(f"    ❌ Unexpected error: {e}")
        return False

def test_config():
    """Test configuration validation."""
    print("⚙️  Testing configuration...")
    
    try:
        from src.config import settings
        
        # Check critical settings
        critical_vars = [
            'slack_bot_token',
            'slack_app_token', 
            'slack_signing_secret',
            'openai_api_key',
            'mcp_server_url'
        ]
        
        missing = []
        for var in critical_vars:
            if not getattr(settings, var, None):
                missing.append(var.upper())
        
        if missing:
            print(f"    ⚠️  Missing environment variables: {', '.join(missing)}")
            print("    💡 Create .env file with required values")
            return False
        
        print("    ✅ Configuration OK")
        return True
        
    except Exception as e:
        print(f"    ❌ Configuration error: {e}")
        return False

def main():
    """Run all validation tests."""
    print("🚀 OptiBot Simplified Version - Validation Test")
    print("=" * 50)
    
    success = True
    
    # Test imports
    if not test_imports():
        success = False
    
    print()
    
    # Test configuration
    if not test_config():
        success = False
    
    print()
    print("=" * 50)
    
    if success:
        print("🎉 All tests passed! OptiBot simplified version is ready to run.")
        print("💡 Start with: python run-simple.py")
        print("🐳 Or with Docker: docker-compose -f docker-compose-simple.yml up")
    else:
        print("❌ Some tests failed. Please fix the issues above.")
        sys.exit(1)

if __name__ == "__main__":
    main()