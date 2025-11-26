# MCP Code Mode

> Secure TypeScript code execution sandbox for MCP (Model Context Protocol)

Execute TypeScript code in a secure Deno sandbox instead of making individual MCP tool calls. Inspired by [Cloudflare's Code Mode](https://blog.cloudflare.com/code-mode/).

## Why Code Mode?

When LLMs interact with tools, they typically make one call at a time:

```
LLM → list_directory → Result
LLM → read_file_1 → Result
LLM → read_file_2 → Result
... (repeat for each file)
LLM → Response to user
```

This is slow and expensive. **Code Mode** allows LLMs to write TypeScript code that chains operations:

```typescript
const files = await client.tools.filesystem.listDirectory({ path: '/tmp' });
for (const file of files) {
    const content = await client.tools.filesystem.readFile({ path: file.path });
    console.log(`${file.name}: ${content.length} bytes`);
}
```

**Result**: One tool call instead of N+1, with all processing in the sandbox.

## Features

- **Secure Deno Sandbox**: No network access (except via MCP), no file system writes
- **AST-Based Validation**: Blocks dangerous patterns before execution
- **TypeScript Support**: Native TypeScript with full type checking
- **Configurable Permissions**: Control allowed imports and network hosts
- **Timeout Protection**: Kill long-running code automatically
- **FastMCP Integration**: Ready-to-use MCP server

## Requirements

- **Python 3.12+**
- **Deno** - For sandboxed execution ([install](https://deno.land/))
- **Node.js** - For AST validation ([install](https://nodejs.org/))

```bash
# Install Deno
curl -fsSL https://deno.land/install.sh | sh

# Verify
deno --version
node --version
```

## Installation

```bash
# Clone the repository
git clone https://github.com/edison-watch/mcp-code-mode.git
cd mcp-code-mode

# Install Python dependencies
pip install -e .

# Install JavaScript dependencies (for AST validation)
cd js && npm install && cd ..
```

Or with uv:

```bash
uv pip install -e .
cd js && npm install
```

## Quick Start

### As a Library

```python
import asyncio
from mcp_code_mode import CodeExecutor, CodeValidator

async def main():
    # Validate code before execution
    validator = CodeValidator(allowed_imports=["@mcp-codegen/"])
    result = await validator.validate("""
        import { createClient } from '@mcp-codegen/filesystem';
        console.log('Hello!');
    """)
    print(f"Valid: {result.valid}")

    # Execute code in sandbox
    executor = CodeExecutor(
        allowed_imports=["@mcp-codegen/"],
        timeout_seconds=30,
    )
    result = await executor.execute("""
        const data = [1, 2, 3, 4, 5];
        const sum = data.reduce((a, b) => a + b, 0);
        console.log('Sum:', sum);
    """)
    print(f"Output: {result.output}")

asyncio.run(main())
```

### As an MCP Server

```bash
# Run the server
python server.py
```

The server exposes two tools:

- `code_mode` - Execute TypeScript code in the sandbox
- `validate_code` - Validate code without execution

### With MCP Client Libraries

If you have generated MCP client libraries, you can use them in your code:

```python
from pathlib import Path
from mcp_code_mode import CodeExecutor

executor = CodeExecutor(
    mcp_libraries_path=Path("path/to/generated/libraries"),
    allowed_imports=["@mcp-codegen/"],
    timeout_seconds=30,
)

code = """
import { createClient } from '@mcp-codegen/filesystem';

const client = createClient('http://localhost:3000/mcp/YOUR_KEY');
await client.initialize();

const files = await client.tools.filesystem.listDirectory({ path: '/tmp' });
console.log('Found', files.length, 'files');

await client.close();
"""

result = await executor.execute(code)
```

## Security

MCP Code Mode implements defense-in-depth security:

### Layer 1: AST Validation (Pre-execution)

Uses TypeScript compiler API to detect dangerous patterns:

| Pattern | Blocked |
|---------|---------|
| `eval()` | ✅ Direct and indirect (`globalThis.eval`) |
| `new Function()` | ✅ Including `Function.prototype.constructor` |
| `WebAssembly.*` | ✅ `instantiate`, `compile`, etc. |
| `new Worker()` | ✅ Workers and SharedWorkers |
| Dynamic imports | ✅ `import(variable)`, template literals |
| `require()` | ✅ CommonJS require |
| Prototype pollution | ✅ `__proto__` access |
| Constructor chains | ✅ `constructor.constructor` |

### Layer 2: Import Validation

Only allowed import prefixes are permitted:

```python
validator = CodeValidator(allowed_imports=["@mcp-codegen/", "@modelcontextprotocol/"])
```

### Layer 3: Deno Permissions (Runtime)

Deno provides additional sandboxing:

- ❌ No network access (except specified hosts)
- ❌ No file system writes
- ❌ No environment variable access
- ✅ Read access only to MCP library directory

### Layer 4: Process Isolation

- Runs in subprocess
- Killed on timeout
- Cannot affect parent process

**Security Model**: If AST analysis fails, we **fail closed** (reject the code).

## API Reference

### CodeValidator

```python
from mcp_code_mode import CodeValidator

validator = CodeValidator(
    allowed_imports=["@mcp-codegen/"],  # Allowed import prefixes
    extractor_script_path=None,          # Custom path to extract_imports.mjs
)

result = await validator.validate(code)
# result.valid: bool
# result.errors: list[str]
# result.warnings: list[str]
# result.imports: list[str]
# result.has_dynamic_imports: bool
# result.has_computed_imports: bool
```

### CodeExecutor

```python
from mcp_code_mode import CodeExecutor

executor = CodeExecutor(
    mcp_libraries_path=None,              # Path to generated MCP libraries
    allowed_imports=["@mcp-codegen/"],    # Allowed import prefixes
    timeout_seconds=30,                    # Maximum execution time
    validate_before_execution=True,        # Run validation first
    allowed_net_hosts=["localhost:3000"], # Allowed network hosts
)

result = await executor.execute(code)
# result.success: bool
# result.output: str
# result.error: str | None
# result.exit_code: int
# result.validation: ValidationResult | None
```

## Examples

### Simple Computation

```typescript
const data = [1, 2, 3, 4, 5];
const sum = data.reduce((a, b) => a + b, 0);
const avg = sum / data.length;
console.log(`Sum: ${sum}, Average: ${avg}`);
```

### Data Processing

```typescript
interface User {
    name: string;
    age: number;
}

const users: User[] = [
    { name: 'Alice', age: 30 },
    { name: 'Bob', age: 25 },
    { name: 'Charlie', age: 35 },
];

const adults = users.filter(u => u.age >= 30);
console.log('Adults:', JSON.stringify(adults));
```

### Async Operations

```typescript
async function fetchAndProcess() {
    // Simulated async operation
    const data = await Promise.resolve([1, 2, 3]);
    return data.map(x => x * 2);
}

const result = await fetchAndProcess();
console.log('Result:', result);
```

## Testing

```bash
# Run all tests
make test

# Python tests only
make test-py

# JavaScript tests only
make test-js

# Run linter
make lint
```

## Development

```bash
# Install dev dependencies
make install-dev
make install-js

# Run CI checks
make ci
```

## License

Apache 2.0 - See [LICENSE](LICENSE) for details.

## Related Projects

- [Edison Watch](https://edison.watch) - MCP security and monitoring
- [FastMCP](https://github.com/jlowin/fastmcp) - Fast MCP server framework
- [Deno](https://deno.land) - Secure JavaScript/TypeScript runtime

---

Built with ❤️ for efficient and secure AI agent operations

