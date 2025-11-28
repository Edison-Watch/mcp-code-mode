"""
TypeScript code executor using Deno for sandboxed execution.

Deno provides:
- Secure by default (no network, file system, or env access without explicit permission)
- Native TypeScript support (no transpilation needed)
- Configurable permissions model
- Import maps for module resolution

DOS Protection:
- Memory limit via V8 max-old-space-size flag
- Hard timeout cap to prevent unbounded execution
- Concurrency limit via semaphore
- Output size limit to prevent parent process OOM
"""

import asyncio
import contextlib
import json
import logging
import re
import shutil
import tempfile
from asyncio.subprocess import PIPE, Process
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .validator import CodeValidator, ValidationResult

log = logging.getLogger(__name__)

# DOS Protection Constants
MAX_TIMEOUT_SECONDS = 90
MAX_HEAP_SIZE_MB = 256
MAX_OUTPUT_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_CONCURRENT_EXECUTIONS = 3

_execution_semaphore = asyncio.Semaphore(MAX_CONCURRENT_EXECUTIONS)


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
        self.mcp_libraries_path = mcp_libraries_path
        self.timeout_seconds = timeout_seconds
        self.validate_before_execution = validate_before_execution
        self.allowed_net_hosts = allowed_net_hosts or ["localhost:3000"]
        self.validator = CodeValidator(allowed_imports=allowed_imports)

    async def execute(self, code: str, env: dict[str, str] | None = None) -> ExecutionResult:
        """Execute TypeScript code in a sandboxed environment."""
        validation_result: ValidationResult | None = None
        effective_timeout = min(self.timeout_seconds, MAX_TIMEOUT_SECONDS)

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

        async with _execution_semaphore:
            return await self._execute_sandboxed(code, env, effective_timeout, validation_result)

    async def _execute_sandboxed(
        self,
        code: str,
        env: dict[str, str] | None,
        timeout: int,
        validation_result: ValidationResult | None,
    ) -> ExecutionResult:
        """Run code in Deno sandbox."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            code_file = temp_path / "code.ts"
            import_map_file = temp_path / "import_map.json"

            # Wrap code to ensure clean exit (MCP client leaves handles open)
            wrapped_code = self._wrap_code_for_exit(code)
            code_file.write_text(wrapped_code, encoding="utf-8")

            # Create import map
            import_map = self._create_import_map()
            import_map_file.write_text(json.dumps(import_map, indent=2), encoding="utf-8")

            # Build Deno command
            deno_cmd = [
                self._find_deno(),
                "run",
                f"--v8-flags=--max-old-space-size={MAX_HEAP_SIZE_MB}",
                "--no-prompt",
                f"--allow-net={','.join(self.allowed_net_hosts)}",
                "--import-map",
                str(import_map_file),
            ]

            if self.mcp_libraries_path and self.mcp_libraries_path.exists():
                deno_cmd.append(f"--allow-read={self.mcp_libraries_path.resolve()}")

            deno_cmd.append(str(code_file))

            try:
                process = await asyncio.create_subprocess_exec(
                    *deno_cmd,
                    stdout=PIPE,
                    stderr=PIPE,
                    env={**env} if env else None,
                )

                try:
                    stdout, stderr = await asyncio.wait_for(
                        self._read_output_limited(process),
                        timeout=timeout,
                    )
                except TimeoutError:
                    log.error(f"Code execution timed out after {timeout}s")
                    process.kill()
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(process.communicate(), timeout=5)
                    return ExecutionResult(
                        success=False,
                        output="",
                        error=f"Execution timed out after {timeout}s",
                        exit_code=-1,
                        validation=validation_result,
                    )

                output = stdout.decode("utf-8", errors="replace")
                error_output = stderr.decode("utf-8", errors="replace")
                exit_code = process.returncode or 0

                # Strip ANSI codes from error output
                if error_output:
                    error_output = re.sub(
                        r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])", "", error_output
                    )

                return ExecutionResult(
                    success=exit_code == 0,
                    output=output,
                    error=error_output if error_output else None,
                    exit_code=exit_code,
                    validation=validation_result,
                )

            except FileNotFoundError:
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
        home_deno = Path.home() / ".deno" / "bin" / "deno"
        if home_deno.exists():
            return str(home_deno)
        return "deno"

    async def _read_output_limited(self, process: Process) -> tuple[bytes, bytes]:
        """Read stdout/stderr with size limits to prevent OOM."""

        async def read_limited(stream: asyncio.StreamReader | None) -> bytes:
            if stream is None:
                return b""
            data = b""
            while len(data) < MAX_OUTPUT_BYTES:
                chunk = await stream.read(min(4096, MAX_OUTPUT_BYTES - len(data)))
                if not chunk:
                    break
                data += chunk
            # Drain remainder to prevent deadlock
            while True:
                chunk = await stream.read(4096)
                if not chunk:
                    break
            return data

        stdout, stderr = await asyncio.gather(
            read_limited(process.stdout),
            read_limited(process.stderr),
        )
        await process.wait()
        return stdout, stderr

    def _wrap_code_for_exit(self, code: str) -> str:
        """
        Ensure code exits cleanly.

        The MCP TypeScript client doesn't fully clean up async handles,
        so we add Deno.exit() to ensure termination.
        """
        if "Deno.exit" in code:
            return code

        stripped = code.rstrip()

        # If code ends with promise chain like .then(...).catch(...);
        # add .finally(() => Deno.exit(0))
        if (".then(" in code or ".catch(" in code) and stripped.endswith(");"):
            return f"{stripped[:-1]}\n  .finally(() => Deno.exit(0));\n"

        # If code ends with simple function call like main();
        if re.search(r"\w+\(\)\s*;\s*$", stripped):
            return (
                re.sub(
                    r"(\w+)\(\)\s*;\s*$",
                    r"\1().then(() => Deno.exit(0)).catch((e) => { console.error(e); Deno.exit(1); });",
                    stripped,
                )
                + "\n"
            )

        # For code with imports, add exit at end
        if "import " in code:
            return f"{code}\nDeno.exit(0);\n"

        # Wrap in async IIFE
        return f"(async () => {{\n{code}\n}})().then(() => Deno.exit(0)).catch((e) => {{ console.error(e); Deno.exit(1); }});\n"

    def _create_import_map(self) -> dict[str, Any]:
        """Create import map for Deno to resolve MCP libraries and npm packages."""
        imports: dict[str, str] = {}

        if not self.mcp_libraries_path or not self.mcp_libraries_path.exists():
            return {"imports": imports}

        # Scan for generated libraries
        for server_dir in self.mcp_libraries_path.iterdir():
            if not server_dir.is_dir():
                continue

            entry_point = server_dir / "dist" / "index.js"
            if not entry_point.exists():
                continue

            # Map @mcp-codegen/{server} to generated library
            package_name = f"@mcp-codegen/{server_dir.name}"
            imports[package_name] = f"file://{entry_point.resolve()}"

            # Find node_modules for this library
            node_modules = server_dir / "node_modules"
            if not node_modules.exists():
                continue

            # Map MCP SDK imports to local ESM files
            sdk_esm = node_modules / "@modelcontextprotocol" / "sdk" / "dist" / "esm"
            if sdk_esm.exists():
                # Map base SDK
                sdk_index = sdk_esm / "index.js"
                if sdk_index.exists():
                    imports["@modelcontextprotocol/sdk"] = f"file://{sdk_index.resolve()}"

                # Map all SDK sub-paths
                for js_file in sdk_esm.rglob("*.js"):
                    rel_path = js_file.relative_to(sdk_esm)
                    import_path = str(rel_path).replace("\\", "/")
                    file_url = f"file://{js_file.resolve()}"

                    # Map with .js extension
                    imports[f"@modelcontextprotocol/sdk/{import_path}"] = file_url

                    # Also without .js for compatibility
                    if import_path.endswith(".js"):
                        imports[f"@modelcontextprotocol/sdk/{import_path[:-3]}"] = file_url

            # Scan generated code for npm dependencies
            dist_dir = server_dir / "dist"
            npm_deps = self._find_npm_imports(dist_dir, sdk_esm)

            # Map npm dependencies to npm: specifiers (Deno handles caching)
            for dep in npm_deps:
                if dep not in imports:
                    imports[dep] = f"npm:{dep}"

        return {"imports": imports}

    def _find_npm_imports(self, *dirs: Path | None) -> set[str]:
        """Scan directories for npm import statements."""
        pattern = re.compile(r"from\s+['\"]([^'\"]+)['\"]")
        deps: set[str] = set()

        for dir_path in dirs:
            if not dir_path or not dir_path.exists():
                continue
            for js_file in dir_path.rglob("*.js"):
                try:
                    for match in pattern.finditer(js_file.read_text()):
                        imp = match.group(1)
                        # Skip relative, node built-ins, and already-mapped imports
                        if (
                            not imp.startswith(".")
                            and not imp.startswith("node:")
                            and not imp.startswith("@modelcontextprotocol/")
                        ):
                            deps.add(imp)
                except Exception:
                    pass

        return deps

    async def execute_file(
        self, file_path: Path, env: dict[str, str] | None = None
    ) -> ExecutionResult:
        """Execute a TypeScript file."""
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

    test_code = """
    console.log("Code mode execution successful");
    console.log(JSON.stringify({ status: "ok" }, null, 2));
    """

    print("Executing test code...")
    result = await executor.execute(test_code)
    print(f"Success: {result.success}")
    print(f"Output: {result.output}")
    if result.error:
        print(f"Error: {result.error}")


if __name__ == "__main__":
    asyncio.run(main())
