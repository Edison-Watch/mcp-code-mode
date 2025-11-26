"""
MCP Code Mode - TypeScript Code Execution Sandbox

A secure sandbox for executing TypeScript code in Deno with AST-based validation.
Designed for use with MCP (Model Context Protocol) tool execution.

Features:
- Secure Deno sandbox with configurable permissions
- AST-based validation to block dangerous patterns (eval, Function, etc.)
- Import validation to restrict modules
- Timeout protection
"""

from .executor import CodeExecutor, ExecutionResult
from .validator import CodeValidator, ImportInfo, ValidationResult

__all__ = [
    "CodeExecutor",
    "CodeValidator",
    "ExecutionResult",
    "ValidationResult",
    "ImportInfo",
]

__version__ = "0.1.0"
