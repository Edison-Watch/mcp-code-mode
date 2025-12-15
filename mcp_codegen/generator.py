#!/usr/bin/env python3
"""
MCP Code Mode Generator

Generates TypeScript API wrappers for MCP servers by:
1. Connecting to MCP servers using fastmcp client
2. Introspecting available tools, resources, and prompts
3. Generating TypeScript code that wraps MCP calls in a familiar API

Inspired by: https://blog.cloudflare.com/code-mode/
"""

import argparse
import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastmcp import Client as FastMCPClient

log = logging.getLogger(__name__)


@dataclass
class ToolSpec:
    """Specification for an MCP tool."""

    name: str
    description: str
    input_schema: dict[str, Any] | None
    output_schema: dict[str, Any] | None


@dataclass
class ResourceSpec:
    """Specification for an MCP resource."""

    uri: str
    name: str
    description: str | None
    mime_type: str | None


@dataclass
class PromptSpec:
    """Specification for an MCP prompt."""

    name: str
    description: str | None
    arguments: list[dict[str, Any]] | None


@dataclass
class ServerSpec:
    """Complete specification for an MCP server."""

    name: str
    tools: list[ToolSpec]
    resources: list[ResourceSpec]
    prompts: list[PromptSpec]


def group_tools_by_server(tools: list[ToolSpec]) -> dict[str, list[ToolSpec]]:
    """Group tools by their server prefix (e.g., filesystem_, zapier_)."""
    servers: dict[str, list[ToolSpec]] = {}

    for tool in tools:
        # Extract server prefix from tool name
        if "_" in tool.name:
            prefix = tool.name.split("_", 1)[0]
            # Sanitize prefix - remove spaces, special chars
            prefix = prefix.replace(" ", "").replace("-", "").lower()
        else:
            prefix = "builtin"  # Tools without prefix go to builtin

        if prefix not in servers:
            servers[prefix] = []
        servers[prefix].append(tool)

    return servers


def sanitize_name(name: str) -> str:
    """Convert MCP names to valid TypeScript identifiers."""
    # Remove server prefix if present (e.g., "filesystem_read_file" -> "read_file")
    if "_" in name:
        parts = name.split("_", 1)
        if len(parts) == 2:
            name = parts[1]

    # Convert to camelCase
    parts = name.split("_")
    if not parts:
        return "unknown"

    # First part lowercase, rest capitalized
    result = parts[0].lower()
    for part in parts[1:]:
        if part:
            result += part.capitalize()

    # Ensure it's a valid JS identifier
    if result and result[0].isdigit():
        result = f"_{result}"

    return result or "unknown"


def json_schema_to_typescript_type(schema: dict[str, Any] | None, indent: int = 0) -> str:  # noqa: C901
    """Convert JSON Schema to TypeScript type definition.

    Handles nested objects, arrays, unions, enums, and preserves descriptions as JSDoc comments.
    """
    if not schema:
        return "any"

    schema_type = schema.get("type")
    indent_str = "  " * indent

    if schema_type == "object":
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))
        additional_properties = schema.get("additionalProperties")

        if not properties and additional_properties:
            # additionalProperties is specified, create an index signature
            if isinstance(additional_properties, dict):
                value_type = json_schema_to_typescript_type(additional_properties, indent)
                return f"Record<string, {value_type}>"
            if additional_properties is True:
                return "Record<string, any>"
            return "Record<string, never>"

        if not properties:
            return "Record<string, any>"

        lines = ["{"]
        for prop_name, prop_schema in properties.items():
            prop_type = json_schema_to_typescript_type(prop_schema, indent + 1)
            optional = "" if prop_name in required else "?"
            description = prop_schema.get("description")

            if description:
                # Escape special characters in JSDoc
                description = description.replace("*/", "*\\/")
                lines.append(f"{indent_str}  /** {description} */")
            lines.append(f"{indent_str}  {prop_name}{optional}: {prop_type};")

        # Handle additional properties if specified
        if additional_properties and properties:
            if isinstance(additional_properties, dict):
                value_type = json_schema_to_typescript_type(additional_properties, indent + 1)
                lines.append(f"{indent_str}  [key: string]: {value_type};")
            elif additional_properties is True:
                lines.append(f"{indent_str}  [key: string]: any;")

        lines.append(f"{indent_str}}}")
        return "\n".join(lines)

    if schema_type == "array":
        items = schema.get("items", {})
        item_type = json_schema_to_typescript_type(items, indent)
        # Use Array<T> for complex types, T[] for simple types
        if "\n" in item_type or item_type.startswith("{"):
            return f"Array<{item_type}>"
        return f"{item_type}[]"

    if schema_type == "string":
        enum = schema.get("enum")
        if enum:
            return " | ".join(f'"{val}"' for val in enum)
        # Could map formats to specific types (e.g., "date-time" -> Date)
        # but for now keep as string
        return "string"

    if schema_type == "number" or schema_type == "integer":
        return "number"

    if schema_type == "boolean":
        return "boolean"

    if schema_type == "null":
        return "null"

    if isinstance(schema_type, list):
        # Union type (e.g., ["string", "null"])
        types = [json_schema_to_typescript_type({"type": t}, indent) for t in schema_type]
        return " | ".join(types)

    # Handle oneOf, anyOf, allOf
    if "oneOf" in schema:
        types = [json_schema_to_typescript_type(s, indent) for s in schema["oneOf"]]
        return " | ".join(f"({t})" if " | " in t else t for t in types)

    if "anyOf" in schema:
        types = [json_schema_to_typescript_type(s, indent) for s in schema["anyOf"]]
        return " | ".join(f"({t})" if " | " in t else t for t in types)

    if "allOf" in schema:
        # For allOf, we'd need to merge the schemas, which is complex
        # For now, just intersect the types
        types = [json_schema_to_typescript_type(s, indent) for s in schema["allOf"]]
        return " & ".join(f"({t})" if " | " in t or " & " in t else t for t in types)

    # Handle const (single value)
    if "const" in schema:
        const_val = schema["const"]
        if isinstance(const_val, str):
            return f'"{const_val}"'
        return str(const_val)

    return "any"


def generate_package_json(server_name: str) -> str:
    """Generate package.json for the MCP wrapper library."""
    return json.dumps(
        {
            "name": f"@mcp-codegen/{server_name}",
            "version": "0.1.0",
            "description": f"TypeScript API wrapper for {server_name} MCP server",
            "type": "module",
            "main": "dist/index.js",
            "types": "dist/index.d.ts",
            "scripts": {
                "build": "tsc",
                "watch": "tsc --watch",
                "clean": "rm -rf dist",
            },
            "dependencies": {"@modelcontextprotocol/sdk": "^1.0.4"},
            "devDependencies": {"typescript": "^5.7.0", "@types/node": "^22.0.0"},
        },
        indent=2,
    )


def generate_tsconfig() -> str:
    """Generate tsconfig.json for the wrapper library."""
    return json.dumps(
        {
            "compilerOptions": {
                "target": "ES2022",
                "module": "ES2022",
                "moduleResolution": "bundler",
                "lib": ["ES2022"],
                "outDir": "./dist",
                "rootDir": "./src",
                "declaration": True,
                "declarationMap": True,
                "sourceMap": True,
                "strict": True,
                "esModuleInterop": True,
                "skipLibCheck": True,
                "forceConsistentCasingInFileNames": True,
            },
            "include": ["src/**/*"],
            "exclude": ["node_modules", "dist"],
        },
        indent=2,
    )


def generate_types_file(spec: ServerSpec) -> str:
    """Generate types.ts with TypeScript interfaces from schemas."""
    lines = [
        "/**",
        f" * TypeScript types for {spec.name} MCP server",
        " * Generated automatically - do not edit manually",
        " * ",
        f" * This file contains type definitions for {len(spec.tools)} tool(s)",
        " */",
        "",
    ]

    if not spec.tools:
        lines.append("// No tools available on this server")
        return "\n".join(lines)

    # Generate tool input/output types
    for tool in spec.tools:
        tool_name = sanitize_name(tool.name)
        camel_name = tool_name[0].upper() + tool_name[1:] if tool_name else "Unknown"

        # Add JSDoc comment block for the tool
        lines.append("/**")
        lines.append(f" * Types for tool: {tool.name}")
        if tool.description:
            lines.append(" * ")
            # Split description into lines
            desc_lines = tool.description.split("\n")
            for desc_line in desc_lines:
                lines.append(f" * {desc_line}")
        lines.append(" */")
        lines.append("")

        # Input type with better documentation
        lines.append("/**")
        lines.append(f" * Input parameters for {tool.name}")
        if tool.input_schema:
            schema_desc = tool.input_schema.get("description")
            if schema_desc:
                lines.append(f" * {schema_desc}")
        lines.append(" */")
        input_type = json_schema_to_typescript_type(tool.input_schema)
        lines.append(f"export type {camel_name}Input = {input_type};")
        lines.append("")

        # Output type with better documentation
        lines.append("/**")
        lines.append(f" * Output/result from {tool.name}")
        if tool.output_schema:
            schema_desc = tool.output_schema.get("description")
            if schema_desc:
                lines.append(f" * {schema_desc}")
        lines.append(" */")
        output_type = json_schema_to_typescript_type(tool.output_schema)
        lines.append(f"export type {camel_name}Output = {output_type};")
        lines.append("")

    return "\n".join(lines)


def generate_client_file() -> str:
    """Generate client.ts with MCP SDK client wrapper."""
    return """/**
 * Base MCP client wrapper using @modelcontextprotocol/sdk
 * Generated automatically - do not edit manually
 */

import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';

export interface MCPClientConfig {
  url: string;
  timeout?: number;
}

export interface MCPToolResult {
  content: Array<{
    type: string;
    text?: string;
    data?: any;
  }>;
  isError?: boolean;
}

/**
 * Error thrown when an MCP tool call fails
 */
export class MCPToolError extends Error {
  public readonly toolName: string;
  public readonly errorContent: string;

  constructor(toolName: string, errorContent: string) {
    super(`MCP tool '${toolName}' failed: ${errorContent}`);
    this.name = 'MCPToolError';
    this.toolName = toolName;
    this.errorContent = errorContent;
  }
}

export interface MCPResource {
  uri: string;
  name: string;
  description?: string;
  mimeType?: string;
}

/**
 * Wrapper around MCP SDK Client for easier usage
 */
export class MCPClient {
  private client: Client;
  private transport: StreamableHTTPClientTransport;
  private url: string;

  constructor(config: MCPClientConfig) {
    this.url = config.url;
    this.transport = new StreamableHTTPClientTransport(new URL(config.url));
    this.client = new Client({
      name: 'mcp-typescript-client',
      version: '1.0.0',
    }, {
      capabilities: {}
    });
  }

  /**
   * Initialize the MCP connection
   */
  async initialize(): Promise<void> {
    await this.client.connect(this.transport);
  }

  /**
   * Call an MCP tool
   * @throws {MCPToolError} When the tool returns an error
   */
  async callTool(name: string, args: any): Promise<MCPToolResult> {
    const result = await this.client.callTool({
      name,
      arguments: args,
    }) as MCPToolResult;

    // Check if the tool returned an error
    if (result.isError) {
      // Extract error message from content
      let errorMessage = 'Unknown error';
      if (result.content && result.content.length > 0) {
        const firstContent = result.content[0];
        if (firstContent.text) {
          errorMessage = firstContent.text;
        } else if (firstContent.data) {
          errorMessage = typeof firstContent.data === 'string'
            ? firstContent.data
            : JSON.stringify(firstContent.data);
        }
      }
      throw new MCPToolError(name, errorMessage);
    }

    return result;
  }

  /**
   * Read an MCP resource
   */
  async readResource(uri: string): Promise<MCPToolResult> {
    const result = await this.client.readResource({ uri });
    return result as any;
  }

  /**
   * List available resources
   */
  async listResources(): Promise<MCPResource[]> {
    const result = await this.client.listResources();
    return (result.resources || []) as MCPResource[];
  }

  /**
   * Close the MCP connection
   */
  async close(): Promise<void> {
    await this.client.close();
  }
}
"""


def generate_tools_file(spec: ServerSpec) -> str:  # noqa: C901
    """Generate main tools.ts that re-exports all server-specific tool directories."""
    # Group tools by server prefix
    servers = group_tools_by_server(spec.tools)

    lines = [
        "/**",
        f" * Tool wrappers for {spec.name} MCP server",
        " * Generated automatically - do not edit manually",
        " * ",
        f" * Re-exports tools from {len(servers)} server(s)",
        " */",
        "",
    ]

    # Import all server tool classes
    for server_prefix in sorted(servers.keys()):
        class_name = f"{server_prefix.capitalize()}Tools"
        lines.append(f"export {{ {class_name} }} from './tools/{server_prefix}/index.js';")

    lines.append("")
    lines.append("import type { MCPClient } from './client.js';")

    # Import all classes for the main Tools class
    for server_prefix in sorted(servers.keys()):
        class_name = f"{server_prefix.capitalize()}Tools"
        lines.append(f"import {{ {class_name} }} from './tools/{server_prefix}/index.js';")

    lines.extend(
        [
            "",
            "/**",
            f" * Main tools namespace for {spec.name} MCP server",
            f" * Organizes {len(spec.tools)} tool(s) across {len(servers)} server(s)",
            " */",
            "export class Tools {",
        ]
    )

    # Add a property for each server
    for server_prefix in sorted(servers.keys()):
        lines.append(f"  public {server_prefix}: {server_prefix.capitalize()}Tools;")

    lines.extend(
        [
            "",
            "  constructor(private client: MCPClient) {",
        ]
    )

    # Initialize each server's tools
    for server_prefix in sorted(servers.keys()):
        class_name = f"{server_prefix.capitalize()}Tools"
        lines.append(f"    this.{server_prefix} = new {class_name}(client);")

    lines.extend(
        [
            "  }",
            "}",
        ]
    )

    return "\n".join(lines)


def generate_server_readme(server_prefix: str, tools: list[ToolSpec]) -> str:
    """Generate README.md for a server directory documenting all its tools."""
    lines = [
        f"# {server_prefix.capitalize()} Tools",
        "",
        f"This directory contains **{len(tools)} tool(s)** for the `{server_prefix}` server.",
        "",
        "## Available Tools",
        "",
    ]

    for tool in sorted(tools, key=lambda t: t.name):
        tool_name = sanitize_name(tool.name)
        lines.append(f"### `{tool_name}` - {tool.name}")
        lines.append("")

        if tool.description:
            lines.append(tool.description)
            lines.append("")

        # Show input schema if available
        if tool.input_schema and tool.input_schema.get("properties"):
            lines.append("**Input Parameters:**")
            lines.append("")
            for prop_name, prop_schema in tool.input_schema.get("properties", {}).items():
                prop_type = prop_schema.get("type", "any")
                prop_desc = prop_schema.get("description", "")
                required = prop_name in tool.input_schema.get("required", [])
                req_marker = " *(required)*" if required else " *(optional)*"
                lines.append(f"- `{prop_name}` ({prop_type}){req_marker}: {prop_desc}")
            lines.append("")

        # Show output schema if available
        if tool.output_schema:
            lines.append("**Output:**")
            lines.append("")
            output_desc = tool.output_schema.get("description", "See type definition")
            lines.append(f"- {output_desc}")
            lines.append("")

        lines.append("**File:** `" + f"./{tool_name}.ts`")
        lines.append("")
        lines.append("---")
        lines.append("")

    lines.append("## Usage")
    lines.append("")
    lines.append("```typescript")
    lines.append(f"import {{ {server_prefix.capitalize()}Tools }} from './index.js';")
    lines.append("import { MCPClient } from '../../client.js';")
    lines.append("")
    lines.append("const client = new MCPClient({ url: 'http://localhost:3000/mcp/YOUR_KEY' });")
    lines.append("await client.initialize();")
    lines.append("")
    lines.append(f"const {server_prefix} = new {server_prefix.capitalize()}Tools(client);")

    if tools:
        example_tool = tools[0]
        example_name = sanitize_name(example_tool.name)
        lines.append(f"const result = await {server_prefix}.{example_name}({{ /* args */ }});")

    lines.append("```")
    lines.append("")
    lines.append("## Direct Imports")
    lines.append("")
    lines.append("You can also import individual tools for better tree-shaking:")
    lines.append("")
    lines.append("```typescript")
    if tools:
        for tool in tools[:3]:  # Show first 3 as examples
            tool_name = sanitize_name(tool.name)
            lines.append(f"import {{ {tool_name} }} from './{tool_name}.js';")
    lines.append("```")

    return "\n".join(lines)


def generate_single_tool_file(tool: ToolSpec) -> str:
    """Generate a file for a single tool."""
    tool_name = sanitize_name(tool.name)
    camel_name = tool_name[0].upper() + tool_name[1:] if tool_name else "Unknown"

    lines = [
        "/**",
        f" * Tool: {tool.name}",
        " * Generated automatically - do not edit manually",
        " */",
        "",
        "import type { MCPClient, MCPToolResult } from '../../client.js';",
        "import type {",
        f"  {camel_name}Input,",
        f"  {camel_name}Output,",
        "} from '../../types.js';",
        "",
    ]

    # Add JSDoc
    lines.append("/**")
    if tool.description:
        # Split long descriptions into multiple lines
        desc_lines = tool.description.split("\n")
        for desc_line in desc_lines:
            if len(desc_line) > 80:
                # Wrap long lines
                words = desc_line.split()
                current_line = " * "
                for word in words:
                    if len(current_line) + len(word) + 1 > 80:
                        lines.append(current_line)
                        current_line = " * " + word
                    else:
                        current_line += (" " if current_line != " * " else "") + word
                if current_line != " * ":
                    lines.append(current_line)
            else:
                lines.append(f" * {desc_line}")
    else:
        lines.append(f" * Tool: {tool.name}")

    lines.append(" *")
    lines.append(" * @param client - MCP client instance")
    lines.append(f" * @param args - Input parameters for {tool.name}")
    lines.append(f" * @returns Result from {tool.name}")
    lines.append(" */")

    # Generate the function
    lines.append(f"export async function {tool_name}(")
    lines.append("  client: MCPClient,")
    lines.append(f"  args: {camel_name}Input")
    lines.append(f"): Promise<{camel_name}Output> {{")
    lines.append("  try {")
    lines.append(f'    const result = await client.callTool("{tool.name}", args);')
    lines.append("    // Extract content from MCP result")
    lines.append("    if (result.content && result.content.length > 0) {")
    lines.append("      const firstContent = result.content[0];")
    lines.append("      if (firstContent.type === 'text' && firstContent.text) {")
    lines.append("        try {")
    lines.append("          return JSON.parse(firstContent.text);")
    lines.append("        } catch {")
    lines.append("          return firstContent.text as any;")
    lines.append("        }")
    lines.append("      }")
    lines.append("      return firstContent.data || firstContent;")
    lines.append("    }")
    lines.append("    return result as any;")
    lines.append("  } catch (error: any) {")
    lines.append("    // Re-throw with more context")
    lines.append("    const errorMessage = error?.message || error?.toString() || 'Unknown error';")
    lines.append("    const errorCode = error?.code || 'MCP_ERROR';")
    lines.append(
        f"    throw new Error(`MCP tool '{tool.name}' failed: ${{errorMessage}} (code: ${{errorCode}})`);"
    )
    lines.append("  }")
    lines.append("}")

    return "\n".join(lines)


def generate_server_index_file(server_prefix: str, tools: list[ToolSpec]) -> str:
    """Generate index.ts for a server that exports all its tools."""
    # Collect all type names for static imports
    type_names: list[str] = []
    for tool in tools:
        tool_name = sanitize_name(tool.name)
        camel_name = tool_name[0].upper() + tool_name[1:] if tool_name else "Unknown"
        type_names.append(f"{camel_name}Input")
        type_names.append(f"{camel_name}Output")

    lines = [
        "/**",
        f" * {server_prefix.capitalize()} tools index",
        " * Generated automatically - do not edit manually",
        f" * Exports {len(tools)} tool(s)",
        " */",
        "",
        "import type { MCPClient } from '../../client.js';",
        "import type {",
    ]

    # Add type imports (4 per line for readability)
    for i in range(0, len(type_names), 4):
        chunk = type_names[i : i + 4]
        lines.append(f"  {', '.join(chunk)},")
    lines.append("} from '../../types.js';")
    lines.append("")

    # Import all tool functions
    for tool in tools:
        tool_name = sanitize_name(tool.name)
        lines.append(f"import {{ {tool_name} }} from './{tool_name}.js';")
        lines.append(f"export {{ {tool_name} }} from './{tool_name}.js';")

    lines.append("")
    lines.append("/**")
    lines.append(f" * {server_prefix.capitalize()} tools class")
    lines.append(f" * Provides {len(tools)} tool(s)")
    lines.append(" */")
    lines.append(f"export class {server_prefix.capitalize()}Tools {{")
    lines.append("  constructor(private client: MCPClient) {}")
    lines.append("")

    # Generate wrapper methods with static types
    for tool in tools:
        tool_name = sanitize_name(tool.name)
        camel_name = tool_name[0].upper() + tool_name[1:] if tool_name else "Unknown"

        lines.append("  /**")
        if tool.description:
            lines.append(f"   * {tool.description[:80]}...")
        lines.append(f"   * @see {{{tool_name}}} for full documentation")
        lines.append("   */")
        lines.append(
            f"  async {tool_name}(args: {camel_name}Input): Promise<{camel_name}Output> {{"
        )
        lines.append(f"    return {tool_name}(this.client, args);")
        lines.append("  }")
        lines.append("")

    lines.append("}")

    return "\n".join(lines)


def generate_server_tools_file(server_prefix: str, tools: list[ToolSpec]) -> str:  # noqa: C901
    """Generate a tools file for a specific server prefix (e.g., filesystem, browser)."""
    lines = [
        "/**",
        f" * Tools for {server_prefix} server",
        " * Generated automatically - do not edit manually",
        " */",
        "",
        "import type { MCPClient, MCPToolResult } from '../client.js';",
    ]

    # Import types
    type_imports = []
    for tool in tools:
        tool_name = sanitize_name(tool.name)
        camel_name = tool_name[0].upper() + tool_name[1:] if tool_name else "Unknown"
        type_imports.append(f"  {camel_name}Input,")
        type_imports.append(f"  {camel_name}Output,")

    if type_imports:
        lines.append("import type {")
        lines.extend(type_imports)
        lines.append("} from '../types.js';")

    lines.append("")
    lines.append("/**")
    lines.append(f" * {server_prefix.capitalize()} tools")
    lines.append(f" * Provides {len(tools)} tool(s)")
    lines.append(" */")
    lines.append(f"export class {server_prefix.capitalize()}Tools {{")
    lines.append("  constructor(private client: MCPClient) {}")
    lines.append("")

    if not tools:
        lines.append(f"  // No {server_prefix} tools available")
        lines.append("}")
        return "\n".join(lines)

    # Generate method for each tool
    for tool in tools:
        tool_name = sanitize_name(tool.name)
        camel_name = tool_name[0].upper() + tool_name[1:] if tool_name else "Unknown"

        lines.append("  /**")
        if tool.description:
            # Split long descriptions into multiple lines
            desc_lines = tool.description.split("\n")
            for desc_line in desc_lines:
                if len(desc_line) > 80:
                    # Wrap long lines
                    words = desc_line.split()
                    current_line = "   * "
                    for word in words:
                        if len(current_line) + len(word) + 1 > 80:
                            lines.append(current_line)
                            current_line = "   * " + word
                        else:
                            current_line += (" " if current_line != "   * " else "") + word
                    if current_line != "   * ":
                        lines.append(current_line)
                else:
                    lines.append(f"   * {desc_line}")
        else:
            lines.append(f"   * Tool: {tool.name}")

        lines.append("   *")
        lines.append(f"   * @param args - Input parameters for {tool.name}")
        lines.append(f"   * @returns Result from {tool.name}")
        lines.append("   */")

        lines.append(
            f"  async {tool_name}(args: {camel_name}Input): Promise<{camel_name}Output> {{"
        )
        lines.append("    try {")
        lines.append(f'      const result = await this.client.callTool("{tool.name}", args);')
        lines.append("      // Extract content from MCP result")
        lines.append("      if (result.content && result.content.length > 0) {")
        lines.append("        const firstContent = result.content[0];")
        lines.append("        if (firstContent.type === 'text' && firstContent.text) {")
        lines.append("          try {")
        lines.append("            return JSON.parse(firstContent.text);")
        lines.append("          } catch {")
        lines.append("            return firstContent.text as any;")
        lines.append("          }")
        lines.append("        }")
        lines.append("        return firstContent.data || firstContent;")
        lines.append("      }")
        lines.append("      return result as any;")
        lines.append("    } catch (error: any) {")
        lines.append("      // Re-throw with more context")
        lines.append(
            "      const errorMessage = error?.message || error?.toString() || 'Unknown error';"
        )
        lines.append("      const errorCode = error?.code || 'MCP_ERROR';")
        lines.append(
            f"      throw new Error(`MCP tool '{tool.name}' failed: ${{errorMessage}} (code: ${{errorCode}})`);"
        )
        lines.append("    }")
        lines.append("  }")
        lines.append("")

    lines.append("}")

    return "\n".join(lines)


def generate_resources_file(spec: ServerSpec) -> str:
    """Generate resources.ts with resource access methods."""
    lines = [
        "/**",
        f" * Resource wrappers for {spec.name} MCP server",
        " * Generated automatically - do not edit manually",
        " * ",
        f" * This server provides {len(spec.resources)} resource(s)",
        " */",
        "",
        "import type { MCPClient, MCPToolResult, MCPResource } from './client.js';",
        "",
    ]

    # Add known resources as constants with documentation
    if spec.resources:
        lines.append("/**")
        lines.append(" * Known resources available on this server")
        lines.append(" */")
        lines.append("export const KNOWN_RESOURCES = {")
        for resource in spec.resources:
            safe_name = sanitize_name(resource.name or resource.uri.split("/")[-1])
            lines.append("  /**")
            if resource.description:
                lines.append(f"   * {resource.description}")
            if resource.mime_type:
                lines.append(f"   * MIME type: {resource.mime_type}")
            lines.append(f"   * URI: {resource.uri}")
            lines.append("   */")
            lines.append(f"  {safe_name.upper()}: '{resource.uri}',")
        lines.append("} as const;")
        lines.append("")

    lines.extend(
        [
            "/**",
            f" * Resources namespace for {spec.name} MCP server",
            " */",
            "export class Resources {",
            "  constructor(private client: MCPClient) {}",
            "",
            "  /**",
            "   * List all available resources from the server",
            "   * ",
            f"   * This server is known to provide {len(spec.resources)} resource(s):",
        ]
    )

    if spec.resources:
        for resource in spec.resources:
            desc = f" - {resource.name}" + (
                f": {resource.description}" if resource.description else ""
            )
            lines.append(f"   * {desc}")

    lines.extend(
        [
            "   */",
            "  async list(): Promise<MCPResource[]> {",
            "    return await this.client.listResources();",
            "  }",
            "",
            "  /**",
            "   * Read a specific resource by URI",
            "   * ",
            "   * @param uri - The URI of the resource to read",
            "   * @returns The resource content",
            "   */",
            "  async read(uri: string): Promise<MCPToolResult> {",
            "    return await this.client.readResource(uri);",
            "  }",
            "}",
        ]
    )

    return "\n".join(lines)


def generate_index_file(spec: ServerSpec, default_url: str | None = None) -> str:
    """Generate index.ts as the main entry point."""
    servers = group_tools_by_server(spec.tools)
    server_list = ", ".join(sorted(servers.keys()))

    # Create the createClient function with optional URL
    if default_url:
        create_client_func = f"""/**
 * Convenience function to create a client
 * Default URL is pre-configured: {default_url}
 */
export function createClient(url?: string, config?: Omit<MCPClientConfig, 'url'>): {spec.name.replace("-", "").replace("_", "").title()}Client {{
  const finalUrl = url || '{default_url}';
  return new {spec.name.replace("-", "").replace("_", "").title()}Client({{ url: finalUrl, ...config }});
}}"""
    else:
        create_client_func = f"""/**
 * Convenience function to create a client
 */
export function createClient(url: string, config?: Omit<MCPClientConfig, 'url'>): {spec.name.replace("-", "").replace("_", "").title()}Client {{
  return new {spec.name.replace("-", "").replace("_", "").title()}Client({{ url, ...config }});
}}"""

    return f"""/**
 * Main entry point for {spec.name} MCP server wrapper
 * Generated automatically - do not edit manually
 *
 * Tools are organized by server prefix: {server_list}
 */

import {{ MCPClient, type MCPClientConfig }} from './client.js';
import {{ Tools }} from './tools.js';
import {{ Resources }} from './resources.js';

export * from './types.js';
export {{ type MCPClientConfig, type MCPToolResult, type MCPResource, MCPToolError }} from './client.js';

// Re-export individual server tool classes for direct access
export * from './tools.js';

/**
 * Main client for {spec.name} MCP server
 *
 * Tools are organized by server:
{chr(10).join(f" * - tools.{prefix}: {len(tools)} tool(s)" for prefix, tools in sorted(servers.items()))}
 */
export class {spec.name.replace("-", "").replace("_", "").title()}Client {{
  private mcpClient: MCPClient;
  public tools: Tools;
  public resources: Resources;

  constructor(config: MCPClientConfig) {{
    this.mcpClient = new MCPClient(config);
    this.tools = new Tools(this.mcpClient);
    this.resources = new Resources(this.mcpClient);
  }}

  /**
   * Initialize the connection
   */
  async initialize(): Promise<void> {{
    await this.mcpClient.initialize();
  }}

  /**
   * Close the connection
   */
  async close(): Promise<void> {{
    await this.mcpClient.close();
  }}
}}

{create_client_func}
"""


def generate_readme(spec: ServerSpec) -> str:  # noqa: C901
    """Generate README.md for the generated library."""
    tools_section = ""
    if spec.tools:
        tools_section = "## Available Tools\n\n"
        for tool in spec.tools:
            tools_section += f"### `{tool.name}`\n\n"
            if tool.description:
                tools_section += f"{tool.description}\n\n"

            # Show input schema summary
            if tool.input_schema and tool.input_schema.get("properties"):
                tools_section += "**Parameters:**\n\n"
                for prop_name, prop_schema in tool.input_schema.get("properties", {}).items():
                    prop_type = prop_schema.get("type", "any")
                    prop_desc = prop_schema.get("description", "")
                    required = prop_name in tool.input_schema.get("required", [])
                    req_marker = " (required)" if required else " (optional)"
                    tools_section += f"- `{prop_name}` ({prop_type}){req_marker}: {prop_desc}\n"
                tools_section += "\n"

            tools_section += "---\n\n"
    else:
        tools_section = "## Available Tools\n\nNo tools available on this server.\n\n"

    resources_section = ""
    if spec.resources:
        resources_section = "## Available Resources\n\n"
        for resource in spec.resources:
            resources_section += f"### `{resource.name}`\n\n"
            resources_section += f"**URI:** `{resource.uri}`\n\n"
            if resource.description:
                resources_section += f"{resource.description}\n\n"
            if resource.mime_type:
                resources_section += f"**MIME Type:** `{resource.mime_type}`\n\n"
            resources_section += "---\n\n"
    else:
        resources_section = "## Available Resources\n\nNo resources available on this server.\n\n"

    prompts_section = ""
    if spec.prompts:
        prompts_section = "## Available Prompts\n\n"
        for prompt in spec.prompts:
            prompts_section += f"### `{prompt.name}`\n\n"
            if prompt.description:
                prompts_section += f"{prompt.description}\n\n"
            if prompt.arguments:
                prompts_section += "**Arguments:**\n\n"
                for arg in prompt.arguments:
                    arg_name = arg.get("name", "unknown")
                    arg_desc = arg.get("description", "")
                    arg_required = arg.get("required", False)
                    req_marker = " (required)" if arg_required else " (optional)"
                    prompts_section += f"- `{arg_name}`{req_marker}: {arg_desc}\n"
                prompts_section += "\n"
            prompts_section += "---\n\n"

    example_tool_call = ""
    if spec.tools:
        first_tool = spec.tools[0]
        tool_name = sanitize_name(first_tool.name)
        example_tool_call = f"""// Use tools
const result = await client.tools.{tool_name}({{
  // Add your parameters here based on {first_tool.name} input schema
}});
console.log(result);
"""

    return f"""# {spec.name} MCP Client

TypeScript API wrapper for the **{spec.name}** MCP server.

**This code is automatically generated. Do not edit manually.**

Generated from MCP server introspection with:
- **{len(spec.tools)}** tool(s)
- **{len(spec.resources)}** resource(s)
- **{len(spec.prompts)}** prompt(s)

## Installation

```bash
npm install
npm run build
```

## Quick Start

```typescript
import {{ createClient }} from './src/index.js';

// Create and initialize client
const client = createClient('http://localhost:3000/mcp/');
await client.initialize();

try {{
{example_tool_call}
  // Access resources
  const resources = await client.resources.list();
  console.log('Available resources:', resources);

  // Read a specific resource
  const content = await client.resources.read('resource://example');
  console.log(content);

}} finally {{
  // Always close when done
  await client.close();
}}
```

{tools_section}

{resources_section}

{prompts_section}

## Type Safety

This library provides full TypeScript type safety:
- Input parameters are validated at compile time
- Output types are inferred from the MCP schema
- IDE autocomplete works for all tools and resources

## Error Handling

```typescript
try {{
  const result = await client.tools.someTool({{...}});
}} catch (error) {{
  console.error('MCP call failed:', error.message);
}}
```

## Development

```bash
# Build the library
npm run build

# Watch mode for development
npm run watch

# Clean build artifacts
npm run clean
```
"""


async def introspect_server(url: str, headers: dict[str, str] | None = None) -> ServerSpec:  # noqa: C901
    """Connect to MCP server and introspect its capabilities.

    Args:
        url: MCP server URL
        headers: Optional HTTP headers for authentication (e.g., Authorization)
    """
    log.info(f"Connecting to MCP server at {url}...")

    # Create client with optional auth
    # FastMCPClient supports Bearer token auth via the auth parameter
    if headers and "Authorization" in headers:
        # Extract token from "Bearer TOKEN" format
        auth_header = headers["Authorization"]
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]  # Remove "Bearer " prefix
            log.debug("Using Bearer token authentication")
            # Create a simple auth object that FastMCP can use
            from httpx import Auth

            class BearerAuth(Auth):
                def __init__(self, token: str):
                    self.token = token

                def auth_flow(self, request):
                    request.headers["Authorization"] = f"Bearer {self.token}"
                    yield request

            client = FastMCPClient(url, auth=BearerAuth(token))
        else:
            log.warning("Authorization header present but not in 'Bearer TOKEN' format, ignoring")
            client = FastMCPClient(url)
    else:
        client = FastMCPClient(url)

    try:
        async with client:
            log.info("Connected successfully")

            # Extract server name from URL
            # Use a shorter name for the package/module, but keep full URL for default_url
            raw_server_name = url.rstrip("/").split("/")[-1]
            if not raw_server_name or raw_server_name == "mcp":
                raw_server_name = (
                    url.rstrip("/").split("/")[-2] if len(url.split("/")) > 2 else "mcp-server"
                )

            # Shorten the server name for package/module names
            # If it contains a long hex string (like edison_...), use just the prefix
            if "_" in raw_server_name:
                parts = raw_server_name.split("_", 1)
                server_name = parts[0] if len(parts[1]) > 20 else raw_server_name
            else:
                server_name = raw_server_name

            tools = []
            resources = []
            prompts = []

            # List all tools using MCP protocol
            log.info("Fetching tools from server...")
            try:
                tools_list = await client.list_tools()
                log.info(f"Found {len(tools_list)} tools")

                for tool in tools_list:
                    tool_name = tool.name if hasattr(tool, "name") else str(tool)
                    description = tool.description if hasattr(tool, "description") else ""

                    # Extract input schema
                    input_schema = None
                    if hasattr(tool, "inputSchema"):
                        input_schema = tool.inputSchema
                    elif hasattr(tool, "input_schema"):
                        input_schema = tool.input_schema
                    elif hasattr(tool, "parameters"):
                        input_schema = tool.parameters

                    # Try to get output schema if available
                    output_schema = None
                    if hasattr(tool, "outputSchema"):
                        output_schema = tool.outputSchema
                    elif hasattr(tool, "output_schema"):
                        output_schema = tool.output_schema

                    tools.append(
                        ToolSpec(
                            name=tool_name,
                            description=description or "",
                            input_schema=input_schema,
                            output_schema=output_schema,
                        )
                    )

            except Exception as e:
                log.warning(f"Could not list tools: {e}")

            # List all resources
            log.info("Fetching resources from server...")
            try:
                resources_list = await client.list_resources()
                log.info(f"Found {len(resources_list)} resources")

                for resource in resources_list:
                    uri = str(resource.uri) if hasattr(resource, "uri") else ""
                    name = str(resource.name) if hasattr(resource, "name") else uri
                    description = resource.description if hasattr(resource, "description") else None
                    mime_type = resource.mimeType if hasattr(resource, "mimeType") else None

                    resources.append(
                        ResourceSpec(
                            uri=uri,
                            name=name,
                            description=description,
                            mime_type=mime_type,
                        )
                    )

            except Exception as e:
                log.warning(f"Could not list resources: {e}")

            # List all prompts
            log.info("Fetching prompts from server...")
            try:
                prompts_list = await client.list_prompts()
                log.info(f"Found {len(prompts_list)} prompts")

                for prompt in prompts_list:
                    name = prompt.name if hasattr(prompt, "name") else ""
                    description = prompt.description if hasattr(prompt, "description") else None
                    # Convert arguments to dict format if needed
                    arguments_raw = prompt.arguments if hasattr(prompt, "arguments") else None
                    arguments: list[dict[str, Any]] | None = None
                    if arguments_raw:
                        try:
                            # Try to convert to list of dicts
                            arguments = [
                                {
                                    "name": str(getattr(arg, "name", "")),
                                    "description": str(getattr(arg, "description", "")),
                                    "required": bool(getattr(arg, "required", False)),
                                }
                                for arg in arguments_raw
                            ]
                        except (AttributeError, TypeError):
                            arguments = None

                    prompts.append(
                        PromptSpec(
                            name=name,
                            description=description,
                            arguments=arguments,
                        )
                    )

            except Exception as e:
                log.warning(f"Could not list prompts: {e}")

            log.info(
                f"Introspection complete: {len(tools)} tools, {len(resources)} resources, {len(prompts)} prompts"
            )

            return ServerSpec(
                name=server_name,
                tools=tools,
                resources=resources,
                prompts=prompts,
            )

    except Exception as e:
        log.error(f"Failed to introspect server: {e}")
        raise


def generate_library(spec: ServerSpec, output_dir: Path, default_url: str | None = None) -> None:
    """Generate complete TypeScript library for an MCP server."""
    server_dir = output_dir / spec.name
    src_dir = server_dir / "src"
    tools_dir = src_dir / "tools"

    log.info(f"Generating library for {spec.name} in {server_dir}...")

    # Create directory structure
    tools_dir.mkdir(parents=True, exist_ok=True)

    # Generate all files
    (server_dir / "package.json").write_text(generate_package_json(spec.name))
    (server_dir / "tsconfig.json").write_text(generate_tsconfig())
    (server_dir / "README.md").write_text(generate_readme(spec))

    (src_dir / "types.ts").write_text(generate_types_file(spec))
    (src_dir / "client.ts").write_text(generate_client_file())
    (src_dir / "resources.ts").write_text(generate_resources_file(spec))
    (src_dir / "index.ts").write_text(generate_index_file(spec, default_url))

    # Generate main tools.ts that re-exports server-specific directories
    (src_dir / "tools.ts").write_text(generate_tools_file(spec))

    # Generate separate directories and files for each server
    servers = group_tools_by_server(spec.tools)
    for server_prefix, tools in servers.items():
        server_tools_dir = tools_dir / server_prefix
        server_tools_dir.mkdir(parents=True, exist_ok=True)

        # Generate README.md for this server
        readme_content = generate_server_readme(server_prefix, tools)
        (server_tools_dir / "README.md").write_text(readme_content)

        # Generate index.ts for this server
        index_content = generate_server_index_file(server_prefix, tools)
        (server_tools_dir / "index.ts").write_text(index_content)

        # Generate individual file for each tool
        for tool in tools:
            tool_name = sanitize_name(tool.name)
            tool_file_content = generate_single_tool_file(tool)
            (server_tools_dir / f"{tool_name}.ts").write_text(tool_file_content)

        log.debug(f"Generated {server_prefix}/ with README and {len(tools)} tool files")

    log.info(f"Generated library for {spec.name}")


async def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Generate TypeScript API wrappers for MCP servers")
    parser.add_argument(
        "--url",
        required=True,
        help="MCP server URL",
    )
    parser.add_argument(
        "--output",
        default="generated",
        help="Output directory for generated libraries (default: generated)",
    )
    parser.add_argument(
        "--auth",
        help="Authorization header value (e.g., 'Bearer TOKEN')",
    )

    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Prepare headers if auth provided
    headers = None
    if args.auth:
        headers = {"Authorization": args.auth}

    try:
        # Introspect the server
        spec = await introspect_server(args.url, headers=headers)

        # Generate the library
        generate_library(spec, output_dir)

        log.info("Code generation complete!")
        log.info(f"Output: {output_dir / spec.name}")
        log.info("\nNext steps:")
        log.info(f"  cd {output_dir / spec.name}")
        log.info("  npm install")
        log.info("  npm run build")

    except Exception as e:
        log.error(f"Code generation failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())

