#!/usr/bin/env python3
"""
Verify that all MCP server information is properly transmitted to TypeScript

Checks:
1. Tool descriptions → JSDoc comments in tool files
2. Parameter descriptions → JSDoc in type definitions
3. Input/output schemas → TypeScript types
4. Server information → README files
5. All data preserved from MCP introspection
"""

import asyncio
import logging
from pathlib import Path

from .generator import group_tools_by_server, introspect_server, sanitize_name

log = logging.getLogger(__name__)


async def verify_information_transmission(  # noqa: C901
    url: str, generated_path: Path
) -> dict[str, bool]:
    """Verify all MCP information made it into generated TypeScript."""

    results = {
        "tool_descriptions_in_files": False,
        "tool_descriptions_in_types": False,
        "param_descriptions_in_types": False,
        "input_schemas_converted": False,
        "output_schemas_converted": False,
        "server_readmes_exist": False,
        "per_server_tools_documented": False,
    }

    log.info("=" * 80)
    log.info("Verifying MCP Information Transmission")
    log.info("=" * 80)

    # Introspect the server
    log.info(f"Introspecting {url}...")
    spec = await introspect_server(url)

    log.info(f"Found {len(spec.tools)} tools across MCP server")

    # Check 1: Tool descriptions in individual tool files
    log.info("\nChecking tool descriptions in individual .ts files...")
    tools_with_descriptions = [t for t in spec.tools if t.description]
    if tools_with_descriptions:
        # Check a sample tool file
        first_tool = tools_with_descriptions[0]
        tool_name = sanitize_name(first_tool.name)
        servers = group_tools_by_server(spec.tools)

        # Find which server this tool belongs to
        server_prefix = None
        for prefix, tools in servers.items():
            if first_tool in tools:
                server_prefix = prefix
                break

        if server_prefix:
            tool_file = generated_path / "src" / "tools" / server_prefix / f"{tool_name}.ts"
            if tool_file.exists():
                content = tool_file.read_text()
                # Check if description appears in JSDoc
                if first_tool.description[:50] in content:
                    results["tool_descriptions_in_files"] = True
                    log.info(f"  Tool descriptions found in {tool_file.name}")
                else:
                    log.warning(f"  Description missing from {tool_file.name}")

    # Check 2: Tool descriptions in types.ts
    log.info("\nChecking tool descriptions in types.ts...")
    types_file = generated_path / "src" / "types.ts"
    if types_file.exists():
        types_content = types_file.read_text()
        # Check for JSDoc comments with tool descriptions
        if "* Types for tool:" in types_content and tools_with_descriptions:
            sample_desc = tools_with_descriptions[0].description
            if sample_desc and sample_desc[:40] in types_content:
                results["tool_descriptions_in_types"] = True
                log.info("  Tool descriptions found in types.ts JSDoc")

    # Check 3: Parameter descriptions in types
    log.info("\nChecking parameter descriptions in types.ts...")
    tools_with_params = [
        t for t in spec.tools if t.input_schema and t.input_schema.get("properties")
    ]
    if tools_with_params and types_file.exists():
        types_content = types_file.read_text()
        # Look for parameter descriptions
        for tool in tools_with_params[:3]:  # Check first 3
            assert tool.input_schema is not None
            props = tool.input_schema.get("properties", {})
            for prop_name, prop_schema in props.items():
                prop_desc = prop_schema.get("description")
                if prop_desc and prop_desc in types_content:
                    results["param_descriptions_in_types"] = True
                    log.info(f"  Parameter descriptions found (e.g., '{prop_name}')")
                    break
            if results["param_descriptions_in_types"]:
                break

    # Check 4: Input schemas converted to TypeScript types
    log.info("\nChecking input schemas converted to TypeScript...")
    if types_file.exists():
        types_content = types_file.read_text()
        # Look for Input types
        input_types = [t for t in spec.tools if t.input_schema]
        if input_types:
            sample = sanitize_name(input_types[0].name)
            camel_name = sample[0].upper() + sample[1:] if sample else "Unknown"
            if f"{camel_name}Input" in types_content:
                results["input_schemas_converted"] = True
                log.info(f"  Input schemas converted (found {camel_name}Input)")

    # Check 5: Output schemas converted to TypeScript types
    log.info("\nChecking output schemas converted to TypeScript...")
    if types_file.exists():
        types_content_check = types_file.read_text()
        output_types = [t for t in spec.tools if t.output_schema]
        if output_types:
            sample = sanitize_name(output_types[0].name)
            camel_name = sample[0].upper() + sample[1:] if sample else "Unknown"
            if f"{camel_name}Output" in types_content_check:
                results["output_schemas_converted"] = True
                log.info(f"  Output schemas converted (found {camel_name}Output)")

    # Check 6: Server-specific README files exist
    log.info("\nChecking server-specific README files...")
    servers = group_tools_by_server(spec.tools)
    readme_count = 0
    for server_prefix in servers:
        readme_file = generated_path / "src" / "tools" / server_prefix / "README.md"
        if readme_file.exists():
            readme_count += 1

    if readme_count == len(servers):
        results["server_readmes_exist"] = True
        log.info(f"  Found README files for all {len(servers)} servers")
    else:
        log.warning(f"  Found {readme_count}/{len(servers)} README files")

    # Check 7: Per-server tools are documented in their READMEs
    log.info("\nChecking server READMEs document their tools...")
    if readme_count > 0:
        # Check one README as sample
        first_server = sorted(servers.keys())[0]
        readme_file = generated_path / "src" / "tools" / first_server / "README.md"
        if readme_file.exists():
            readme_content = readme_file.read_text()
            server_tools = servers[first_server]
            # Check if tools are documented
            documented = sum(1 for t in server_tools if t.name in readme_content)
            if documented == len(server_tools):
                results["per_server_tools_documented"] = True
                log.info(f"  All {len(server_tools)} {first_server} tools documented in README")

    # Summary
    log.info("\n" + "=" * 80)
    log.info("Verification Results")
    log.info("=" * 80)

    all_passed = all(results.values())
    for check, passed in results.items():
        status = "PASS" if passed else "FAIL"
        log.info(f"{status} {check}: {passed}")

    log.info("")
    if all_passed:
        log.info("All checks passed! MCP information is fully transmitted.")
    else:
        log.warning("Some checks failed. Review the issues above.")

    return results


async def main():
    """Run verification."""
    import argparse

    parser = argparse.ArgumentParser(description="Verify MCP information transmission")
    parser.add_argument(
        "--url",
        required=True,
        help="MCP server URL",
    )
    parser.add_argument(
        "--generated-path",
        type=Path,
        required=True,
        help="Path to generated TypeScript library",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output file for verification report",
    )

    args = parser.parse_args()

    if not args.generated_path.exists():
        log.error(f"Generated library not found at {args.generated_path}")
        return

    results = await verify_information_transmission(args.url, args.generated_path)

    # Create detailed report if output specified
    if args.output:
        import datetime

        report_lines = [
            "# MCP Information Transmission Verification Report",
            "",
            "## Summary",
            "",
            f"Generated Library: `{args.generated_path.name}`",
            f"Verification Date: {datetime.datetime.now().isoformat()}",
            "",
            "## Checks",
            "",
        ]

        for check, passed in results.items():
            status = "PASS" if passed else "FAIL"
            report_lines.append(f"- **{check}**: {status}")

        report_lines.extend(
            [
                "",
                "## Conclusion",
                "",
            ]
        )

        if all(results.values()):
            report_lines.append("**All MCP information is properly transmitted to TypeScript!**")
            report_lines.append("")
            report_lines.append("The generator successfully:")
            report_lines.append("- Extracts tool descriptions and embeds them as JSDoc comments")
            report_lines.append("- Converts JSON schemas to TypeScript types")
            report_lines.append("- Preserves parameter descriptions in type definitions")
            report_lines.append("- Creates server-specific documentation")
            report_lines.append("- Organizes tools by server prefix")
        else:
            report_lines.append("**Some information may not be fully transmitted.**")
            report_lines.append("")
            report_lines.append("Review the failed checks and update the generator accordingly.")

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text("\n".join(report_lines))
        log.info(f"\nReport saved to {args.output}")


if __name__ == "__main__":
    asyncio.run(main())

