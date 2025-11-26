#!/usr/bin/env node
/**
 * TypeScript AST Import Extractor
 * 
 * Uses the TypeScript compiler API to extract ALL import statements.
 * 
 * SECURITY MODEL:
 * - We ONLY analyze imports here
 * - Everything else (eval, WebAssembly, etc.) is blocked by Deno sandbox
 * - This avoids "security through enumeration" anti-pattern
 */

import * as ts from 'typescript';
import * as fs from 'fs';

/**
 * @typedef {Object} ImportInfo
 * @property {string} module - The module being imported
 * @property {'static'|'dynamic'|'require'} type - Type of import
 * @property {number} line - Line number in source
 * @property {boolean} safe - false if computed/dynamic
 * @property {boolean} has_eval - Has eval() call
 * @property {boolean} has_function_constructor - Has Function() constructor
 * @property {boolean} has_web_assembly - Has WebAssembly usage
 * @property {boolean} has_workers - Has Worker creation
 * @property {boolean} has_string_timeout - Has setTimeout/setInterval with string
 * @property {boolean} has_proto_access - Has __proto__ access
 * @property {boolean} has_global_access - Has dynamic global access
 * @property {boolean} has_reflect - Has Reflect.construct
 * @property {boolean} has_constructor_chain - Has constructor chain access
 * @property {boolean} has_process_exit - Has process.exit
 * @property {boolean} has_deno_exit - Has Deno.exit
 */

/**
 * @typedef {Object} AnalysisResult
 * @property {ImportInfo[]} imports - List of imports found
 * @property {boolean} hasDynamicImports - Has dynamic imports
 * @property {boolean} hasComputedImports - Has computed imports
 * @property {boolean} hasRequire - Has require() calls
 */

/**
 * Extract all imports from TypeScript/JavaScript code using AST.
 * 
 * SECURITY: We ONLY extract imports. Deno sandbox handles all other security.
 * 
 * @param {string} sourceCode - Code to analyze
 * @param {string} fileName - Filename for source mapping
 * @returns {AnalysisResult}
 */
function extractImports(sourceCode, fileName = 'code.ts') {
  // Parse code into AST
  const sourceFile = ts.createSourceFile(
    fileName,
    sourceCode,
    ts.ScriptTarget.Latest,
    true, // setParentNodes
    ts.ScriptKind.TS
  );

  const result = {
    imports: [],
    hasDynamicImports: false,
    hasComputedImports: false,
    hasRequire: false,
  };

  // Track dangerous patterns detected during AST traversal
  const dangerousPatterns = {
    has_eval: false,
    has_function_constructor: false,
    has_web_assembly: false,
    has_workers: false,
    has_string_timeout: false,
    has_proto_access: false,
    has_global_access: false,
    has_reflect: false,
    has_constructor_chain: false,
    has_process_exit: false,
    has_deno_exit: false,
  };

  /**
   * Recursively visit all AST nodes.
   * We ONLY extract imports - nothing else.
   * @param {ts.Node} node
   */
  function visit(node) {
    // 1. Static imports: import { x } from 'module'
    if (ts.isImportDeclaration(node)) {
      const moduleSpecifier = node.moduleSpecifier;
      
      if (ts.isStringLiteral(moduleSpecifier)) {
        // Safe static import with string literal
        const line = sourceFile.getLineAndCharacterOfPosition(node.getStart()).line + 1;
        result.imports.push({
          module: moduleSpecifier.text,
          type: 'static',
          line,
          safe: true,
          has_eval: false,
          has_function_constructor: false,
          has_web_assembly: false,
          has_workers: false,
          has_string_timeout: false,
          has_proto_access: false,
          has_global_access: false,
          has_reflect: false,
          has_constructor_chain: false,
          has_process_exit: false,
          has_deno_exit: false,
        });
      } else {
        // Computed import (BLOCKED - security risk)
        result.hasComputedImports = true;
        const line = sourceFile.getLineAndCharacterOfPosition(node.getStart()).line + 1;
        result.imports.push({
          module: '<computed>',
          type: 'static',
          line,
          safe: false,
          has_eval: false,
          has_function_constructor: false,
          has_web_assembly: false,
          has_workers: false,
          has_string_timeout: false,
          has_proto_access: false,
          has_global_access: false,
          has_reflect: false,
          has_constructor_chain: false,
          has_process_exit: false,
          has_deno_exit: false,
        });
      }
    }

    // 2. Dynamic imports: import('module')
    if (ts.isCallExpression(node)) {
      if (node.expression.kind === ts.SyntaxKind.ImportKeyword) {
        result.hasDynamicImports = true;
        const line = sourceFile.getLineAndCharacterOfPosition(node.getStart()).line + 1;

        // Check if it's a simple string literal
        if (node.arguments.length > 0) {
          const arg = node.arguments[0];
          if (ts.isStringLiteral(arg)) {
            // Safe: import('module') with string literal
            result.imports.push({
              module: arg.text,
              type: 'dynamic',
              line,
              safe: true,
              has_eval: false,
              has_function_constructor: false,
              has_web_assembly: false,
              has_workers: false,
              has_string_timeout: false,
              has_proto_access: false,
              has_global_access: false,
              has_reflect: false,
              has_constructor_chain: false,
              has_process_exit: false,
              has_deno_exit: false,
            });
          } else {
            // BLOCKED: import(variable) or import(`template`)
            result.hasComputedImports = true;
            result.imports.push({
              module: '<computed-dynamic>',
              type: 'dynamic',
              line,
              safe: false,
              has_eval: false,
              has_function_constructor: false,
              has_web_assembly: false,
              has_workers: false,
              has_string_timeout: false,
              has_proto_access: false,
              has_global_access: false,
              has_reflect: false,
              has_constructor_chain: false,
              has_process_exit: false,
              has_deno_exit: false,
            });
          }
        }
      }

      // 3. require() calls (banned - use import instead)
      if (ts.isIdentifier(node.expression) && node.expression.text === 'require') {
        result.hasRequire = true;
        const line = sourceFile.getLineAndCharacterOfPosition(node.getStart()).line + 1;

        if (node.arguments.length > 0 && ts.isStringLiteral(node.arguments[0])) {
          result.imports.push({
            module: node.arguments[0].text,
            type: 'require',
            line,
            safe: true,
            has_eval: false,
            has_function_constructor: false,
            has_web_assembly: false,
            has_workers: false,
            has_string_timeout: false,
            has_proto_access: false,
            has_global_access: false,
            has_reflect: false,
            has_constructor_chain: false,
            has_process_exit: false,
            has_deno_exit: false,
          });
        } else {
          // BLOCKED: require(variable)
          result.hasComputedImports = true;
          result.imports.push({
            module: '<computed-require>',
            type: 'require',
            line,
            safe: false,
            has_eval: false,
            has_function_constructor: false,
            has_web_assembly: false,
            has_workers: false,
            has_string_timeout: false,
            has_proto_access: false,
            has_global_access: false,
            has_reflect: false,
            has_constructor_chain: false,
            has_process_exit: false,
            has_deno_exit: false,
          });
        }
      }

      // Detect dangerous patterns in call expressions
      if (ts.isIdentifier(node.expression)) {
        const funcName = node.expression.text;
        const line = sourceFile.getLineAndCharacterOfPosition(node.getStart()).line + 1;

        if (funcName === 'eval') {
          dangerousPatterns.has_eval = true;
          result.imports.push({
            module: '<eval>',
            type: 'static',
            line,
            safe: false,
            has_eval: true,
            has_function_constructor: false,
            has_web_assembly: false,
            has_workers: false,
            has_string_timeout: false,
            has_proto_access: false,
            has_global_access: false,
            has_reflect: false,
            has_constructor_chain: false,
            has_process_exit: false,
            has_deno_exit: false,
          });
        } else if (funcName === 'setTimeout' || funcName === 'setInterval') {
          // Check if first argument is a string (dangerous)
          if (node.arguments.length > 0 && ts.isStringLiteral(node.arguments[0])) {
            dangerousPatterns.has_string_timeout = true;
            result.imports.push({
              module: `<${funcName}-string>`,
              type: 'static',
              line,
              safe: false,
              has_eval: false,
              has_function_constructor: false,
              has_web_assembly: false,
              has_workers: false,
              has_string_timeout: true,
              has_proto_access: false,
              has_global_access: false,
              has_reflect: false,
              has_constructor_chain: false,
              has_process_exit: false,
              has_deno_exit: false,
            });
          }
        }
      }
    }

    // Detect aliasing of dangerous identifiers: eval, Function, console
    // This catches: const e = eval, const c = console, const log = console.log, etc.
    if (ts.isVariableDeclaration(node) && node.initializer) {
      const line = sourceFile.getLineAndCharacterOfPosition(node.getStart()).line + 1;
      
      // Direct identifier aliasing (e.g., const e = eval, const c = console)
      if (ts.isIdentifier(node.initializer)) {
        const initName = node.initializer.text;
        
        if (initName === 'console') {
          result.imports.push({
            module: '<console-alias>',
            type: 'static',
            line,
            safe: false,
            has_eval: false,
            has_function_constructor: false,
            has_web_assembly: false,
            has_workers: false,
            has_string_timeout: false,
            has_proto_access: false,
            has_global_access: false,
            has_reflect: false,
            has_constructor_chain: false,
            has_process_exit: false,
            has_deno_exit: false,
          });
        }
      }
      
      // Property access aliasing (e.g., const log = console.log)
      if (ts.isPropertyAccessExpression(node.initializer)) {
        const objText = ts.isIdentifier(node.initializer.expression) 
          ? node.initializer.expression.text 
          : '';
        const propName = node.initializer.name?.text;
        
        if (objText === 'console' && (propName === 'log' || propName === 'warn' || propName === 'error' || propName === 'info' || propName === 'debug')) {
          result.imports.push({
            module: `<console.${propName}-alias>`,
            type: 'static',
            line,
            safe: false,
            has_eval: false,
            has_function_constructor: false,
            has_web_assembly: false,
            has_workers: false,
            has_string_timeout: false,
            has_proto_access: false,
            has_global_access: false,
            has_reflect: false,
            has_constructor_chain: false,
            has_process_exit: false,
            has_deno_exit: false,
          });
        }
      }
      
      // Destructuring console (e.g., const { log } = console, const { log: l } = console)
      if (ts.isObjectBindingPattern(node.name) && ts.isIdentifier(node.initializer) && node.initializer.text === 'console') {
        const consoleMethods = ['log', 'warn', 'error', 'info', 'debug', 'trace', 'dir'];
        for (const element of node.name.elements) {
          if (ts.isBindingElement(element)) {
            // Get the property name being destructured
            const propName = element.propertyName 
              ? (ts.isIdentifier(element.propertyName) ? element.propertyName.text : null)
              : (ts.isIdentifier(element.name) ? element.name.text : null);
            
            if (propName && consoleMethods.includes(propName)) {
              result.imports.push({
                module: `<console.${propName}-destructure>`,
                type: 'static',
                line,
                safe: false,
                has_eval: false,
                has_function_constructor: false,
                has_web_assembly: false,
                has_workers: false,
                has_string_timeout: false,
                has_proto_access: false,
                has_global_access: false,
                has_reflect: false,
                has_constructor_chain: false,
                has_process_exit: false,
                has_deno_exit: false,
              });
            }
          }
        }
      }
    }

    // Detect aliasing of eval or Function (e.g., const e = eval; const F = Function)
    // This catches: const e = eval, let f = Function, var x = eval, etc.
    if (ts.isVariableDeclaration(node) && node.initializer && ts.isIdentifier(node.initializer)) {
      const initName = node.initializer.text;
      const line = sourceFile.getLineAndCharacterOfPosition(node.getStart()).line + 1;
      
      if (initName === 'eval') {
        dangerousPatterns.has_eval = true;
        result.imports.push({
          module: '<eval-alias>',
          type: 'static',
          line,
          safe: false,
          has_eval: true,
          has_function_constructor: false,
          has_web_assembly: false,
          has_workers: false,
          has_string_timeout: false,
          has_proto_access: false,
          has_global_access: false,
          has_reflect: false,
          has_constructor_chain: false,
          has_process_exit: false,
          has_deno_exit: false,
        });
      } else if (initName === 'Function') {
        dangerousPatterns.has_function_constructor = true;
        result.imports.push({
          module: '<Function-alias>',
          type: 'static',
          line,
          safe: false,
          has_eval: false,
          has_function_constructor: true,
          has_web_assembly: false,
          has_workers: false,
          has_string_timeout: false,
          has_proto_access: false,
          has_global_access: false,
          has_reflect: false,
          has_constructor_chain: false,
          has_process_exit: false,
          has_deno_exit: false,
        });
      }
    }

    // Detect assignment expressions aliasing eval or Function (e.g., x = eval)
    if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.EqualsToken) {
      if (ts.isIdentifier(node.right)) {
        const rightName = node.right.text;
        const line = sourceFile.getLineAndCharacterOfPosition(node.getStart()).line + 1;
        
        if (rightName === 'eval') {
          dangerousPatterns.has_eval = true;
          result.imports.push({
            module: '<eval-reassign>',
            type: 'static',
            line,
            safe: false,
            has_eval: true,
            has_function_constructor: false,
            has_web_assembly: false,
            has_workers: false,
            has_string_timeout: false,
            has_proto_access: false,
            has_global_access: false,
            has_reflect: false,
            has_constructor_chain: false,
            has_process_exit: false,
            has_deno_exit: false,
          });
        } else if (rightName === 'Function') {
          dangerousPatterns.has_function_constructor = true;
          result.imports.push({
            module: '<Function-reassign>',
            type: 'static',
            line,
            safe: false,
            has_eval: false,
            has_function_constructor: true,
            has_web_assembly: false,
            has_workers: false,
            has_string_timeout: false,
            has_proto_access: false,
            has_global_access: false,
            has_reflect: false,
            has_constructor_chain: false,
            has_process_exit: false,
            has_deno_exit: false,
          });
        }
      }
    }

    // Detect console.log being passed as a callback argument
    // e.g., [data].map(console.log), arr.forEach(console.log)
    if (ts.isCallExpression(node)) {
      for (const arg of node.arguments) {
        if (ts.isPropertyAccessExpression(arg)) {
          const objText = ts.isIdentifier(arg.expression) ? arg.expression.text : '';
          const propName = arg.name?.text;
          if (objText === 'console' && (propName === 'log' || propName === 'warn' || propName === 'error' || propName === 'info' || propName === 'debug')) {
            const line = sourceFile.getLineAndCharacterOfPosition(node.getStart()).line + 1;
            result.imports.push({
              module: `<console.${propName}-as-callback>`,
              type: 'static',
              line,
              safe: false,
              has_eval: false,
              has_function_constructor: false,
              has_web_assembly: false,
              has_workers: false,
              has_string_timeout: false,
              has_proto_access: false,
              has_global_access: false,
              has_reflect: false,
              has_constructor_chain: false,
              has_process_exit: false,
              has_deno_exit: false,
            });
          }
        }
      }
    }

    // Detect console.log.call/apply/bind patterns
    // e.g., console.log.call(console, data), console.log.apply(console, [data]), console.log.bind(console)
    if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression)) {
      const methodName = node.expression.name?.text;
      if (methodName === 'call' || methodName === 'apply' || methodName === 'bind') {
        // Check if it's console.log.call/apply/bind
        if (ts.isPropertyAccessExpression(node.expression.expression)) {
          const innerProp = node.expression.expression.name?.text;
          if (ts.isIdentifier(node.expression.expression.expression)) {
            const obj = node.expression.expression.expression.text;
            if (obj === 'console' && (innerProp === 'log' || innerProp === 'warn' || innerProp === 'error' || innerProp === 'info' || innerProp === 'debug')) {
              const line = sourceFile.getLineAndCharacterOfPosition(node.getStart()).line + 1;
              result.imports.push({
                module: `<console.${innerProp}.${methodName}>`,
                type: 'static',
                line,
                safe: false,
                has_eval: false,
                has_function_constructor: false,
                has_web_assembly: false,
                has_workers: false,
                has_string_timeout: false,
                has_proto_access: false,
                has_global_access: false,
                has_reflect: false,
                has_constructor_chain: false,
                has_process_exit: false,
                has_deno_exit: false,
              });
            }
          }
        }
      }
    }

    // Check for property access expressions in call expressions (WebAssembly, Reflect, process.exit, Deno.exit, eval, etc.)
    if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression)) {
        const propName = node.expression.name?.text;
        let objText = '';
        try {
          if (ts.isIdentifier(node.expression.expression)) {
            objText = node.expression.expression.text;
          } else {
            objText = sourceFile.getText(node.expression.expression);
          }
        } catch (e) {
          // If we can't get the text, skip this check
          objText = '';
        }
        const line = sourceFile.getLineAndCharacterOfPosition(node.getStart()).line + 1;

        if (objText === 'WebAssembly' && (propName === 'instantiate' || propName === 'compile')) {
          dangerousPatterns.has_web_assembly = true;
          result.imports.push({
            module: `<WebAssembly.${propName}>`,
            type: 'static',
            line,
            safe: false,
            has_eval: false,
            has_function_constructor: false,
            has_web_assembly: true,
            has_workers: false,
            has_string_timeout: false,
            has_proto_access: false,
            has_global_access: false,
            has_reflect: false,
            has_constructor_chain: false,
            has_process_exit: false,
            has_deno_exit: false,
          });
        } else if (objText === 'Reflect' && propName === 'construct') {
          dangerousPatterns.has_reflect = true;
          result.imports.push({
            module: '<Reflect.construct>',
            type: 'static',
            line,
            safe: false,
            has_eval: false,
            has_function_constructor: false,
            has_web_assembly: false,
            has_workers: false,
            has_string_timeout: false,
            has_proto_access: false,
            has_global_access: false,
            has_reflect: true,
            has_constructor_chain: false,
            has_process_exit: false,
            has_deno_exit: false,
          });
        } else if (objText === 'process' && propName === 'exit') {
          dangerousPatterns.has_process_exit = true;
          result.imports.push({
            module: '<process.exit>',
            type: 'static',
            line,
            safe: false,
            has_eval: false,
            has_function_constructor: false,
            has_web_assembly: false,
            has_workers: false,
            has_string_timeout: false,
            has_proto_access: false,
            has_global_access: false,
            has_reflect: false,
            has_constructor_chain: false,
            has_process_exit: true,
            has_deno_exit: false,
          });
        } else if (objText === 'Deno' && propName === 'exit') {
          dangerousPatterns.has_deno_exit = true;
          result.imports.push({
            module: '<Deno.exit>',
            type: 'static',
            line,
            safe: false,
            has_eval: false,
            has_function_constructor: false,
            has_web_assembly: false,
            has_workers: false,
            has_string_timeout: false,
            has_proto_access: false,
            has_global_access: false,
            has_reflect: false,
            has_constructor_chain: false,
            has_process_exit: false,
            has_deno_exit: true,
          });
        } else if ((objText === 'globalThis' || objText === 'window' || objText === 'self') && propName === 'eval') {
          // Indirect eval access: globalThis.eval, window.eval, self.eval
          dangerousPatterns.has_eval = true;
          result.imports.push({
            module: `<${objText}.eval>`,
            type: 'static',
            line,
            safe: false,
            has_eval: true,
            has_function_constructor: false,
            has_web_assembly: false,
            has_workers: false,
            has_string_timeout: false,
            has_proto_access: false,
            has_global_access: false,
            has_reflect: false,
            has_constructor_chain: false,
            has_process_exit: false,
            has_deno_exit: false,
          });
        }
    }

    // Detect Function() constructor (direct and indirect via prototype)
    if (ts.isNewExpression(node)) {
      if (ts.isIdentifier(node.expression) && node.expression.text === 'Function') {
        dangerousPatterns.has_function_constructor = true;
        const line = sourceFile.getLineAndCharacterOfPosition(node.getStart()).line + 1;
        result.imports.push({
          module: '<Function-constructor>',
          type: 'static',
          line,
          safe: false,
          has_eval: false,
          has_function_constructor: true,
          has_web_assembly: false,
          has_workers: false,
          has_string_timeout: false,
          has_proto_access: false,
          has_global_access: false,
          has_reflect: false,
          has_constructor_chain: false,
          has_process_exit: false,
          has_deno_exit: false,
        });
      } else if (ts.isPropertyAccessExpression(node.expression)) {
        // Check for Function.prototype.constructor
        const propName = node.expression.name?.text;
        let objText = '';
        try {
          if (ts.isPropertyAccessExpression(node.expression.expression)) {
            const innerProp = node.expression.expression.name?.text;
            if (ts.isIdentifier(node.expression.expression.expression)) {
              const outerObj = node.expression.expression.expression.text;
              if (outerObj === 'Function' && innerProp === 'prototype' && propName === 'constructor') {
                dangerousPatterns.has_function_constructor = true;
                const line = sourceFile.getLineAndCharacterOfPosition(node.getStart()).line + 1;
                result.imports.push({
                  module: '<Function.prototype.constructor>',
                  type: 'static',
                  line,
                  safe: false,
                  has_eval: false,
                  has_function_constructor: true,
                  has_web_assembly: false,
                  has_workers: false,
                  has_string_timeout: false,
                  has_proto_access: false,
                  has_global_access: false,
                  has_reflect: false,
                  has_constructor_chain: false,
                  has_process_exit: false,
                  has_deno_exit: false,
                });
              }
            }
          }
        } catch (e) {
          // Skip if we can't parse
        }
      } else if (ts.isIdentifier(node.expression) && (node.expression.text === 'Worker' || node.expression.text === 'SharedWorker')) {
        dangerousPatterns.has_workers = true;
        const line = sourceFile.getLineAndCharacterOfPosition(node.getStart()).line + 1;
        result.imports.push({
          module: `<${node.expression.text}>`,
          type: 'static',
          line,
          safe: false,
          has_eval: false,
          has_function_constructor: false,
          has_web_assembly: false,
          has_workers: true,
          has_string_timeout: false,
          has_proto_access: false,
          has_global_access: false,
          has_reflect: false,
          has_constructor_chain: false,
          has_process_exit: false,
          has_deno_exit: false,
        });
      }
    }

    // Detect __proto__ access
    if (ts.isPropertyAccessExpression(node)) {
      const propName = node.name?.text;
      if (propName === '__proto__') {
        dangerousPatterns.has_proto_access = true;
        const line = sourceFile.getLineAndCharacterOfPosition(node.getStart()).line + 1;
        result.imports.push({
          module: '<__proto__>',
          type: 'static',
          line,
          safe: false,
          has_eval: false,
          has_function_constructor: false,
          has_web_assembly: false,
          has_workers: false,
          has_string_timeout: false,
          has_proto_access: true,
          has_global_access: false,
          has_reflect: false,
          has_constructor_chain: false,
          has_process_exit: false,
          has_deno_exit: false,
        });
      } else if (propName === 'constructor' && ts.isPropertyAccessExpression(node.expression)) {
        // Check for constructor.constructor pattern
        if (node.expression.name?.text === 'constructor') {
          dangerousPatterns.has_constructor_chain = true;
          const line = sourceFile.getLineAndCharacterOfPosition(node.getStart()).line + 1;
          result.imports.push({
            module: '<constructor-chain>',
            type: 'static',
            line,
            safe: false,
            has_eval: false,
            has_function_constructor: false,
            has_web_assembly: false,
            has_workers: false,
            has_string_timeout: false,
            has_proto_access: false,
            has_global_access: false,
            has_reflect: false,
            has_constructor_chain: true,
            has_process_exit: false,
            has_deno_exit: false,
          });
        }
      }
    }

    // Detect dynamic global access (globalThis[x], window[x], self[x])
    if (ts.isElementAccessExpression(node)) {
      const exprText = node.expression.getText(sourceFile);
      if (exprText === 'globalThis' || exprText === 'window' || exprText === 'self') {
        dangerousPatterns.has_global_access = true;
        const line = sourceFile.getLineAndCharacterOfPosition(node.getStart()).line + 1;
        result.imports.push({
          module: `<${exprText}-dynamic>`,
          type: 'static',
          line,
          safe: false,
          has_eval: false,
          has_function_constructor: false,
          has_web_assembly: false,
          has_workers: false,
          has_string_timeout: false,
          has_proto_access: false,
          has_global_access: true,
          has_reflect: false,
          has_constructor_chain: false,
          has_process_exit: false,
          has_deno_exit: false,
        });
      }
    }

    // Recurse into child nodes
    ts.forEachChild(node, visit);
  }

  // Start the traversal
  visit(sourceFile);

  return result;
}

/**
 * Main CLI function
 */
function main() {
  const args = process.argv.slice(2);
  
  if (args.length === 0) {
    console.error('Usage: extract_imports.mjs <file.ts>');
    process.exit(1);
  }

  const filePath = args[0];
  
  if (!fs.existsSync(filePath)) {
    console.error(`Error: File not found: ${filePath}`);
    process.exit(1);
  }

  const sourceCode = fs.readFileSync(filePath, 'utf-8');
  const result = extractImports(sourceCode, filePath);

  // Output as JSON for Python to parse
  console.log(JSON.stringify(result, null, 2));
}

// Run if called directly (check if this file is the main module)
if (import.meta.url.endsWith(process.argv[1]?.replace(/\\/g, '/') || '')) {
  main();
}

export { extractImports };
