# 🧩 MCP Code Mode

<p align="center">
  <a href="https://discord.gg/tXjATaKgTV"><img alt="Join our Discord" src="https://img.shields.io/badge/Discord-Join%20us-5865F2?logo=discord&logoColor=white"></a>
  <img alt="Project Version" src="https://img.shields.io/pypi/v/mcp-code-mode?label=version&color=blue">
  <img alt="Python Version" src="https://img.shields.io/badge/python-3.12-blue?logo=python">
  <img src="https://img.shields.io/badge/License-Apache%202.0-blue" alt="License">

</p>

---

**Generate TypeScript code from any MCP server, with AST-Analysed Code Control**

<img width="869" height="480" alt="Screenshot 2025-12-19 at 19 42 48" src="https://github.com/user-attachments/assets/1e4c76c1-253c-4619-93ba-747508ac5c78" />


**Automatic MCP → static TypeScript code generation**: a Python library that connects to a Model Context Protocol (MCP) server, reads its tool schema at runtime, and generates a *static* TypeScript library (SDK) you can import with full types/autocomplete. This lets agents write normal TypeScript against tools instead of juggling ad-hoc JSON calls.

This repository also includes optional security primitives for “code mode” execution:

1. **MCP-to-TypeScript generator (USP):** Connect to an MCP server and generate a typed TS client on the fly.
2. **AST analysis (static safety layer):** Reject dynamic/obfuscated patterns before execution, enabling reliable reasoning about what code can do.
3. **Deno sandbox (isolation):** A straightforward Deno-permissions sandbox to reduce RCE risk and restrict network/file access.

## 📦 Installation

```bash
pip install mcp-code-mode
cd js && npm install
```

## 🚀 Usage: MCP → typed TypeScript client generation (the main USP)

To let an LLM (or any runtime) write code against MCP tools, it helps a lot to have a real TypeScript library instead of raw JSON tool calls. This repo includes `mcp-codegen`, a Python CLI that connects to an MCP server, introspects tools/resources/prompts, and generates a *static* TypeScript client library.

```bash
# Generates an npm package under ./generated/<server-name>
mcp-codegen --url http://localhost:3000/mcp/YOUR_API_KEY --output ./generated
```

<details>
<summary><strong>🧰 Optional: execute generated TypeScript in “code mode” (sandbox + AST gate)</strong></summary>

If you also want to *run* TypeScript produced by an agent, `mcp_code_mode.CodeExecutor` runs it in a Deno sandbox and can gate it with the AST analysis layer.

```python
import asyncio
from pathlib import Path

from mcp_code_mode import CodeExecutor


async def main() -> None:
    executor = CodeExecutor(
        mcp_libraries_path=Path("./generated"),  # where mcp-codegen wrote libraries
        allowed_imports=["@mcp-codegen/"],
        allowed_net_hosts=["localhost:3000"],
        validate_before_execution=True,  # enables AST analysis gate
    )

    ts = """
      import { createClient } from "@mcp-codegen/YOUR_SERVER_NAME";

      const client = createClient(); // default URL is embedded at generation time
      await client.initialize();

      // Call tools with full type safety + IDE autocomplete.
      // (Tool names depend on the server; see the generated library README.)
      // const result = await client.tools.<prefix>.<toolName>({ ... });

      await client.close();
    """

    result = await executor.execute(ts)
    print(result.output)


if __name__ == "__main__":
    asyncio.run(main())
```

</details>

## 💡 Motivation (expand for details)

At a high level: **sandboxing reduces RCE risk, but it doesn’t automatically stop prompt-injection-driven data exfiltration** in MCP “code mode”. The rest of this section explains the “lethal trifecta” framing and why AST analysis helps reduce false positives.

<details>
<summary><strong>⚠️ Why sandboxing isn’t enough (data exfiltration) + lethal trifecta + false positives</strong></summary>

MCP “code mode” still suffers from **prompt-injection-driven data exfiltration**, even when the code is sandboxed. A sandbox can prevent the script from *harming the host* (RCE, arbitrary network/file access), but it doesn’t automatically prevent the script from **reading sensitive tool outputs and funneling them into an exfiltration channel** (often via other allowed tool calls or outputs).

Our previous work with OpenEdison introduced a deterministic mitigation: the **lethal trifecta blocking algorithm** (details: `https://edisonwatch.substack.com/p/introducing-openedison`).

**Important:** the lethal trifecta blocking / taint-permission enforcement logic is **not implemented in this repository**. This repo focuses on the **MCP→TypeScript code generator** plus the **sandbox + AST analyzability gate** that make stronger data-flow enforcement *possible elsewhere*.

**Lethal trifecta, in 1–2 lines:** label tools/data sources and track (per agent session) when the model has ingested untrusted content; then **block tool-call plans that would combine untrusted influence + sensitive data access + an exfiltration path**, preventing deterministic “read secret → leak secret” flows.

#### 🎯 Why naïve lethal-trifecta blocking has high false positives

This repo adds an **AST-based static analysis layer that runs before execution**. It rejects code containing “funny business” or dynamic patterns (e.g., WebAssembly, prototype modification, or complex indirection) so the program remains statically analyzable.

If you “always block once untrusted content exists,” you end up with constant blocking and a poor security–UX tradeoff. Example: take the classic *calendar prompt injection* scenario, but suppose the agent only ever prints **event metadata** (time, who sent it) rather than event bodies/notes. In that case it’s far less likely for the LLM to get jailbroken, because what matters is **what actually enters the LLM context window**.

Naïve blocking treats *any* access to a potentially untrusted tool as contamination, which produces very high false positives and turns the algorithm into a sledgehammer rather than a scalpel.

#### 🔍 How AST analysis reduces false positives (“only contaminate what reaches the context window”)

That analyzability is useful on its own, but it’s also the key to reducing false positives in lethal-trifecta-style defenses: instead of registering everything as contaminated up-front, you can **only register contamination of untrusted content if it actually enters the LLM context window through code execution** (e.g., via `console.log`/return values that get fed back to the model). This can be made **granular down to specific tool attributes**, e.g. “event.title contaminated” while “event.start time safe,” depending on what the program actually surfaces to the model.

</details>

## 🛡️ The security model (expand for details)

In this repo, “secure code mode” is split into:

- **System integrity**: isolate execution (reduce RCE risk; restrict network/files/env).
- **Data flow**: reject dynamic/obfuscated code patterns up front so the program is statically analyzable.

<details>
<summary><strong>🔒 Security model details: Deno sandbox + AST analysis rules</strong></summary>

Securing Code Mode requires addressing two distinct vectors: **System Integrity** and **Data Flow**.

### 🧱 1) System integrity: Deno sandbox (RCE + network isolation)

We utilize Deno’s permission system to prevent executed code from harming the host machine.

- **Network**: restricted to allowlists (e.g., `localhost` only).
- **Filesystem**: scoped read-only access to specific library directories.
- **Environment**: no access to environment variables.

### 🌊 2) Data flow: AST analysis (reject dynamic “funny business”)

Sandboxing reduces RCE risk, but it doesn’t automatically prevent data exfiltration. To make data-flow controls viable (and reduce false positives), the executed TypeScript must be **statically analyzable**.

By parsing the AST (Abstract Syntax Tree) before execution, we enforce a “strict TypeScript” subset and reject patterns that introduce dynamic behavior, hidden dependencies, or hard-to-audit indirection.

#### 📊 High-level examples of allowed vs rejected patterns

| Category | Allowed (analyzable) | Rejected (dynamic/obfuscated) | Why it’s rejected |
| :--- | :--- | :--- | :--- |
| **Execution** | `const sum = x + y;` | `eval("x + y")` | String execution defeats static reasoning. |
| **Imports** | `import { x } from "./lib";` | `import(someVar)` | Dynamic imports hide dependency graph. |
| **Indirection** | `obj.key = value;` | `obj["k" + "ey"] = value;` | Computed access can trigger hidden getters/setters. |
| **Codegen** | normal functions | `new Function("...")` | Runtime compilation bypasses analysis. |
| **Reflection** | normal `new Foo()` | `Reflect.construct(...)` | Reflection hides call targets. |
| **Prototype / globals** | local pure code | `Object.prototype... = ...` | Prototype modification enables surprising flows. |
| **WASM** | N/A | `WebAssembly.*` | Adds opaque execution paths and payloads. |

</details>

<img width="685" height="685" alt="Screenshot 2025-12-19 at 18 56 09" src="https://github.com/user-attachments/assets/90158f80-13e0-4b3b-b8f7-9a48480fed6f" />

## 🤝 Commercial Integration & Advanced Security

<details>
<summary><strong>🏢 Commercial integration (Edison Watch)</strong></summary>

This repository contains the foundational execution and validation layers used in our commercial product, **Edison Watch**.

While this OSS library enforces *analyzability*, Edison Watch leverages that analyzability to enforce **granular data permissions** (the “Trifecta” family of defenses). That enforcement layer is **out of scope for this repo**.

- **Open source**: helps ensure code is safer to run (reduced RCE risk) and readable (no obfuscation / dynamic tricks).
- **Edison Watch**: enforces data permissions and tracks taint across the execution lifecycle.

*If there is sufficient community demand, we may explore open-sourcing the Taint Tracking/Trifecta logic in the future.*

</details>

## ✅ Requirements

  * Python 3.12+
  * Deno
  * Node.js (Required strictly for the AST parsing layer)

## 📄 License

Apache 2.0
