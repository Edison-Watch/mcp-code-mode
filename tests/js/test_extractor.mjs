#!/usr/bin/env node
/**
 * Test the AST-based import extractor
 */

import { extractImports } from '../../js/extract_imports.mjs';

// Test cases
const testCases = [
  {
    name: 'Simple static import',
    code: `import { createClient } from '@mcp-codegen/filesystem';`,
    expected: { safe: true, count: 1 }
  },
  {
    name: 'Dynamic import with string literal',
    code: `const mod = await import('@mcp-codegen/filesystem');`,
    expected: { safe: true, count: 1, dynamic: true }
  },
  {
    name: '🚨 Dynamic import with variable (ATTACK)',
    code: `
      const module = 'axios';
      const mod = await import(module);
    `,
    expected: { safe: false, computed: true }
  },
  {
    name: '🚨 Dynamic import with template literal (ATTACK)',
    code: `const mod = await import(\`axi\${'os'}\`);`,
    expected: { safe: false, computed: true }
  },
  {
    name: '🚨 Obfuscated static import (ATTACK)',
    code: `import/*comment*/{default as axios}/**/from/**/'axios';`,
    expected: { safe: true, count: 1 } // AST handles this!
  },
  {
    name: '🚨 require() with variable (ATTACK)',
    code: `
      const lib = 'axios';
      const mod = require(lib);
    `,
    expected: { safe: false, computed: true, require: true }
  },
  {
    name: '🚨 String.fromCharCode obfuscation (ATTACK)',
    code: `
      const lib = String.fromCharCode(97,120,105,111,115); // 'axios'
      await import(lib);
    `,
    expected: { safe: false, computed: true }
  },
  {
    name: 'Multiple imports',
    code: `
      import { x } from '@mcp-codegen/filesystem';
      import { y } from '@mcp-codegen/github';
      const z = await import('@mcp-codegen/sqlite');
    `,
    expected: { safe: true, count: 3 }
  },
  {
    name: '🚨 eval() detection',
    code: `
      const code = "console.log('hacked')";
      eval(code);
    `,
    expected: { safe: false, hasEval: true }
  },
  {
    name: '🚨 Function constructor detection',
    code: `
      const fn = new Function('return 123');
      fn();
    `,
    expected: { safe: false, hasFunctionConstructor: true }
  },
  {
    name: '🚨 WebAssembly detection',
    code: `
      const bytes = new Uint8Array([0, 97, 115, 109]);
      WebAssembly.instantiate(bytes);
    `,
    expected: { safe: false, hasWebAssembly: true }
  },
  {
    name: '🚨 Worker detection',
    code: `
      const worker = new Worker('worker.js');
    `,
    expected: { safe: false, hasWorkers: true }
  }
];

console.log('🧪 Testing AST-based import extraction\n');
console.log('=' .repeat(60));

let passed = 0;
let failed = 0;

for (const test of testCases) {
  console.log(`\n📝 Test: ${test.name}`);
  console.log('Code:', test.code.trim().substring(0, 60) + '...');
  
  try {
    const result = extractImports(test.code, 'test.ts');
    
    console.log(`\n📊 Results:`);
    console.log(`   Imports found: ${result.imports.length}`);
    console.log(`   Dynamic imports: ${result.hasDynamicImports}`);
    console.log(`   Computed imports: ${result.hasComputedImports}`);
    console.log(`   require() calls: ${result.hasRequire}`);
    
    if (result.imports.length > 0) {
      console.log('\n   Import details:');
      result.imports.forEach(imp => {
        const safetyIcon = imp.safe ? '✅' : '🚨';
        console.log(`   ${safetyIcon} Line ${imp.line}: ${imp.type} import of "${imp.module}"`);
        if (imp.has_eval) console.log('      🚨 eval() detected');
        if (imp.has_function_constructor) console.log('      🚨 Function constructor detected');
        if (imp.has_web_assembly) console.log('      🚨 WebAssembly detected');
        if (imp.has_workers) console.log('      🚨 Worker detected');
      });
    }
    
    // Validate expectations
    const allSafe = result.imports.every(imp => imp.safe);
    
    let testPassed = true;
    if (test.expected.safe !== undefined && allSafe !== test.expected.safe) {
      testPassed = false;
    }
    if (test.expected.count !== undefined && result.imports.length !== test.expected.count) {
      testPassed = false;
    }
    if (test.expected.computed !== undefined && result.hasComputedImports !== test.expected.computed) {
      testPassed = false;
    }
    if (test.expected.dynamic !== undefined && result.hasDynamicImports !== test.expected.dynamic) {
      testPassed = false;
    }
    if (test.expected.require !== undefined && result.hasRequire !== test.expected.require) {
      testPassed = false;
    }
    if (test.expected.hasEval !== undefined) {
      const hasEval = result.imports.some(imp => imp.has_eval);
      if (hasEval !== test.expected.hasEval) testPassed = false;
    }
    if (test.expected.hasFunctionConstructor !== undefined) {
      const has = result.imports.some(imp => imp.has_function_constructor);
      if (has !== test.expected.hasFunctionConstructor) testPassed = false;
    }
    if (test.expected.hasWebAssembly !== undefined) {
      const has = result.imports.some(imp => imp.has_web_assembly);
      if (has !== test.expected.hasWebAssembly) testPassed = false;
    }
    if (test.expected.hasWorkers !== undefined) {
      const has = result.imports.some(imp => imp.has_workers);
      if (has !== test.expected.hasWorkers) testPassed = false;
    }
    
    if (testPassed) {
      console.log('\n✅ PASS');
      passed++;
    } else {
      console.log('\n❌ FAIL - Did not match expectations');
      failed++;
    }
    
  } catch (error) {
    console.log(`\n❌ ERROR: ${error.message}`);
    failed++;
  }
  
  console.log('─'.repeat(60));
}

console.log(`\n${'='.repeat(60)}`);
console.log(`\n📊 Summary: ${passed} passed, ${failed} failed`);

if (failed === 0) {
  console.log('\n🎉 All tests passed! AST analysis is working correctly.');
  process.exit(0);
} else {
  console.log('\n⚠️  Some tests failed. Please review the output above.');
  process.exit(1);
}

