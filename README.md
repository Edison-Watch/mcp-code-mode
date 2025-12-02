# MCP Code Mode

A secure TypeScript execution sandbox for MCP (Model Context Protocol).

## Overview

MCP Code Mode enables LLMs to execute TypeScript code in a sandboxed environment rather than making individual tool calls. This improves efficiency for multi-step operations.

## Quick Start

### As a Library

```python
from mcp_code_mode import CodeExecutor

executor = CodeExecutor(
    allowed_imports=["@modelcontextprotocol/"],
    allowed_net_hosts=["localhost:3000", "api.example.com:443"],
    timeout_seconds=30,
    validate_before_execution=True,
)

result = await executor.execute("""
    const data = [1, 2, 3, 4, 5];
    const sum = data.reduce((a, b) => a + b, 0);
    console.log('Sum:', sum);
""")
```

### As an MCP Server

```bash
python server.py
```

Exposes two tools:

- `code_mode` - Execute TypeScript in sandbox
- `validate_code` - Validate code without execution

## Requirements

- Python 3.12+
- Deno (<https://deno.land/>)
- Node.js (for AST analysis)

## Installation

```bash
pip install -e .
cd js && npm install
```

## Security Architecture

The sandbox uses two layers of defense:

### Layer 1: Deno Process Sandbox

Code executes in a separate Deno process with restricted permissions:

- Network access limited to `allowed_net_hosts` only
- No file system write access
- No environment variable access
- Read access restricted to specified library directories
- Memory and timeout limits enforced
- Process killed on timeout

### Layer 2: Static AST Analysis (Optional)

Before execution, all code is parsed using the TypeScript compiler API. The AST is analyzed to:

- Reject imports not in `allowed_imports`
- Reject patterns that prevent further static analysis (dynamic code)
- Reject patterns that could allow sandbox escape via runtime tricks

This layer is **enabled by default** but can be disabled via `validate_before_execution=False`.

If AST analysis fails for any reason, execution is rejected (fail-closed).

The blocked patterns are documented below.

## Layer 2: Blocked Patterns

The following patterns are rejected because they defeat static analysis or could allow dynamic code execution.

### Dynamic Code Execution

```typescript
eval("code")
```

```typescript
new Function("return 1")
```

```typescript
globalThis.eval("code")
```

```typescript
Function.prototype.constructor("return 1")
```

### Dynamic Imports

```typescript
const mod = "fs";
import(mod)
```

```typescript
import(`./modules/${name}`)
```

```typescript
require(variable)
```

### Prototype Manipulation

```typescript
obj.__proto__.polluted = true
```

```typescript
({}).__proto__.constructor.constructor("code")()
```

### Global Object Access

```typescript
globalThis["ev" + "al"]("code")
```

```typescript
window[dynamicKey]
```

### Reflective Construction

```typescript
Reflect.construct(Function, ["return 1"])
```

### Workers and WebAssembly

```typescript
new Worker("worker.js")
```

```typescript
WebAssembly.instantiate(bytes)
```

### String-Based Timeouts

```typescript
setTimeout("alert(1)", 100)
```

## Configuration

### CodeExecutor

```python
from mcp_code_mode import CodeExecutor

executor = CodeExecutor(
    mcp_libraries_path=None,            # Path to MCP client libraries
    allowed_imports=None,               # Import prefixes to permit (None = all)
    allowed_net_hosts=None,             # Network hosts to permit (None = ["localhost:3000"])
    timeout_seconds=30,                 # Max execution time (capped at 90s)
    validate_before_execution=True,     # Run AST analysis first
)
```

### allowed_imports

Controls which ES module imports are permitted. Imports not matching any prefix are rejected.

```python
# Only allow MCP SDK
allowed_imports=["@modelcontextprotocol/"]

# Allow specific scopes
allowed_imports=["@modelcontextprotocol/", "@myorg/"]

# Allow all imports (not recommended)
allowed_imports=None
```

### allowed_net_hosts

Controls which hosts the Deno sandbox can connect to. Format: `host:port`.

```python
# Only localhost
allowed_net_hosts=["localhost:3000"]

# Multiple hosts
allowed_net_hosts=["localhost:3000", "api.example.com:443"]
```

## License

Apache 2.0
