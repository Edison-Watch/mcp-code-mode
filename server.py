#!/usr/bin/env python3
"""
MCP Code Mode Server

A minimal FastMCP server that provides a secure TypeScript code execution tool.
LLMs can use this tool to execute multi-step operations more efficiently than
making individual tool calls.

Usage:
    python server.py

The server exposes a single tool:
    - code_mode: Execute TypeScript code in a sandboxed Deno environment
"""

import logging
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from mcp_code_mode import CodeExecutor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
log = logging.getLogger(__name__)

# Create the MCP server
mcp = FastMCP(
    name="mcp-code-mode",
    instructions="""
    This server provides a secure TypeScript code execution sandbox.

    Use the `code_mode` tool to execute TypeScript code that can:
    - Chain multiple operations without round-trips
    - Process data locally in the sandbox
    - Use generated MCP client libraries

    The code runs in a Deno sandbox with:
    - Limited network access (configurable)
    - No file system writes
    - AST validation before execution
    - Configurable timeout
    """,
)


@mcp.tool()
async def code_mode(
    code: str,
    timeout_seconds: int = 30,
    validate: bool = True,
    mcp_libraries_path: str | None = None,
    allowed_imports: list[str] | None = None,
    allowed_net_hosts: list[str] | None = None,
) -> dict[str, Any]:
    """
    Execute TypeScript code in a secure sandbox.

    This tool allows you to write TypeScript code that executes in a sandboxed
    Deno environment. This is more efficient for complex multi-step operations
    than making individual tool calls.

    The code runs with:
    - Limited network access (only to specified hosts)
    - No file system writes
    - AST validation to block dangerous patterns (eval, Function, etc.)
    - Configurable timeout

    Example:
    ```typescript
    // Simple computation
    const data = [1, 2, 3, 4, 5];
    const sum = data.reduce((a, b) => a + b, 0);
    console.log('Sum:', sum);
    ```

    Example with MCP client (if libraries are configured):
    ```typescript
    import { createClient } from '@mcp-codegen/filesystem';

    const client = createClient('http://localhost:3000/mcp/YOUR_KEY');
    await client.initialize();

    const files = await client.tools.filesystem.listDirectory({ path: '/tmp' });
    console.log('Files:', files);

    await client.close();
    ```

    Args:
        code: TypeScript code to execute
        timeout_seconds: Maximum execution time in seconds (default: 30)
        validate: Whether to validate code before execution (default: True)
        mcp_libraries_path: Path to generated MCP client libraries (optional)
        allowed_imports: List of allowed import prefixes (default: ["@mcp-codegen/"])
        allowed_net_hosts: List of allowed network hosts (default: ["localhost:3000"])

    Returns:
        Dictionary with execution results:
        - success: Whether execution completed successfully
        - output: stdout from the code
        - error: Error message if execution failed
        - exit_code: Process exit code
        - validation: Validation results (if validate=True)
    """
    log.info("Code mode tool called")

    # Set defaults
    if allowed_imports is None:
        allowed_imports = ["@mcp-codegen/", "@modelcontextprotocol/"]

    # Parse libraries path if provided
    libraries_path = Path(mcp_libraries_path) if mcp_libraries_path else None

    # Create executor
    executor = CodeExecutor(
        mcp_libraries_path=libraries_path,
        allowed_imports=allowed_imports,
        timeout_seconds=timeout_seconds,
        validate_before_execution=validate,
        allowed_net_hosts=allowed_net_hosts,
    )

    # Execute the code
    result = await executor.execute(code)

    # Build response
    response: dict[str, Any] = {
        "success": result.success,
        "exit_code": result.exit_code,
        "output": result.output,
    }

    if result.error:
        response["error"] = result.error

    if result.validation:
        response["validation"] = {
            "valid": result.validation.valid,
            "errors": result.validation.errors,
            "warnings": result.validation.warnings,
            "imports": result.validation.imports,
        }

    return response


@mcp.tool()
async def validate_code(
    code: str,
    allowed_imports: list[str] | None = None,
) -> dict[str, Any]:
    """
    Validate TypeScript code without executing it.

    This tool performs AST-based validation to check:
    - Import statements are from allowed sources
    - No dangerous patterns (eval, Function constructor, etc.)
    - No dynamic/computed imports

    Use this to pre-validate code before execution.

    Args:
        code: TypeScript code to validate
        allowed_imports: List of allowed import prefixes (default: ["@mcp-codegen/"])

    Returns:
        Dictionary with validation results:
        - valid: Whether the code passed validation
        - errors: List of validation errors
        - warnings: List of validation warnings
        - imports: List of imports found in the code
    """
    from mcp_code_mode import CodeValidator

    if allowed_imports is None:
        allowed_imports = ["@mcp-codegen/", "@modelcontextprotocol/"]

    validator = CodeValidator(allowed_imports=allowed_imports)
    result = await validator.validate(code)

    return {
        "valid": result.valid,
        "errors": result.errors,
        "warnings": result.warnings,
        "imports": result.imports,
        "has_dynamic_imports": result.has_dynamic_imports,
        "has_computed_imports": result.has_computed_imports,
    }


def main() -> None:
    """Run the MCP server."""
    log.info("Starting MCP Code Mode server...")
    mcp.run()


if __name__ == "__main__":
    main()
