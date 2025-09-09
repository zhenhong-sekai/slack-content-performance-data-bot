"""Intent-to-MCP tool mapping configuration."""

from typing import Dict, Any


def get_mcp_mapping() -> Dict[str, Any]:
    """Get mapping configuration from query intent to MCP tools."""
    
    return {
        "performance_metrics": {
            "type": "analytics",
            "priority": 5,
            "required": True,
            "tools": [
                {
                    "name": "search_performance_data",
                    "intent_types": ["metrics", "trends", "summary"],
                    "timeout": 30,
                    "retry_count": 3,
                    "default_args": {
                        "format": "json",
                        "limit": 10000
                    },
                    "argument_mapping": {
                        "metrics": {
                            "source": "entities",
                            "field": "metrics",
                            "transform": "list"
                        },
                        "dimensions": {
                            "source": "entities", 
                            "field": "dimensions",
                            "transform": "list"
                        },
                        "filters": {
                            "source": "filters",
                            "field": "*"
                        }
                    }
                },
                {
                    "name": "get_metric_definitions",
                    "intent_types": ["summary", "detailed"],
                    "timeout": 10,
                    "retry_count": 2,
                    "default_args": {
                        "include_metadata": True
                    },
                    "argument_mapping": {}
                }
            ]
        },
        
        "campaign_data": {
            "type": "marketing",
            "priority": 4,
            "required": True,
            "tools": [
                {
                    "name": "search_campaign_performance",
                    "intent_types": ["metrics", "trends", "comparison"],
                    "timeout": 45,
                    "retry_count": 3,
                    "default_args": {
                        "format": "json",
                        "include_costs": True,
                        "include_conversions": True
                    },
                    "argument_mapping": {
                        "campaign_ids": {
                            "source": "entities",
                            "field": "campaigns",
                            "transform": "list"
                        },
                        "channels": {
                            "source": "filters",
                            "field": "channel",
                            "transform": "list"
                        },
                        "status": {
                            "source": "filters",
                            "field": "status",
                            "transform": "lowercase"
                        }
                    }
                },
                {
                    "name": "get_campaign_hierarchy",
                    "intent_types": ["summary", "detailed"],
                    "timeout": 15,
                    "retry_count": 2,
                    "default_args": {},
                    "argument_mapping": {}
                }
            ]
        },
        
        "user_analytics": {
            "type": "user_behavior",
            "priority": 3,
            "required": False,
            "tools": [
                {
                    "name": "search_user_behavior",
                    "intent_types": ["metrics", "trends", "detailed"],
                    "timeout": 60,
                    "retry_count": 3,
                    "default_args": {
                        "format": "json",
                        "include_demographics": True,
                        "anonymize": True
                    },
                    "argument_mapping": {
                        "segments": {
                            "source": "filters",
                            "field": "segment",
                            "transform": "list"
                        },
                        "behaviors": {
                            "source": "entities",
                            "field": "behaviors",
                            "transform": "list"
                        },
                        "cohort": {
                            "source": "filters",
                            "field": "cohort"
                        }
                    }
                },
                {
                    "name": "get_retention_metrics",
                    "intent_types": ["trends", "metrics"],
                    "timeout": 30,
                    "retry_count": 2,
                    "default_args": {
                        "format": "json",
                        "periods": ["1d", "7d", "30d"]
                    },
                    "argument_mapping": {}
                }
            ]
        },
        
        "financial_data": {
            "type": "finance",
            "priority": 4,
            "required": True,
            "tools": [
                {
                    "name": "search_financial_metrics",
                    "intent_types": ["metrics", "trends", "summary"],
                    "timeout": 30,
                    "retry_count": 3,
                    "default_args": {
                        "format": "json",
                        "currency": "USD",
                        "precision": 2
                    },
                    "argument_mapping": {
                        "metric_types": {
                            "source": "entities",
                            "field": "financial_metrics",
                            "transform": "list"
                        },
                        "breakdown": {
                            "source": "entities",
                            "field": "dimensions",
                            "transform": "list"
                        }
                    }
                },
                {
                    "name": "get_revenue_breakdown",
                    "intent_types": ["detailed", "comparison"],
                    "timeout": 45,
                    "retry_count": 2,
                    "default_args": {
                        "format": "json",
                        "include_costs": True
                    },
                    "argument_mapping": {
                        "product_lines": {
                            "source": "filters",
                            "field": "product",
                            "transform": "list"
                        }
                    }
                }
            ]
        },
        
        "operational_data": {
            "type": "operations",
            "priority": 2,
            "required": False,
            "tools": [
                {
                    "name": "search_system_metrics",
                    "intent_types": ["metrics", "trends"],
                    "timeout": 20,
                    "retry_count": 2,
                    "default_args": {
                        "format": "json",
                        "include_alerts": True
                    },
                    "argument_mapping": {
                        "services": {
                            "source": "filters",
                            "field": "service",
                            "transform": "list"
                        },
                        "metric_types": {
                            "source": "entities",
                            "field": "system_metrics",
                            "transform": "list"
                        }
                    }
                },
                {
                    "name": "get_uptime_reports",
                    "intent_types": ["summary", "detailed"],
                    "timeout": 15,
                    "retry_count": 1,
                    "default_args": {
                        "format": "json"
                    },
                    "argument_mapping": {}
                }
            ]
        }
    }


def get_tool_priority_mapping() -> Dict[str, int]:
    """Get priority mapping for MCP tools."""
    return {
        "search_performance_data": 10,
        "search_campaign_performance": 9,
        "search_financial_metrics": 8,
        "search_user_behavior": 7,
        "get_metric_definitions": 6,
        "get_campaign_hierarchy": 5,
        "get_retention_metrics": 4,
        "get_revenue_breakdown": 3,
        "search_system_metrics": 2,
        "get_uptime_reports": 1,
    }


def get_common_entity_mappings() -> Dict[str, list]:
    """Get common entity type mappings for query understanding."""
    return {
        "metrics": [
            "conversion_rate", "click_through_rate", "cost_per_click", "revenue",
            "users", "sessions", "pageviews", "bounce_rate", "engagement_rate",
            "retention_rate", "churn_rate", "lifetime_value", "roi", "roas"
        ],
        "dimensions": [
            "channel", "campaign", "date", "device", "location", "segment",
            "product", "category", "source", "medium", "platform", "cohort"
        ],
        "time_periods": [
            "today", "yesterday", "this week", "last week", "this month",
            "last month", "this quarter", "last quarter", "this year", "last year"
        ],
        "channels": [
            "google_ads", "facebook", "instagram", "linkedin", "twitter",
            "email", "organic", "direct", "referral", "paid_search", "display"
        ]
    }