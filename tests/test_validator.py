"""
Tests for CodeValidator.

Tests the AST-based validation of TypeScript code.
"""

import pytest

from mcp_code_mode import CodeValidator


@pytest.fixture
def validator() -> CodeValidator:
    """Create a code validator instance."""
    return CodeValidator(allowed_imports=["@mcp-codegen/", "@modelcontextprotocol/"])


class TestCodeValidator:
    """Tests for CodeValidator."""

    @pytest.mark.asyncio
    async def test_validate_simple_code(self, validator: CodeValidator) -> None:
        """Test validation of simple TypeScript code."""
        code = """
        const x: number = 42;
        console.log(x);
        """

        result = await validator.validate(code)
        assert result.valid
        assert len(result.errors) == 0

    @pytest.mark.asyncio
    async def test_validate_with_allowed_import(self, validator: CodeValidator) -> None:
        """Test validation with an allowed import."""
        code = """
        import { createClient } from '@mcp-codegen/filesystem';

        const client = createClient('http://localhost:3000/mcp/key');
        """

        result = await validator.validate(code)
        assert result.valid
        assert "@mcp-codegen/filesystem" in result.imports

    @pytest.mark.asyncio
    async def test_validate_with_forbidden_import(self, validator: CodeValidator) -> None:
        """Test validation rejects forbidden imports."""
        code = """
        import axios from 'axios';  // Not allowed!
        import fs from 'node:fs';    // Not allowed!

        await axios.get('https://evil.com');
        """

        result = await validator.validate(code)
        assert not result.valid
        assert any("Forbidden import" in error for error in result.errors)
        assert "axios" in result.imports
        assert "node:fs" in result.imports

    @pytest.mark.asyncio
    async def test_validate_detects_eval(self, validator: CodeValidator) -> None:
        """Test validation detects dangerous eval() usage."""
        code = """
        const code = "console.log('hacked')";
        eval(code);  // Dangerous!
        """

        result = await validator.validate(code)
        assert not result.valid
        assert any("eval()" in error for error in result.errors)

    @pytest.mark.asyncio
    async def test_validate_detects_function_constructor(self, validator: CodeValidator) -> None:
        """Test validation detects dangerous Function() constructor."""
        code = """
        const fn = new Function('return 123');
        fn();
        """

        result = await validator.validate(code)
        assert not result.valid
        assert any("Function() constructor" in error for error in result.errors)

    @pytest.mark.asyncio
    async def test_validate_detects_indirect_eval(self, validator: CodeValidator) -> None:
        """Test validation detects indirect eval access (globalThis.eval, window.eval)."""
        code = """
        globalThis.eval("console.log('hacked')");
        """

        result = await validator.validate(code)
        assert not result.valid
        assert any("eval()" in error for error in result.errors)

    @pytest.mark.asyncio
    async def test_validate_detects_function_prototype_constructor(
        self, validator: CodeValidator
    ) -> None:
        """Test validation detects Function.prototype.constructor."""
        code = """
        const fn = new Function.prototype.constructor('return 123');
        fn();
        """

        result = await validator.validate(code)
        assert not result.valid
        assert any("Function() constructor" in error for error in result.errors)

    @pytest.mark.asyncio
    async def test_validate_detects_webassembly(self, validator: CodeValidator) -> None:
        """Test validation detects WebAssembly usage."""
        code = """
        const bytes = new Uint8Array([0, 97, 115, 109]);
        WebAssembly.instantiate(bytes);
        """

        result = await validator.validate(code)
        assert not result.valid
        assert any("WebAssembly" in error for error in result.errors)

    @pytest.mark.asyncio
    async def test_validate_detects_workers(self, validator: CodeValidator) -> None:
        """Test validation detects Worker creation."""
        code = """
        const worker = new Worker('worker.js');
        """

        result = await validator.validate(code)
        assert not result.valid
        assert any("Workers" in error for error in result.errors)

    @pytest.mark.asyncio
    async def test_validate_detects_dynamic_import(self, validator: CodeValidator) -> None:
        """Test validation detects dynamic imports with variables."""
        code = """
        const moduleName = 'evil-module';
        const mod = await import(moduleName);
        """

        result = await validator.validate(code)
        assert not result.valid
        assert result.has_computed_imports
        assert any("Computed or dynamic imports" in error for error in result.errors)

    @pytest.mark.asyncio
    async def test_validate_allows_static_dynamic_import(self, validator: CodeValidator) -> None:
        """Test that static string dynamic imports are allowed."""
        code = """
        const mod = await import('@mcp-codegen/filesystem');
        """

        result = await validator.validate(code)
        assert result.valid
        assert result.has_dynamic_imports
        assert not result.has_computed_imports

    @pytest.mark.asyncio
    async def test_validate_no_imports_allowed(self) -> None:
        """Test validation with empty allowed imports list (all imports forbidden)."""
        validator = CodeValidator(allowed_imports=[])
        code = """
        console.log('hello');
        """

        result = await validator.validate(code)
        assert result.valid  # No imports = valid

    @pytest.mark.asyncio
    async def test_validate_all_imports_allowed(self) -> None:
        """Test validation with no restrictions."""
        validator = CodeValidator(allowed_imports=None)
        code = """
        import axios from 'axios';
        import fs from 'fs';
        """

        result = await validator.validate(code)
        # With no allowed_imports, all imports are allowed
        assert result.valid
