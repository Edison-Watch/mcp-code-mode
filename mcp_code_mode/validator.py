"""
AST-based validation for TypeScript code before execution.

SECURITY MODEL:
- AST: Validates imports AND detects dangerous patterns (eval, Function, WebAssembly, etc.)
- Deno: Blocks operations requiring permissions (network, file system, env vars, etc.)

IMPORTANT: Deno does NOT block eval() or Function() by default. AST validation is our
primary defense against these. Deno only blocks things that require explicit permissions.

This follows "secure by default" - we don't enumerate dangers, we only allow what's safe.
"""

import asyncio
import json
import logging
import tempfile
from asyncio.subprocess import PIPE
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

log = logging.getLogger(__name__)


@dataclass
class ImportInfo:
    """Information about an import statement."""

    module: str
    type: str  # 'static', 'dynamic', 'require'
    line: int
    safe: bool  # False if computed/dynamic
    has_eval: bool = False
    has_function_constructor: bool = False
    has_web_assembly: bool = False
    has_workers: bool = False
    has_string_timeout: bool = False
    has_proto_access: bool = False
    has_global_access: bool = False
    has_reflect: bool = False
    has_constructor_chain: bool = False
    has_process_exit: bool = False
    has_deno_exit: bool = False


@dataclass
class ValidationResult:
    """Result of code validation."""

    valid: bool
    errors: list[str]
    warnings: list[str]
    imports: list[str]
    """List of import paths found in the code"""
    has_dynamic_imports: bool = False
    has_computed_imports: bool = False
    has_require: bool = False
    import_details: list[ImportInfo] | None = None
    safety_check_findings: dict[str, dict[str, Any]] | None = None


class CodeValidator:
    """
    Validates TypeScript code using AST analysis.

    SECURITY PHILOSOPHY:
    - We ONLY validate imports (the one thing we must control)
    - Everything else (eval, WebAssembly, network, etc.) is blocked by Deno sandbox
    - This avoids "security through enumeration" anti-pattern
    """

    def __init__(
        self,
        allowed_imports: list[str] | None = None,
        extractor_script_path: Path | None = None,
    ):
        """
        Initialize the validator.

        Args:
            allowed_imports: List of allowed import prefixes. If None, all imports are allowed.
                           Example: ['@mcp-codegen/', './generated/']
            extractor_script_path: Path to the extract_imports.mjs script.
                                  If None, uses the bundled script in js/ directory.
        """
        self.allowed_imports = allowed_imports or []
        self._extractor_script_path = extractor_script_path

    @property
    def extractor_script(self) -> Path:
        """Get the path to the AST extractor script."""
        if self._extractor_script_path:
            return self._extractor_script_path
        # Default: look for js/extract_imports.mjs relative to this package
        return Path(__file__).parent.parent / "js" / "extract_imports.mjs"

    async def validate(self, code: str) -> ValidationResult:  # noqa: C901
        """
        Validate TypeScript code using AST analysis.

        We ONLY validate imports here. All other security is handled by Deno sandbox.

        Args:
            code: TypeScript code to validate

        Returns:
            ValidationResult with validation status and details
        """
        errors: list[str] = []
        warnings: list[str] = []
        imports: list[str] = []
        has_dynamic = False
        has_computed = False
        has_require = False
        import_analysis: list[ImportInfo] | None = None
        safety_findings: dict[str, dict[str, Any]] | None = None

        try:
            # Create temporary file for the code
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".ts", delete=False, encoding="utf-8"
            ) as f:
                f.write(code)
                temp_file = Path(f.name)

            try:
                # Run TypeScript compiler to check syntax (optional, skip if tsc not found)
                try:
                    result = await asyncio.create_subprocess_exec(
                        "tsc",
                        "--noEmit",
                        "--allowJs",
                        "--checkJs",
                        "--target",
                        "esnext",
                        "--module",
                        "esnext",
                        "--skipLibCheck",
                        str(temp_file),
                        stdout=PIPE,
                        stderr=PIPE,
                    )

                    stdout, stderr = await result.communicate()

                    # Parse compiler output for errors
                    if result.returncode != 0:
                        output = stdout.decode() + stderr.decode()
                        # Only add as warning if there's actual TypeScript errors
                        if output.strip() and "Cannot find" not in output:
                            warnings.append(f"TypeScript compiler issues: {output}")
                except FileNotFoundError:
                    # tsc not found is OK - we'll still do AST validation
                    log.debug("TypeScript compiler (tsc) not found, skipping syntax check")

                # Extract imports using proper AST analysis
                import_analysis = await self._extract_imports_ast(temp_file)

                if import_analysis is None:
                    # FAIL CLOSED - Cannot validate imports securely
                    errors.append(
                        "AST analysis failed. Cannot securely validate imports. "
                        "Ensure Node.js is installed and extract_imports.mjs exists."
                    )
                    return ValidationResult(
                        valid=False,
                        errors=errors,
                        warnings=warnings,
                        imports=[],
                    )

                # Validate imports and check for dangerous patterns
                validation_errors = self._validate_imports(import_analysis)
                errors.extend(validation_errors)

                # Check for dangerous patterns detected by AST
                dangerous_errors = self._check_dangerous_patterns(import_analysis)
                errors.extend(dangerous_errors)

                imports = [imp.module for imp in import_analysis if imp.module != "<computed>"]
                has_dynamic = any(imp.type == "dynamic" for imp in import_analysis)
                has_computed = any(not imp.safe for imp in import_analysis)
                has_require = any(imp.type == "require" for imp in import_analysis)

                # Collect detailed safety check findings
                safety_findings = self._collect_safety_check_findings(import_analysis)

            finally:
                # Clean up temp file
                temp_file.unlink(missing_ok=True)

        except Exception as e:
            errors.append(f"Validation error: {e}")
            log.exception("Error during code validation")
            safety_findings = None

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            imports=imports,
            has_dynamic_imports=has_dynamic,
            has_computed_imports=has_computed,
            has_require=has_require,
            import_details=import_analysis,
            safety_check_findings=safety_findings,
        )

    def _validate_imports(self, import_analysis: list[ImportInfo]) -> list[str]:
        """
        Validate imports against allowed list.

        This is the ONLY security check we do in validation.
        Everything else is handled by Deno sandbox.
        """
        errors: list[str] = []

        # Check for computed/dynamic imports (security risk)
        unsafe_imports = [imp for imp in import_analysis if not imp.safe]
        if unsafe_imports:
            lines = ", ".join(str(imp.line) for imp in unsafe_imports)
            errors.append(
                f"Computed or dynamic imports detected at lines: {lines}. "
                "Only static string literal imports are allowed for security."
            )

        # Block require() - use import instead
        if any(imp.type == "require" for imp in import_analysis):
            errors.append("require() is not allowed. Use import statements instead.")

        # Validate imports against allowed list
        if self.allowed_imports:
            for imp_info in import_analysis:
                # Skip computed imports (already flagged above)
                if not imp_info.safe:
                    continue

                imp = imp_info.module
                if not any(imp.startswith(allowed) for allowed in self.allowed_imports):
                    errors.append(
                        f"Forbidden import: '{imp}' at line {imp_info.line}. "
                        f"Only {self.allowed_imports} are allowed."
                    )

        return errors

    def _check_dangerous_patterns(self, import_analysis: list[ImportInfo]) -> list[str]:  # noqa: C901
        """
        Check for dangerous patterns detected by AST analysis.

        Returns list of error messages for any dangerous patterns found.
        """
        errors: list[str] = []

        if any(imp.has_eval for imp in import_analysis):
            errors.append("Use of eval() is forbidden.")
        if any(imp.has_function_constructor for imp in import_analysis):
            errors.append("Use of Function() constructor is forbidden.")
        if any(imp.has_web_assembly for imp in import_analysis):
            errors.append("WebAssembly execution is forbidden.")
        if any(imp.has_workers for imp in import_analysis):
            errors.append("Web Workers are forbidden.")
        if any(imp.has_string_timeout for imp in import_analysis):
            errors.append("setTimeout/setInterval with string arguments is forbidden.")
        if any(imp.has_proto_access for imp in import_analysis):
            errors.append("Prototype pollution attempts are forbidden.")
        if any(imp.has_global_access for imp in import_analysis):
            errors.append("Dynamic global access (globalThis, window, self) is forbidden.")
        if any(imp.has_reflect for imp in import_analysis):
            errors.append("Reflective construction (Reflect.construct) is forbidden.")
        if any(imp.has_constructor_chain for imp in import_analysis):
            errors.append("Constructor chain access is forbidden.")
        if any(imp.has_process_exit for imp in import_analysis):
            errors.append("Calling process.exit is forbidden.")
        if any(imp.has_deno_exit for imp in import_analysis):
            errors.append("Calling Deno.exit is forbidden.")

        return errors

    def _collect_safety_check_findings(
        self, import_analysis: list[ImportInfo]
    ) -> dict[str, dict[str, Any]]:
        """
        Collect detailed findings for each safety check.

        Returns a dictionary mapping check names to their findings.
        """
        findings: dict[str, dict[str, Any]] = {}

        # Define what each check searches for
        check_definitions = {
            "import_validation": {
                "searched_for": [
                    "Static imports: import ... from 'module'",
                    "Dynamic imports: import('module')",
                    "Computed imports: import(variable)",
                    "require() calls: require('module')",
                ],
                "check_fn": lambda imps: [
                    imp for imp in imps if not imp.safe or imp.type == "require"
                ],
            },
            "eval_detection": {
                "searched_for": [
                    "eval() calls",
                    "globalThis.eval",
                    "window.eval",
                    "self.eval",
                ],
                "check_fn": lambda imps: [imp for imp in imps if imp.has_eval],
            },
            "function_constructor": {
                "searched_for": [
                    "new Function()",
                    "Function() constructor",
                    "Function.prototype.constructor",
                ],
                "check_fn": lambda imps: [imp for imp in imps if imp.has_function_constructor],
            },
            "webassembly": {
                "searched_for": [
                    "WebAssembly.instantiate()",
                    "WebAssembly.compile()",
                    "WebAssembly.instantiateStreaming()",
                ],
                "check_fn": lambda imps: [imp for imp in imps if imp.has_web_assembly],
            },
            "workers": {
                "searched_for": [
                    "new Worker()",
                    "new SharedWorker()",
                    "Worker creation",
                ],
                "check_fn": lambda imps: [imp for imp in imps if imp.has_workers],
            },
            "string_timeouts": {
                "searched_for": [
                    "setTimeout(string, ...)",
                    "setInterval(string, ...)",
                    "String-based timeout functions",
                ],
                "check_fn": lambda imps: [imp for imp in imps if imp.has_string_timeout],
            },
            "prototype_pollution": {
                "searched_for": [
                    "__proto__ access",
                    "Object.prototype manipulation",
                    "Prototype chain modification",
                ],
                "check_fn": lambda imps: [imp for imp in imps if imp.has_proto_access],
            },
            "global_access": {
                "searched_for": [
                    "globalThis['property']",
                    "window['property']",
                    "self['property']",
                    "Dynamic global property access",
                ],
                "check_fn": lambda imps: [imp for imp in imps if imp.has_global_access],
            },
            "reflect_construct": {
                "searched_for": [
                    "Reflect.construct()",
                    "Reflective construction",
                ],
                "check_fn": lambda imps: [imp for imp in imps if imp.has_reflect],
            },
            "constructor_chain": {
                "searched_for": [
                    "constructor.constructor",
                    "Constructor chain access",
                ],
                "check_fn": lambda imps: [imp for imp in imps if imp.has_constructor_chain],
            },
            "process_exit": {
                "searched_for": [
                    "process.exit()",
                    "process.exitCode",
                ],
                "check_fn": lambda imps: [imp for imp in imps if imp.has_process_exit],
            },
            "deno_exit": {
                "searched_for": [
                    "Deno.exit()",
                ],
                "check_fn": lambda imps: [imp for imp in imps if imp.has_deno_exit],
            },
        }

        # Collect findings for each check
        for check_name, check_def in check_definitions.items():
            check_fn = cast(Callable[[list[ImportInfo]], list[ImportInfo]], check_def["check_fn"])
            found_items = check_fn(import_analysis)
            findings[check_name] = {
                "check_name": check_name,
                "searched_for": check_def["searched_for"],
                "found": [
                    {
                        "line": imp.line,
                        "module": imp.module,
                        "type": imp.type,
                    }
                    for imp in found_items
                ],
                "detected": len(found_items) > 0,
            }

        return findings

    async def _extract_imports_ast(self, code_file: Path) -> list[ImportInfo] | None:
        """
        Extract import statements using proper TypeScript AST analysis.

        This catches ALL import obfuscation attempts:
        - Dynamic imports: import('module')
        - Computed imports: import(variable)
        - Template literals: import(`module`)
        - require() calls
        - Obfuscated imports

        Returns None if AST extraction fails (caller must fail closed).
        """
        extractor_script = self.extractor_script

        if not extractor_script.exists():
            log.error(f"AST extractor script not found at {extractor_script}")
            return None

        try:
            # Run Node.js script to extract imports via AST
            result = await asyncio.create_subprocess_exec(
                "node",
                str(extractor_script),
                str(code_file),
                stdout=PIPE,
                stderr=PIPE,
            )

            stdout, stderr = await result.communicate()

            if result.returncode != 0:
                log.error(f"AST extraction failed: {stderr.decode()}")
                return None

            # Parse JSON output
            analysis = json.loads(stdout.decode())

            # Convert to ImportInfo objects
            import_infos: list[ImportInfo] = []
            for imp in analysis.get("imports", []):
                import_infos.append(
                    ImportInfo(
                        module=imp["module"],
                        type=imp["type"],
                        line=imp["line"],
                        safe=imp["safe"],
                        has_eval=imp.get("has_eval", False),
                        has_function_constructor=imp.get("has_function_constructor", False),
                        has_web_assembly=imp.get("has_web_assembly", False),
                        has_workers=imp.get("has_workers", False),
                        has_string_timeout=imp.get("has_string_timeout", False),
                        has_proto_access=imp.get("has_proto_access", False),
                        has_global_access=imp.get("has_global_access", False),
                        has_reflect=imp.get("has_reflect", False),
                        has_constructor_chain=imp.get("has_constructor_chain", False),
                        has_process_exit=imp.get("has_process_exit", False),
                        has_deno_exit=imp.get("has_deno_exit", False),
                    )
                )

            return import_infos

        except FileNotFoundError:
            log.error("Node.js not found. Please install Node.js to run code mode.")
            return None
        except json.JSONDecodeError as e:
            log.error(f"Failed to parse AST extraction output: {e}")
            return None
        except Exception as e:
            log.exception(f"Error during AST import extraction: {e}")
            return None

    async def validate_file(self, file_path: Path) -> ValidationResult:
        """
        Validate a TypeScript file.

        Args:
            file_path: Path to the TypeScript file

        Returns:
            ValidationResult with validation status and details
        """
        try:
            code = file_path.read_text(encoding="utf-8")
            return await self.validate(code)
        except Exception as e:
            return ValidationResult(
                valid=False,
                errors=[f"Failed to read file: {e}"],
                warnings=[],
                imports=[],
            )


async def main() -> None:
    """Test the validator."""
    validator = CodeValidator(allowed_imports=["@mcp-codegen/"])

    # Test valid code
    valid_code = """
    import { createClient } from '@mcp-codegen/filesystem';

    async function main() {
        const client = createClient('http://localhost:3000/mcp/key');
        await client.initialize();
        const result = await client.tools.filesystem.readFile({ path: '/tmp/test.txt' });
        console.log(result);
    }

    main();
    """

    result = await validator.validate(valid_code)
    print(f"Valid code result: {result}")

    # Test invalid code with forbidden import
    invalid_code = """
    import { createClient } from '@mcp-codegen/filesystem';
    import axios from 'axios';  // Not allowed!

    async function main() {
        await axios.get('https://evil.com');  // Trying to bypass sandbox
    }
    """

    result = await validator.validate(invalid_code)
    print(f"Invalid code result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
