"""
Tests for CodeExecutor.

Tests the Deno sandbox execution of TypeScript code.
"""

import shutil
from pathlib import Path

import pytest

from mcp_code_mode import CodeExecutor


@pytest.fixture
def temp_libraries_path(tmp_path: Path) -> Path:
    """Create a temporary libraries directory."""
    libraries_path = tmp_path / "libraries"
    libraries_path.mkdir()
    return libraries_path


@pytest.fixture
def executor(temp_libraries_path: Path) -> CodeExecutor:
    """Create a code executor instance."""
    return CodeExecutor(
        mcp_libraries_path=temp_libraries_path,
        allowed_imports=["@mcp-codegen/", "@modelcontextprotocol/"],
        timeout_seconds=5,
        validate_before_execution=True,
    )


# Check if Deno is installed
DENO_AVAILABLE = shutil.which("deno") is not None


class TestCodeExecutor:
    """Tests for CodeExecutor."""

    @pytest.mark.asyncio
    @pytest.mark.skipif(not DENO_AVAILABLE, reason="Deno not installed")
    async def test_execute_simple_code(self, executor: CodeExecutor) -> None:
        """Test execution of simple TypeScript code."""
        code = """
        const x = 42;
        console.log('Hello from code mode!');
        console.log('Result:', x);
        """

        result = await executor.execute(code)
        assert result.success
        assert result.exit_code == 0
        assert "Hello from code mode!" in result.output
        assert "Result:" in result.output
        assert "42" in result.output

    @pytest.mark.asyncio
    @pytest.mark.skipif(not DENO_AVAILABLE, reason="Deno not installed")
    async def test_execute_with_timeout(self, executor: CodeExecutor) -> None:
        """Test that execution times out for infinite loops."""
        code = """
        while (true) {
            // Infinite loop
        }
        """

        # Use a short timeout for testing
        executor.timeout_seconds = 2
        result = await executor.execute(code)

        assert not result.success
        assert "timed out" in result.error.lower() if result.error else False

    @pytest.mark.asyncio
    async def test_execute_with_validation_failure(self, executor: CodeExecutor) -> None:
        """Test that validation failures prevent execution."""
        code = """
        import axios from 'axios';  // Forbidden import
        await axios.get('https://evil.com');
        """

        result = await executor.execute(code)
        assert not result.success
        assert result.validation is not None
        assert not result.validation.valid
        assert "Validation failed" in result.error if result.error else False

    @pytest.mark.asyncio
    @pytest.mark.skipif(not DENO_AVAILABLE, reason="Deno not installed")
    async def test_execute_with_runtime_error(self, executor: CodeExecutor) -> None:
        """Test execution captures runtime errors."""
        code = """
        const obj: any = null;
        console.log(obj.property);  // Runtime error: cannot read property of null
        """

        result = await executor.execute(code)
        # Deno will catch this and return non-zero exit code
        assert not result.success

    @pytest.mark.asyncio
    @pytest.mark.skipif(not DENO_AVAILABLE, reason="Deno not installed")
    async def test_execute_typescript_features(self, executor: CodeExecutor) -> None:
        """Test execution of TypeScript-specific features."""
        code = """
        interface Result {
            status: string;
            value: number;
        }

        function calculate(a: number, b: number): Result {
            return {
                status: 'ok',
                value: a + b
            };
        }

        const result = calculate(10, 32);
        console.log(JSON.stringify(result));
        """

        result = await executor.execute(code)
        assert result.success
        assert '"status":"ok"' in result.output
        assert '"value":42' in result.output

    @pytest.mark.asyncio
    @pytest.mark.skipif(not DENO_AVAILABLE, reason="Deno not installed")
    async def test_execute_async_code(self, executor: CodeExecutor) -> None:
        """Test execution of async/await code."""
        code = """
        async function delay(ms: number): Promise<string> {
            return new Promise(resolve => {
                setTimeout(() => resolve('done'), ms);
            });
        }

        const result = await delay(100);
        console.log('Async result:', result);
        """

        result = await executor.execute(code)
        assert result.success
        assert "Async result: done" in result.output

    @pytest.mark.asyncio
    @pytest.mark.skipif(not DENO_AVAILABLE, reason="Deno not installed")
    async def test_execute_without_validation(self, temp_libraries_path: Path) -> None:
        """Test execution with validation disabled."""
        executor = CodeExecutor(
            mcp_libraries_path=temp_libraries_path,
            allowed_imports=["@mcp-codegen/"],
            timeout_seconds=5,
            validate_before_execution=False,  # Disable validation
        )

        code = """
        console.log('No validation');
        """

        result = await executor.execute(code)
        assert result.success
        assert result.validation is None  # No validation was performed

    @pytest.mark.asyncio
    async def test_execute_eval_blocked(self, executor: CodeExecutor) -> None:
        """Test that eval() is blocked by validation."""
        code = """
        eval("console.log('hacked')");
        """

        result = await executor.execute(code)
        assert not result.success
        assert result.validation is not None
        assert not result.validation.valid
        assert any("eval()" in error for error in result.validation.errors)


class TestCodeExecutorIntegration:
    """Integration tests for code execution."""

    @pytest.mark.asyncio
    @pytest.mark.skipif(not DENO_AVAILABLE, reason="Deno not installed")
    async def test_end_to_end_execution(self, executor: CodeExecutor) -> None:
        """End-to-end test of code execution."""
        code = """
        // Test complex TypeScript features
        interface Result {
            status: string;
            value: number;
        }

        function calculate(a: number, b: number): Result {
            return {
                status: 'ok',
                value: a + b
            };
        }

        const result = calculate(10, 32);
        console.log(JSON.stringify(result));
        """

        result = await executor.execute(code)
        assert result.success
        assert '"status":"ok"' in result.output
        assert '"value":42' in result.output

    @pytest.mark.asyncio
    @pytest.mark.skipif(not DENO_AVAILABLE, reason="Deno not installed")
    async def test_data_processing(self, executor: CodeExecutor) -> None:
        """Test data processing in the sandbox."""
        code = """
        // Process some data
        const data = [
            { name: 'Alice', score: 85 },
            { name: 'Bob', score: 92 },
            { name: 'Charlie', score: 78 },
        ];

        const average = data.reduce((sum, item) => sum + item.score, 0) / data.length;
        const highest = data.reduce((max, item) => item.score > max.score ? item : max);

        console.log('Average score:', average.toFixed(2));
        console.log('Highest scorer:', highest.name);
        """

        result = await executor.execute(code)
        assert result.success
        assert "Average score: 85.00" in result.output
        assert "Highest scorer: Bob" in result.output
