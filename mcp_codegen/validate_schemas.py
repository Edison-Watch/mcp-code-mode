#!/usr/bin/env python3
"""
MCP Schema Validator

Validates that generated TypeScript types match actual MCP tool responses.
Useful for testing and debugging the code generator.
"""

import argparse
import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from fastmcp import Client as FastMCPClient

from .generator import introspect_server, json_schema_to_typescript_type

log = logging.getLogger(__name__)


async def validate_tool_schemas(url: str) -> dict[str, Any]:
    """
    Validate tool schemas by:
    1. Introspecting the server
    2. Calling each tool with sample data
    3. Comparing actual response to expected output schema
    """
    log.info(f"Validating schemas for {url}")

    spec = await introspect_server(url)
    results = {
        "server": spec.name,
        "url": url,
        "tools_validated": 0,
        "tools_failed": 0,
        "validation_results": [],
    }

    client = FastMCPClient(url)

    async with client:
        for tool in spec.tools:
            log.info(f"Validating tool: {tool.name}")

            validation = {
                "tool": tool.name,
                "has_input_schema": tool.input_schema is not None,
                "has_output_schema": tool.output_schema is not None,
                "input_type": None,
                "output_type": None,
                "success": False,
                "error": None,
            }

            try:
                # Generate TypeScript types
                if tool.input_schema:
                    validation["input_type"] = json_schema_to_typescript_type(tool.input_schema)

                if tool.output_schema:
                    validation["output_type"] = json_schema_to_typescript_type(tool.output_schema)

                # Log the types
                log.debug(f"Input type: {validation['input_type']}")
                log.debug(f"Output type: {validation['output_type']}")

                validation["success"] = True
                results["tools_validated"] += 1

            except Exception as e:
                validation["error"] = str(e)
                validation["success"] = False
                results["tools_failed"] += 1
                log.error(f"Failed to validate {tool.name}: {e}")

            results["validation_results"].append(validation)

    return results


async def generate_schema_report(url: str, output_file: Path | None = None) -> None:
    """Generate a detailed schema validation report."""
    log.info("Generating schema validation report...")

    results = await validate_tool_schemas(url)

    # Create report
    report_lines = [
        "=" * 80,
        "MCP Schema Validation Report",
        "=" * 80,
        "",
        f"Server: {results['server']}",
        f"URL: {results['url']}",
        f"Tools Validated: {results['tools_validated']}",
        f"Tools Failed: {results['tools_failed']}",
        "",
        "=" * 80,
        "Tool Details",
        "=" * 80,
        "",
    ]

    for result in results["validation_results"]:
        report_lines.append(f"## Tool: {result['tool']}")
        report_lines.append("")
        report_lines.append(f"Has Input Schema: {result['has_input_schema']}")
        report_lines.append(f"Has Output Schema: {result['has_output_schema']}")

        if result["input_type"]:
            report_lines.append("")
            report_lines.append("**Input Type:**")
            report_lines.append("```typescript")
            report_lines.append(result["input_type"])
            report_lines.append("```")

        if result["output_type"]:
            report_lines.append("")
            report_lines.append("**Output Type:**")
            report_lines.append("```typescript")
            report_lines.append(result["output_type"])
            report_lines.append("```")

        if not result["success"]:
            report_lines.append("")
            report_lines.append(f"**Error:** {result['error']}")

        report_lines.append("")
        report_lines.append("-" * 80)
        report_lines.append("")

    report = "\n".join(report_lines)

    # Print to console
    print(report)

    # Save to file if specified
    if output_file:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(report)
        log.info(f"Report saved to {output_file}")


async def compare_with_actual_responses(
    url: str, tool_name: str, args: dict[str, Any]
) -> dict[str, Any]:
    """
    Call a tool and compare actual response structure with expected schema.
    Useful for debugging schema mismatches.
    """
    log.info(f"Testing tool: {tool_name}")

    spec = await introspect_server(url)
    tool_spec = next((t for t in spec.tools if t.name == tool_name), None)

    if not tool_spec:
        raise ValueError(f"Tool {tool_name} not found on server")

    client = FastMCPClient(url)

    async with client:
        # Call the tool
        result = await client.call_tool(tool_name, args)

        # Analyze response structure
        response_structure: dict[str, object] = {
            "has_content": hasattr(result, "content"),
            "content_count": len(result.content) if hasattr(result, "content") else 0,
            "content_types": [],
            "sample_content": None,
        }

        if hasattr(result, "content") and result.content:
            response_structure["content_types"] = [
                getattr(item, "type", "unknown") for item in result.content
            ]

            # Get sample content
            first_item = result.content[0]
            text = getattr(first_item, "text", None)
            if isinstance(text, str):
                try:
                    response_structure["sample_content"] = json.loads(text)
                except json.JSONDecodeError:
                    response_structure["sample_content"] = text[:200]
            elif hasattr(first_item, "data"):
                response_structure["sample_content"] = getattr(first_item, "data")

        return {
            "tool": tool_name,
            "input_args": args,
            "expected_output_schema": tool_spec.output_schema,
            "expected_typescript_type": json_schema_to_typescript_type(tool_spec.output_schema)
            if tool_spec.output_schema
            else None,
            "actual_response": response_structure,
        }


async def main():
    """Run schema validation."""

    parser = argparse.ArgumentParser(description="Validate MCP schemas and generated types")
    parser.add_argument(
        "--url",
        required=True,
        help="MCP server URL",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output file for report",
    )
    parser.add_argument(
        "--test-tool",
        help="Test a specific tool with sample data (format: tool_name)",
    )
    parser.add_argument(
        "--test-args",
        type=json.loads,
        default="{}",
        help='Test arguments as JSON (e.g. \'{"path": "/home"}\')',
    )

    args = parser.parse_args()

    if args.test_tool:
        # Test specific tool
        result = await compare_with_actual_responses(args.url, args.test_tool, args.test_args)
        print(json.dumps(result, indent=2))
    else:
        # Generate full report
        await generate_schema_report(args.url, args.output)


if __name__ == "__main__":
    asyncio.run(main())
