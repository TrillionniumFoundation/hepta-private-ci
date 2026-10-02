// Packaging glue for the pinned Makepad compiler's schema, not application UI.
// The caller authenticates the compiler/source revision. This is not a sandbox
// for arbitrary JavaScript supplied by an unrelated WASM producer.
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFile, readdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { Worker, isMainThread, parentPort, workerData } from 'node:worker_threads';

const BRIDGE_PATH = 'makepad_wasm_bridge/wasm_bridge.js';
const MODULE_PATH = 'makepad_wasm_bridge/static-message-bridge.js';
const ORIGINAL_METHOD = `create_js_message_bridge(wasm_app){
let msg=new FromWasmMsg(this,this.wasm_get_js_message_bridge(wasm_app));
let code=msg.read_str();
msg.free();
this.msg_class=new Function("ToWasmMsg","FromWasmMsg",code)(ToWasmMsg,FromWasmMsg);
}`;
const STATIC_METHOD = `create_js_message_bridge(wasm_app){
const ptr=this.wasm_get_js_message_bridge(wasm_app);
const code=readBridgeSchema(this.memory,ptr,ptr=>this.wasm_msg_free(ptr));
if(code!==expectedBridgeCode)throw new Error("Makepad bridge schema mismatch");
this.msg_class=createMessageClasses(ToWasmMsg,FromWasmMsg);
}`;
const sha256 = bytes => createHash('sha256').update(bytes).digest('hex');

// Used unchanged during extraction and by the generated static browser module.
// Match FromWasmMsg.read_str's u32 -> UTF-16 conversion, including truncation.
// Invalid pointers cannot safely be passed to the allocator's free function.
function readBridgeSchema(memory, ptr, free) {
  if (!Number.isInteger(ptr) || ptr <= 0 || ptr % 8 !== 0
      || ptr > memory.buffer.byteLength - 12) {
    throw new Error('Invalid Makepad schema pointer');
  }
  try {
    const words = new Uint32Array(memory.buffer);
    const start = ptr / 4 + 3;
    const length = words[start - 1];
    if (length === 0 || length > 1_048_576 || length > words.length - start) {
      throw new Error('Invalid Makepad schema length');
    }
    let code = '';
    for (let i = 0; i < length; i++) code += String.fromCharCode(words[start + i]);
    return code;
  } finally {
    free(ptr);
  }
}

async function extractSchema(bytes) {
  const module = await WebAssembly.compile(bytes);
  const imports = WebAssembly.Module.imports(module);
  const network = new Set([
    'js_network_http_request', 'js_network_http_cancel', 'js_network_ws_open',
    'js_network_ws_send_text', 'js_network_ws_send_binary', 'js_network_ws_close',
  ]);
  const harmless = new Set([
    'js_monotonic_now', 'js_time_now', 'js_wake_ui', 'js_console_error', 'js_console_log',
  ]);
  for (const entry of imports) {
    if (entry.module !== 'env' || entry.kind !== 'function'
        || (!network.has(entry.name) && !harmless.has(entry.name))) {
      throw new Error(`Unsupported Makepad extraction import: ${JSON.stringify(entry)}`);
    }
  }
  let instance;
  let diagnostics = '';
  const log = (ptr, length) => {
    const memory = instance?.exports.memory;
    if (!memory || !Number.isInteger(ptr) || !Number.isInteger(length)
        || ptr < 0 || length < 0 || ptr > memory.buffer.byteLength - length) {
      throw new Error('Invalid Makepad diagnostic pointer');
    }
    if (diagnostics.length < 8192) {
      diagnostics += new TextDecoder().decode(new Uint8Array(memory.buffer, ptr, Math.min(length, 4096)));
    }
  };
  const env = Object.create(null);
  for (const { name } of imports) {
    env[name] = network.has(name) ? () => { throw new Error(`Network import forbidden during schema extraction: ${name}`); }
      : name === 'js_time_now' ? () => Date.now() / 1000
      : name === 'js_monotonic_now' ? () => performance.now() / 1000
      : name === 'js_wake_ui' ? () => {}
      : log;
  }
  try {
    instance = await WebAssembly.instantiate(module, { env });
    const exports = instance.exports;
    if (!(exports.memory instanceof WebAssembly.Memory)) throw new Error('Missing Makepad memory export');
    for (const name of ['wasm_init_panic_hook', 'wasm_create_app', 'wasm_get_js_message_bridge', 'wasm_msg_free']) {
      if (typeof exports[name] !== 'function') throw new Error(`Missing Makepad export: ${name}`);
    }
    exports.wasm_init_panic_hook();
    const app = exports.wasm_create_app();
    if (!Number.isInteger(app) || app <= 0 || app % 4 || app >= exports.memory.buffer.byteLength) {
      throw new Error('Invalid Makepad application pointer');
    }
    const ptr = exports.wasm_get_js_message_bridge(app);
    return { code: readBridgeSchema(exports.memory, ptr, ptr => exports.wasm_msg_free(ptr)), imports };
  } catch (error) {
    throw new Error(`Makepad schema extraction failed: ${error.message}${diagnostics ? `\n${diagnostics}` : ''}`);
  }
}

function extractInWorker(bytes) {
  return new Promise((resolve, reject) => {
    const worker = new Worker(new URL(import.meta.url), {
      workerData: { kind: 'extract-makepad-schema', bytes },
      // Do not inherit --input-type/--test from the invoking build/test command.
      execArgv: [], resourceLimits: { maxOldGenerationSizeMb: 128 },
    });
    const timer = setTimeout(() => { worker.terminate(); reject(new Error('Makepad schema extraction timed out')); }, 15_000);
    worker.once('message', result => {
      clearTimeout(timer);
      if (result.error) reject(new Error(result.error));
      else resolve(result);
    });
    worker.once('error', error => { clearTimeout(timer); reject(error); });
    worker.once('exit', code => {
      clearTimeout(timer);
      if (code !== 0) reject(new Error(`Makepad schema extraction worker exited ${code}`));
    });
  });
}

/** Emit static classes from the exact package's WASM and patch its pristine bridge. */
export async function emitStaticBridge(packageDir) {
  const wasmFiles = (await readdir(packageDir)).filter(name => /^hepta-robrix\.[a-f0-9]+\.wasm$/.test(name));
  if (wasmFiles.length !== 1) throw new Error('Expected exactly one packaged Hepta WASM artifact');
  const wasmFile = wasmFiles[0];
  const bytes = await readFile(join(packageDir, wasmFile));
  if (bytes.length > 64 * 1024 * 1024) throw new Error('Packaged WASM exceeds extraction size limit');
  const originalBridge = await readFile(join(packageDir, BRIDGE_PATH), 'utf8');
  if (originalBridge.split(ORIGINAL_METHOD).length !== 2
      || originalBridge.includes('static-message-bridge.js')
      || (originalBridge.match(/\bnew\s+Function\s*\(/g) ?? []).length !== 1) {
    throw new Error('Unexpected pristine Makepad bridge shape; refusing to patch');
  }
  const { code, imports } = await extractInWorker(bytes);
  // These structural guards detect drift/corruption. Trust still comes from the
  // authenticated pinned compiler, never from this lexical check alone.
  if (!code.startsWith('return {\nToWasmMsg:class extends ToWasmMsg{\n')
      || code.split('},\nFromWasmMsg:class extends FromWasmMsg{\n').length !== 2
      || !code.endsWith('}\n}')
      || /\b(?:eval|Function|import|require|process|globalThis|window|document|fetch|constructor|static|get|set)\b|[\\`'"\u0000]/.test(code)) {
    throw new Error('Unexpected Makepad schema shape or executable construct');
  }
  const staticModule = `// Generated from ${wasmFile}; schema sha256 ${sha256(code)}.\n`
    + `export const expectedBridgeCode=${JSON.stringify(code)};\n`
    + `export ${readBridgeSchema.toString()}\n`
    + `export function createMessageClasses(ToWasmMsg,FromWasmMsg){\n${code}\n}\n`;
  // Parse, but never execute, the emitted module during packaging.
  execFileSync(process.execPath, ['--input-type=module', '--check'], {
    input: staticModule, encoding: 'utf8', timeout: 5000, maxBuffer: 1024 * 1024,
  });
  const bridge = `import {createMessageClasses,expectedBridgeCode,readBridgeSchema} from './static-message-bridge.js';\n`
    + originalBridge.replace(ORIGINAL_METHOD, STATIC_METHOD);
  if (/\b(?:eval\s*\(|new\s+Function\s*\()/.test(bridge)) throw new Error('Dynamic evaluation survived bridge packaging');
  await writeFile(join(packageDir, MODULE_PATH), staticModule);
  await writeFile(join(packageDir, BRIDGE_PATH), bridge);
  return {
    wasmFile, wasmSha256: sha256(bytes), schemaSha256: sha256(code), schemaCodeUnits: code.length,
    bridgePath: BRIDGE_PATH, originalBridgeSha256: sha256(originalBridge), packagedBridgeSha256: sha256(bridge),
    staticModulePath: MODULE_PATH, staticModuleSha256: sha256(staticModule), imports,
  };
}

if (!isMainThread && workerData?.kind === 'extract-makepad-schema') {
  try { parentPort.postMessage(await extractSchema(workerData.bytes)); }
  catch (error) { parentPort.postMessage({ error: error.message }); }
}
