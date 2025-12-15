# MCP Code Mode

A lightweight, secure execution environment for Model Context Protocol (MCP) agents.

## Overview

Code Mode allows LLMs to solve problems by writing and executing TypeScript scripts rather than making individual, chatty tool calls. While efficient, this pattern introduces significant security risks: Remote Code Execution (RCE) and Data Exfiltration.

This repository provides the core primitives to run Code Mode securely:

1.  **Deno Sandbox:** Handles network and file isolation (stopping RCE).
2.  **AST Analysis:** Enforces static analyzability (preventing data leaks).
3.  **MCP Codegen:** Dynamically generates typed TypeScript clients from arbitrary MCP servers.

## Installation

```bash
pip install mcp-code-mode
cd js && npm install
```

## The Security Model

Securing Code Mode requires addressing two distinct vectors: **System Integrity** and **Data Flow**.

### 1\. System Integrity (The Deno Sandbox)

We utilize Deno's permission system to prevent the code from harming the host machine.

  * **Network:** Restricted to allowlists (e.g., `localhost` only).
  * **Filesystem:** Read-only access to specific library directories.
  * **Environment:** No access to environment variables.

### 2\. Data Flow (AST Analysis)

Sandboxing prevents the code from hacking the server, but it doesn't prevent the code from leaking user data. To safely integrate code execution with sensitive data, the code must be **statically analyzable**.

If code is dynamic (e.g., uses `eval` or dynamic imports), security systems cannot predict where data flows. By parsing the AST (Abstract Syntax Tree) before execution, we enforce a "Strict Typescript" subset that guarantees analyzability.

#### Allowed vs. Rejected Patterns

We reject patterns that obfuscate control flow or dependency trees.

| Category | Allowed (Analyzable) | Rejected (Dynamic/Obfuscated) | Reason |
| :--- | :--- | :--- | :--- |
| **Execution** | `const sum = x + y;` | `eval("x + y")` | `eval` bypasses static analysis. |
| **Imports** | `import { fs } from "node:fs";` | `const lib = "fs"; import(lib)` | Dynamic imports hide dependencies. |
| **Objects** | `obj.key = "value";` | `obj["k" + "ey"] = "value";` | Computed keys can trigger hidden getters. |
| **Functions** | `function foo() { ... }` | `new Function("return 1")` | Function constructors execute strings. |
| **Classes** | `class User { ... }` | `Reflect.construct(...)` | Reflective construction hides instantiation. |

## Usage

### Dynamic MCP Client Generation

To allow an LLM to write code against your MCP tools, it needs a valid TypeScript library. This package includes a generator that connects to an MCP server and produces a temporary, typed TypeScript client on the fly.

```python
from mcp_code_mode import CodeExecutor

# 1. Connects to MCP server
# 2. Generates TS definitions
# 3. Executes sandboxed code
executor = CodeExecutor(
    allowed_imports=["@modelcontextprotocol/"],
    allowed_net_hosts=["localhost:3000"],
    validate_before_execution=True, # Enables AST Analysis
)

# Example: LLM calculating sums using generated client
result = await executor.execute("""
    import { calculator } from "./generated-mcp-client";
    
    const data = [1, 2, 3, 4, 5];
    const sum = data.reduce((a, b) => a + b, 0);
    console.log('Sum:', sum);
""")
```

## Commercial Integration & Advanced Security

This repository contains the foundational execution and validation layers used in our commercial product, **Edison Watch**.

While this OSS library enforces *analyzability*, Edison Watch leverages that analyzability to enforce **granular data permissions** (the "Trifecta" algorithm).

  * **Open Source:** Ensures code is safe to run (No RCE) and readable (No Obfuscation).
  * **Edison Watch:** Ensures code only accesses data it is explicitly permitted to see, tracking data taint across the execution lifecycle.

*If there is sufficient community demand, we may explore open-sourcing the Taint Tracking/Trifecta logic in the future.*

## Requirements

  * Python 3.12+
  * Deno
  * Node.js (Required strictly for the AST parsing layer)

## License

Apache 2.0
