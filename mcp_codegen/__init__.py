"""
MCP Codegen - TypeScript Client Library Generator for MCP Servers

This package generates type-safe TypeScript client libraries from any MCP server
by introspecting its capabilities and generating strongly-typed wrappers.

Usage:
    # CLI
    mcp-codegen --url http://localhost:3000/mcp/YOUR_KEY --output ./generated

    # Library
    from mcp_codegen import generate_library, introspect_server

    spec = await introspect_server("http://localhost:3000/mcp/YOUR_KEY")
    generate_library(spec, Path("./generated"))
"""

from .advanced import (
    SchemaCache,
    batch_generate,
    generate_with_cache,
    run_npm_build,
    run_npm_install,
)
from .generator import (
    PromptSpec,
    ResourceSpec,
    ServerSpec,
    ToolSpec,
    generate_library,
    group_tools_by_server,
    introspect_server,
    json_schema_to_typescript_type,
    sanitize_name,
)

__all__ = [
    # Data classes
    "ServerSpec",
    "ToolSpec",
    "ResourceSpec",
    "PromptSpec",
    # Main functions
    "introspect_server",
    "generate_library",
    # Advanced
    "SchemaCache",
    "generate_with_cache",
    "batch_generate",
    "run_npm_install",
    "run_npm_build",
    # Utilities
    "json_schema_to_typescript_type",
    "sanitize_name",
    "group_tools_by_server",
]

__version__ = "0.1.0"

