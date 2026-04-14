#!/usr/bin/env python3
"""
Advanced MCP Code Generator

This module extends the basic generator with additional features:
- Support for batch generation from multiple servers
- Caching of introspected schemas
- Validation of generated TypeScript
- Automatic npm install and build
"""

import argparse
import asyncio
import json
import logging
import subprocess
from pathlib import Path

from .generator import (
    PromptSpec,
    ResourceSpec,
    ServerSpec,
    ToolSpec,
    generate_library,
    introspect_server,
)

log = logging.getLogger(__name__)


class SchemaCache:
    """Cache introspected MCP server schemas to disk."""

    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_cache_file(self, url: str) -> Path:
        """Get cache file path for a server URL."""
        # Create a safe filename from URL
        safe_name = url.replace("://", "_").replace("/", "_").replace(":", "_")
        return self.cache_dir / f"{safe_name}.json"

    def load(self, url: str) -> ServerSpec | None:
        """Load cached schema for a server."""
        cache_file = self.get_cache_file(url)
        if not cache_file.exists():
            return None

        try:
            data = json.loads(cache_file.read_text())
            log.debug(f"Loaded cached schema for {url}")

            # Reconstruct ServerSpec from dict
            tools = [
                ToolSpec(
                    name=t["name"],
                    description=t["description"],
                    input_schema=t["input_schema"],
                    output_schema=t["output_schema"],
                )
                for t in data.get("tools", [])
            ]
            resources = [
                ResourceSpec(
                    uri=r["uri"],
                    name=r["name"],
                    description=r.get("description"),
                    mime_type=r.get("mime_type"),
                )
                for r in data.get("resources", [])
            ]
            prompts = [
                PromptSpec(
                    name=p["name"],
                    description=p.get("description"),
                    arguments=p.get("arguments"),
                )
                for p in data.get("prompts", [])
            ]

            return ServerSpec(
                name=data["name"],
                tools=tools,
                resources=resources,
                prompts=prompts,
            )
        except Exception as e:
            log.warning(f"Failed to load cache for {url}: {e}")
            return None

    def save(self, url: str, spec: ServerSpec) -> None:
        """Save schema to cache."""
        cache_file = self.get_cache_file(url)

        try:
            data = {
                "name": spec.name,
                "tools": [
                    {
                        "name": t.name,
                        "description": t.description,
                        "input_schema": t.input_schema,
                        "output_schema": t.output_schema,
                    }
                    for t in spec.tools
                ],
                "resources": [
                    {
                        "uri": r.uri,
                        "name": r.name,
                        "description": r.description,
                        "mime_type": r.mime_type,
                    }
                    for r in spec.resources
                ],
                "prompts": [
                    {
                        "name": p.name,
                        "description": p.description,
                        "arguments": p.arguments,
                    }
                    for p in spec.prompts
                ],
            }

            cache_file.write_text(json.dumps(data, indent=2))
            log.debug(f"Saved schema cache for {url}")
        except Exception as e:
            log.warning(f"Failed to save cache for {url}: {e}")


def run_npm_install(library_dir: Path) -> bool:
    """Run npm install in the generated library directory."""
    log.info(f"Running npm install in {library_dir}...")

    try:
        result = subprocess.run(
            ["npm", "install"],
            cwd=library_dir,
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode == 0:
            log.info("npm install completed successfully")
            return True
        log.error(f"npm install failed: {result.stderr}")
        return False

    except subprocess.TimeoutExpired:
        log.error("npm install timed out")
        return False
    except FileNotFoundError:
        log.warning("npm not found, skipping install")
        return False
    except Exception as e:
        log.error(f"npm install failed: {e}")
        return False


def run_npm_build(library_dir: Path) -> bool:
    """Run npm build in the generated library directory."""
    log.info(f"Building TypeScript in {library_dir}...")

    try:
        result = subprocess.run(
            ["npm", "run", "build"],
            cwd=library_dir,
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode == 0:
            log.info("TypeScript build completed successfully")
            return True
        log.error(f"Build failed: {result.stderr}")
        return False

    except subprocess.TimeoutExpired:
        log.error("Build timed out")
        return False
    except FileNotFoundError:
        log.warning("npm not found, skipping build")
        return False
    except Exception as e:
        log.error(f"Build failed: {e}")
        return False


async def generate_with_cache(
    url: str, output_dir: Path, cache: SchemaCache, use_cache: bool = True
) -> tuple[bool, str | None]:
    """Generate TypeScript wrapper with optional caching."""
    try:
        # Try to load from cache first
        spec = None
        if use_cache:
            spec = cache.load(url)
            if spec:
                log.info(f"Using cached schema for {url}")

        # Introspect if no cache
        if not spec:
            log.info(f"Introspecting {url}...")
            spec = await introspect_server(url)
            cache.save(url, spec)

        # Generate library
        generate_library(spec, output_dir)

        return True, spec.name

    except Exception as e:
        log.error(f"Failed to generate library for {url}: {e}")
        return False, str(e)


async def batch_generate(  # noqa: C901
    urls: list[str],
    output_dir: Path,
    cache_dir: Path | None = None,
    use_cache: bool = True,
    install: bool = False,
    build: bool = False,
) -> dict[str, dict]:
    """
    Generate TypeScript wrappers for multiple MCP servers.

    Args:
        urls: List of MCP server URLs
        output_dir: Output directory for generated libraries
        cache_dir: Directory to cache introspected schemas
        use_cache: Whether to use cached schemas
        install: Run npm install after generation
        build: Run npm build after generation (implies install)

    Returns:
        Dictionary mapping URLs to results
    """
    log.info(f"Generating TypeScript wrappers for {len(urls)} server(s)")

    # Setup cache
    if cache_dir is None:
        cache_dir = output_dir / ".cache"
    cache = SchemaCache(cache_dir)

    # Generate for each server
    results = {}
    for url in urls:
        success, result = await generate_with_cache(
            url, output_dir, cache, use_cache=use_cache
        )

        results[url] = {
            "success": success,
            "name": result if success else None,
            "error": result if not success else None,
        }

        # Run npm install/build if requested
        if success and (install or build):
            assert result is not None
            library_dir = output_dir / result
            if library_dir.exists():
                if install or build:
                    results[url]["npm_install"] = run_npm_install(library_dir)
                if build:
                    results[url]["npm_build"] = run_npm_build(library_dir)

    # Print summary
    success_count = sum(1 for r in results.values() if r["success"])
    log.info(f"Successful: {success_count}/{len(urls)}")
    log.info(f"Failed: {len(urls) - success_count}/{len(urls)}")

    return results


async def main():  # noqa: C901
    """Main entry point for advanced generator."""
    parser = argparse.ArgumentParser(
        description="Advanced MCP Code Mode Generator with caching and auto-build"
    )
    parser.add_argument(
        "--url",
        action="append",
        help="MCP server URL(s) to generate wrappers for (can specify multiple)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="JSON config file with multiple server URLs",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("generated"),
        help="Output directory",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable schema caching",
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="Run npm install after generation",
    )
    parser.add_argument(
        "--build",
        action="store_true",
        help="Run npm build after generation (implies --install)",
    )

    args = parser.parse_args()

    # Collect server URLs
    urls: list[str] = []
    if args.url:
        urls.extend(args.url)
    if args.config:
        config_data = json.loads(args.config.read_text())
        urls.extend(config_data.get("servers", []))

    if not urls:
        parser.error("At least one --url or --config with servers is required")

    # Run batch generation
    results = await batch_generate(
        urls=urls,
        output_dir=args.output,
        use_cache=not args.no_cache,
        install=args.install,
        build=args.build,
    )

    # Print results
    log.info("\nGenerated libraries:")
    for url, result in results.items():
        if result["success"]:
            log.info(f"  - {result['name']} (from {url})")


if __name__ == "__main__":
    asyncio.run(main())

