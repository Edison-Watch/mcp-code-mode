#!/usr/bin/env python3
"""
MCP Codegen CLI

Generate TypeScript wrappers from an MCP server.

Usage:
    mcp-codegen --url http://localhost:3000/mcp/YOUR_API_KEY
    mcp-codegen --url https://api.example.com/mcp/ --auth "Bearer TOKEN"
"""

import argparse
import asyncio
import logging
import sys
import traceback
from pathlib import Path

from .generator import generate_library, introspect_server

log = logging.getLogger(__name__)


def setup_logging(verbose: bool = False) -> None:
    """Configure logging for the CLI."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


async def generate(args: argparse.Namespace) -> bool:
    """Generate TypeScript libraries from an MCP server."""
    output_dir = Path(args.output)

    log.info("=" * 80)
    log.info("Generating TypeScript wrappers from MCP Server")
    log.info("=" * 80)
    log.info(f"Server URL: {args.url}")
    log.info(f"Output directory: {output_dir}")
    log.info("")

    try:
        # Prepare headers if auth provided
        headers = None
        if args.auth:
            headers = {"Authorization": args.auth}
            log.info("Using authorization header")

        # Introspect the server
        log.info("Introspecting MCP server...")
        spec = await introspect_server(args.url, headers=headers)

        log.info("")
        log.info("Server Introspection Results:")
        log.info(f"   Server Name: {spec.name}")
        log.info(f"   Tools: {len(spec.tools)}")
        log.info(f"   Resources: {len(spec.resources)}")
        log.info(f"   Prompts: {len(spec.prompts)}")
        log.info("")

        if spec.tools:
            log.info("Available Tools:")
            for tool in spec.tools[:10]:  # Show first 10
                desc = (
                    tool.description[:60] + "..."
                    if tool.description and len(tool.description) > 60
                    else tool.description or "No description"
                )
                log.info(f"   - {tool.name}: {desc}")
            if len(spec.tools) > 10:
                log.info(f"   ... and {len(spec.tools) - 10} more")
            log.info("")

        if spec.resources:
            log.info("Available Resources:")
            for resource in spec.resources[:10]:  # Show first 10
                log.info(f"   - {resource.name} ({resource.uri})")
            if len(spec.resources) > 10:
                log.info(f"   ... and {len(spec.resources) - 10} more")
            log.info("")

        # Generate the TypeScript library
        log.info("Generating TypeScript library...")
        generate_library(spec, output_dir, default_url=args.url)

        server_dir = output_dir / spec.name
        log.info("")
        log.info("Generation complete!")
        log.info(f"Output directory: {server_dir}")
        log.info("")
        log.info("Generated files:")
        for file_path in sorted(server_dir.rglob("*")):
            if file_path.is_file() and not file_path.match("node_modules/*"):
                rel_path = file_path.relative_to(output_dir)
                size = file_path.stat().st_size
                log.info(f"   - {rel_path} ({size:,} bytes)")

        log.info("")
        log.info("Next steps:")
        log.info(f"   cd {server_dir}")
        log.info("   npm install")
        log.info("   npm run build")
        log.info("")
        log.info("Example usage:")
        log.info(f"   import {{ createClient }} from './{server_dir}/dist/index.js';")
        log.info("   ")
        log.info(f"   const client = createClient('{args.url}');")
        log.info("   await client.initialize();")
        log.info("   ")
        log.info("   // Use tools with full type safety")
        log.info("   const result = await client.tools.someToolName({ ... });")
        log.info("")

        # Show generated README
        readme_path = server_dir / "README.md"
        if readme_path.exists():
            log.info(f"See {readme_path} for full documentation")

        return True

    except Exception as e:
        log.error(f"\nGeneration failed: {e}")
        traceback.print_exc()
        return False


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Generate a TypeScript client library from an MCP server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate from a local MCP server
  mcp-codegen --url http://localhost:3000/mcp/YOUR_API_KEY

  # Remote server with auth header
  mcp-codegen --url https://api.example.com/mcp/ --auth "Bearer TOKEN"

  # Custom output directory
  mcp-codegen --url http://localhost:3000/mcp/KEY --output ./my-client
        """,
    )

    parser.add_argument(
        "--url",
        required=True,
        help="MCP server URL (including API key in path if needed)",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="generated",
        help="Output directory for generated library (default: generated)",
    )
    parser.add_argument(
        "--auth",
        help='Authorization header value (e.g., "Bearer TOKEN")',
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    setup_logging(args.verbose)

    success = asyncio.run(generate(args))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

