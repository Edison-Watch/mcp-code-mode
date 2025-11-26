"""
TypeScript code executor using Deno for sandboxed execution.

Deno provides:
- Secure by default (no network, file system, or env access without explicit permission)
- Native TypeScript support (no transpilation needed)
- Configurable permissions model
- Import maps to control module resolution
"""

import asyncio
import json
import logging
import re
import shutil
import tempfile
from asyncio.subprocess import PIPE
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .validator import CodeValidator, ValidationResult

log = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result of code execution."""

    success: bool
    output: str
    error: str | None
    exit_code: int
    validation: ValidationResult | None = None


class CodeExecutor:
    """Executes TypeScript code in a sandboxed Deno environment."""

    def __init__(
        self,
        mcp_libraries_path: Path | None = None,
        allowed_imports: list[str] | None = None,
        timeout_seconds: int = 30,
        validate_before_execution: bool = True,
        allowed_net_hosts: list[str] | None = None,
    ):
        """
        Initialize the code executor.

        Args:
            mcp_libraries_path: Path to generated MCP client libraries (optional)
            allowed_imports: List of allowed import prefixes for validation
            timeout_seconds: Maximum execution time
            validate_before_execution: Whether to validate code before executing
            allowed_net_hosts: List of allowed network hosts (e.g., ["localhost:3000"])
        """
        self.mcp_libraries_path = mcp_libraries_path
        self.timeout_seconds = timeout_seconds
        self.validate_before_execution = validate_before_execution
        self.allowed_net_hosts = allowed_net_hosts or ["localhost:3000"]
        self.validator = CodeValidator(allowed_imports=allowed_imports)

    async def execute(self, code: str, env: dict[str, str] | None = None) -> ExecutionResult:  # noqa: C901
        """
        Execute TypeScript code in a sandboxed environment.

        Args:
            code: TypeScript code to execute
            env: Environment variables to pass to the sandbox

        Returns:
            ExecutionResult with execution details
        """
        validation_result: ValidationResult | None = None

        # Validate code first if enabled
        if self.validate_before_execution:
            log.info("Validating code before execution...")
            validation_result = await self.validator.validate(code)

            if not validation_result.valid:
                log.error(f"Code validation failed: {validation_result.errors}")
                return ExecutionResult(
                    success=False,
                    output="",
                    error=f"Validation failed: {', '.join(validation_result.errors)}",
                    exit_code=-1,
                    validation=validation_result,
                )

            if validation_result.warnings:
                log.warning(f"Code validation warnings: {validation_result.warnings}")

        # Create temporary directory for execution
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            code_file = temp_path / "code.ts"
            import_map_file = temp_path / "import_map.json"

            # Write code to file
            code_file.write_text(code, encoding="utf-8")

            # Create import map to redirect imports to MCP libraries
            import_map = self._create_import_map()
            import_map_file.write_text(json.dumps(import_map, indent=2), encoding="utf-8")

            # Build Deno command with strict permissions
            deno_cmd_base = self._find_deno()

            # Build network permission flag
            net_permission = f"--allow-net={','.join(self.allowed_net_hosts)}"

            deno_cmd = [
                deno_cmd_base,
                "run",
                # Permissions (start with none, grant only what's needed)
                "--no-prompt",  # Don't ask for permissions
                net_permission,  # Allow network access only to specified hosts
                "--import-map",
                str(import_map_file),
            ]

            # Add read permission for MCP libraries if path is set
            if self.mcp_libraries_path and self.mcp_libraries_path.exists():
                deno_cmd.append(f"--allow-read={self.mcp_libraries_path}")

            deno_cmd.append(str(code_file))

            log.debug(f"Executing Deno command: {' '.join(deno_cmd)}")

            try:
                # Execute with timeout
                process = await asyncio.create_subprocess_exec(
                    *deno_cmd,
                    stdout=PIPE,
                    stderr=PIPE,
                    env={**env} if env else None,
                )

                try:
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(), timeout=self.timeout_seconds
                    )
                except TimeoutError:
                    log.error(f"Code execution timed out after {self.timeout_seconds}s")
                    process.kill()
                    await process.communicate()
                    return ExecutionResult(
                        success=False,
                        output="",
                        error=f"Execution timed out after {self.timeout_seconds}s",
                        exit_code=-1,
                        validation=validation_result,
                    )

                output = stdout.decode("utf-8")
                error_output = stderr.decode("utf-8")
                exit_code = process.returncode or 0

                # Strip ANSI color codes from error output
                if error_output:
                    ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
                    error_output = ansi_escape.sub("", error_output)

                success = exit_code == 0
                if not success:
                    log.error(f"Code execution failed with exit code {exit_code}")
                    log.error(f"Error output: {error_output}")

                return ExecutionResult(
                    success=success,
                    output=output,
                    error=error_output if error_output else None,
                    exit_code=exit_code,
                    validation=validation_result,
                )

            except FileNotFoundError:
                log.error("Deno not found. Please install Deno: https://deno.land/")
                return ExecutionResult(
                    success=False,
                    output="",
                    error="Deno not found. Please install Deno: https://deno.land/",
                    exit_code=-1,
                    validation=validation_result,
                )
            except Exception as e:
                log.exception("Error executing code")
                return ExecutionResult(
                    success=False,
                    output="",
                    error=f"Execution error: {e}",
                    exit_code=-1,
                    validation=validation_result,
                )

    def _find_deno(self) -> str:
        """Find the Deno executable."""
        if shutil.which("deno"):
            return "deno"

        # Try standard installation location
        home_deno = Path.home() / ".deno" / "bin" / "deno"
        if home_deno.exists():
            log.debug(f"Using Deno from: {home_deno}")
            return str(home_deno)

        return "deno"  # Let it fail with a helpful error

    def _create_import_map(self) -> dict[str, Any]:  # noqa: C901
        """
        Create an import map for Deno to resolve MCP library imports.

        Scans the actual generated code to find what it imports, then maps those.
        """
        import_map: dict[str, Any] = {"imports": {}}

        if not self.mcp_libraries_path or not self.mcp_libraries_path.exists():
            return import_map

        import_pattern = re.compile(r"from\s+['\"]([^'\"]+)['\"]")

        # Scan for generated libraries
        for server_dir in self.mcp_libraries_path.iterdir():
            if server_dir.is_dir():
                # Map @mcp-codegen/{server} to the generated dist/index.js
                package_name = f"@mcp-codegen/{server_dir.name}"
                entry_point = server_dir / "dist" / "index.js"

                if entry_point.exists():
                    # Use absolute path or file:// URL
                    import_map["imports"][package_name] = str(entry_point.resolve())
                    log.debug(f"Mapped {package_name} -> {entry_point}")

                    # Scan actual imports from generated code
                    node_modules = server_dir / "node_modules"
                    dist_dir = server_dir / "dist"
                    sdk_dir = (
                        node_modules / "@modelcontextprotocol" / "sdk" / "dist" / "esm"
                        if node_modules.exists()
                        else None
                    )

                    # Collect all imports
                    all_imports: set[str] = set()

                    # Scan generated library
                    if dist_dir.exists():
                        for js_file in dist_dir.rglob("*.js"):
                            try:
                                content = js_file.read_text()
                                for match in import_pattern.finditer(content):
                                    imp = match.group(1)
                                    if not imp.startswith("."):
                                        all_imports.add(imp)
                            except Exception:
                                pass

                    # Scan SDK files for transitive dependencies
                    if sdk_dir and sdk_dir.exists():
                        for js_file in sdk_dir.rglob("*.js"):
                            try:
                                content = js_file.read_text()
                                for match in import_pattern.finditer(content):
                                    imp = match.group(1)
                                    if not imp.startswith(".") and not imp.startswith("node:"):
                                        all_imports.add(imp)
                            except Exception:
                                pass

                    # Map the imports we found
                    for imp in all_imports:
                        if imp.startswith("@modelcontextprotocol/"):
                            # Map MCP SDK imports to ESM paths
                            parts = imp.split("/")
                            if len(parts) >= 2:
                                sdk_path = node_modules / parts[0] / parts[1]
                                if sdk_path.exists():
                                    rel_path = "/".join(parts[2:])
                                    full_path = sdk_path / "dist" / "esm" / rel_path
                                    if full_path.exists():
                                        import_map["imports"][imp] = str(full_path.resolve())
                                        log.debug(f"Mapped {imp} -> {full_path}")
                        elif not imp.startswith("node:"):
                            # Regular npm package - use npm: specifier
                            if imp not in import_map["imports"]:
                                import_map["imports"][imp] = f"npm:{imp}"
                                log.debug(f"Mapped {imp} -> npm:{imp}")
                else:
                    log.warning(
                        f"Generated library {server_dir.name} found but not built. "
                        "Run 'npm run build' in the library directory."
                    )

        return import_map

    async def execute_file(
        self, file_path: Path, env: dict[str, str] | None = None
    ) -> ExecutionResult:
        """
        Execute a TypeScript file.

        Args:
            file_path: Path to the TypeScript file
            env: Environment variables to pass to the sandbox

        Returns:
            ExecutionResult with execution details
        """
        try:
            code = file_path.read_text(encoding="utf-8")
            return await self.execute(code, env)
        except Exception as e:
            return ExecutionResult(
                success=False,
                output="",
                error=f"Failed to read file: {e}",
                exit_code=-1,
            )


async def main() -> None:
    """Test the executor."""
    executor = CodeExecutor(
        allowed_imports=["@mcp-codegen/"],
        timeout_seconds=10,
    )

    # Test code that uses basic TypeScript
    test_code = """
    // Example: Basic TypeScript execution
    console.log("Starting code mode execution...");

    const result = {
        status: "ok",
        message: "Code mode execution successful",
    };

    console.log(JSON.stringify(result, null, 2));
    """

    print("Executing test code...")
    result = await executor.execute(test_code)

    print(f"\n{'=' * 60}")
    print(f"Success: {result.success}")
    print(f"Exit Code: {result.exit_code}")
    print(f"{'=' * 60}")
    print(f"\nOutput:\n{result.output}")
    if result.error:
        print(f"\nError:\n{result.error}")
    if result.validation:
        print("\nValidation:")
        print(f"  Valid: {result.validation.valid}")
        print(f"  Errors: {result.validation.errors}")
        print(f"  Warnings: {result.validation.warnings}")
        print(f"  Imports: {result.validation.imports}")


if __name__ == "__main__":
    asyncio.run(main())
