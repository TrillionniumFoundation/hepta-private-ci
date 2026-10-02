import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { emitStaticBridge } from '../tools/emit-static-makepad-bridge.mjs';

const schema = `return {
ToWasmMsg:class extends ToWasmMsg{
ToWasmPing(t0){this.app.value=t0.value;}
},
FromWasmMsg:class extends FromWasmMsg{
7(){this.app.received=this.app.value;}
}
}`;
const pristine = `export class ToWasmMsg{constructor(app){this.app=app;}}
export class FromWasmMsg{constructor(app){this.app=app;}}
export class WasmBridge{
create_js_message_bridge(wasm_app){
let msg=new FromWasmMsg(this,this.wasm_get_js_message_bridge(wasm_app));
let code=msg.read_str();
msg.free();
this.msg_class=new Function("ToWasmMsg","FromWasmMsg",code)(ToWasmMsg,FromWasmMsg);
}
}`;
const sha = data => createHash('sha256').update(data).digest('hex');
const uleb = value => { const out = []; do { let byte = value & 127; value >>>= 7; out.push(byte | (value ? 128 : 0)); } while (value); return out; };
const sleb = value => {
  const out = [];
  for (;;) { const byte = value & 127; value >>= 7; const done = (value === 0 && !(byte & 64)) || (value === -1 && !!(byte & 64)); out.push(byte | (done ? 0 : 128)); if (done) return out; }
};
const name = text => { const bytes = [...Buffer.from(text)]; return [...uleb(bytes.length), ...bytes]; };
const section = (id, bytes) => [id, ...uleb(bytes.length), ...bytes];

// A small real WASM module exercises the public packaging API without a Rust
// toolchain, network, or dynamic JavaScript evaluator in the test suite.
function fixtureWasm({ code = schema, ptr = 16, length = code.length, importName, importModule = 'env', callImport = false, malformedExport = false } = {}) {
  const imported = importName ? 1 : 0;
  const data = Buffer.alloc(12 + code.length * 4);
  data.writeUInt32LE(length, 8);
  for (let i = 0; i < code.length; i++) data.writeUInt32LE(code.charCodeAt(i), 12 + i * 4);
  const types = [4, 0x60, 0, 0, 0x60, 0, 1, 0x7f, 0x60, 1, 0x7f, 1, 0x7f, 0x60, 1, 0x7f, 0];
  const exports = [
    [...name('memory'), 2, 0], [...name('wasm_init_panic_hook'), 0, imported],
    [...name('wasm_create_app'), 0, imported + 1],
    [...name(malformedExport ? 'unexpected_schema' : 'wasm_get_js_message_bridge'), 0, imported + 2],
    [...name('wasm_msg_free'), 0, imported + 3], [...name('free_count'), 3, 0],
  ];
  const bodies = [
    [0, 0x0b],
    [0, ...(callImport ? [0x10, 0] : []), 0x41, 8, 0x0b],
    [0, 0x41, ...sleb(ptr), 0x0b],
    [0, 0x23, 0, 0x41, 1, 0x6a, 0x24, 0, 0x0b],
  ];
  return Buffer.from([
    0, 97, 115, 109, 1, 0, 0, 0,
    ...section(1, types),
    ...(imported ? section(2, [1, ...name(importModule), ...name(importName), 0, 0]) : []),
    ...section(3, [4, 0, 1, 2, 3]), ...section(5, [1, 0, 1]),
    ...section(6, [1, 0x7f, 1, 0x41, 0, 0x0b]),
    ...section(7, [exports.length, ...exports.flat()]),
    ...section(10, [bodies.length, ...bodies.flatMap(body => [...uleb(body.length), ...body])]),
    ...section(11, [1, 0, 0x41, 16, 0x0b, ...uleb(data.length), ...data]),
  ]);
}

async function packageFixture(t, options = {}) {
  const dir = await mkdtemp(join(tmpdir(), 'hepta-static-bridge-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  await mkdir(join(dir, 'makepad_wasm_bridge'));
  await writeFile(join(dir, 'package.json'), '{"type":"module"}');
  await writeFile(join(dir, 'hepta-robrix.123abc.wasm'), fixtureWasm(options));
  await writeFile(join(dir, 'makepad_wasm_bridge/wasm_bridge.js'), pristine);
  return dir;
}

test('exact WASM schema emits equivalent static classes, frees once, and hashes each artifact', async t => {
  const dir = await packageFixture(t);
  const result = await emitStaticBridge(dir);
  assert.equal(result.schemaSha256, sha(schema));
  assert.equal(result.originalBridgeSha256, sha(pristine));
  assert.deepEqual(result.imports, []);
  for (const [path, hash] of [[result.wasmFile, result.wasmSha256], [result.bridgePath, result.packagedBridgeSha256], [result.staticModulePath, result.staticModuleSha256]]) {
    assert.equal(sha(await readFile(join(dir, path))), hash);
  }
  const { WasmBridge, ToWasmMsg, FromWasmMsg } = await import(pathToFileURL(join(dir, result.bridgePath)));
  const { instance: { exports } } = await WebAssembly.instantiate(fixtureWasm());
  const app = { memory: exports.memory, wasm_get_js_message_bridge: exports.wasm_get_js_message_bridge, wasm_msg_free: exports.wasm_msg_free };
  WasmBridge.prototype.create_js_message_bridge.call(app, 8);
  assert.equal(exports.free_count.value, 1);
  const to = new app.msg_class.ToWasmMsg(app);
  const from = new app.msg_class.FromWasmMsg(app);
  assert.ok(to instanceof ToWasmMsg);
  assert.ok(from instanceof FromWasmMsg);
  to.ToWasmPing({ value: 42 }); from[7]();
  assert.deepEqual({ value: app.value, received: app.received }, { value: 42, received: 42 });
  assert.doesNotMatch(await readFile(join(dir, result.bridgePath), 'utf8'), /new\s+Function|\beval\s*\(/);
  await assert.rejects(emitStaticBridge(dir), /pristine Makepad bridge shape/);
});

test('runtime mismatched schema fails closed after freeing, before constructing classes', async t => {
  const dir = await packageFixture(t);
  const result = await emitStaticBridge(dir);
  const { WasmBridge } = await import(pathToFileURL(join(dir, result.bridgePath)));
  const { instance: { exports } } = await WebAssembly.instantiate(fixtureWasm({ code: schema.replace('value', 'other') }));
  const app = { memory: exports.memory, wasm_get_js_message_bridge: exports.wasm_get_js_message_bridge, wasm_msg_free: exports.wasm_msg_free };
  assert.throws(() => WasmBridge.prototype.create_js_message_bridge.call(app, 8), /schema mismatch/);
  assert.equal(exports.free_count.value, 1);
  assert.equal(app.msg_class, undefined);
});

for (const [label, options, expected] of [
  ['unaligned pointer', { ptr: 17 }, /schema pointer/],
  ['out-of-memory pointer', { ptr: 65536 }, /schema pointer/],
  ['negative pointer', { ptr: -8 }, /schema pointer/],
  ['empty schema', { length: 0 }, /schema length/],
  ['oversized schema', { length: 1_048_577 }, /schema length/],
  ['truncated schema', { length: 65536 }, /schema length/],
  ['missing export', { malformedExport: true }, /Missing Makepad export/],
  ['unknown import', { importName: 'js_unrecognized' }, /Unsupported Makepad extraction import/],
  ['foreign import module', { importName: 'js_time_now', importModule: 'other' }, /Unsupported Makepad extraction import/],
  ['network effect', { importName: 'js_network_ws_open', callImport: true }, /Network import forbidden/],
  ['injected evaluator', { code: schema.replace('t0.value', 'eval(t0.value)') }, /schema shape or executable construct/],
  ['escaped identifier', { code: schema.replace('t0.value', 'global\\u0054his.value') }, /schema shape or executable construct/],
  ['malformed JavaScript', { code: schema.replace('t0.value;', 't0.value);') }, /Command failed/],
]) {
  test(`rejects ${label} without modifying the pristine bridge`, async t => {
    const dir = await packageFixture(t, options);
    await assert.rejects(emitStaticBridge(dir), expected);
    assert.equal(await readFile(join(dir, 'makepad_wasm_bridge/wasm_bridge.js'), 'utf8'), pristine);
    await assert.rejects(readFile(join(dir, 'makepad_wasm_bridge/static-message-bridge.js')), { code: 'ENOENT' });
  });
}

test('bounded runtime reader frees a valid message once even when its length is malformed', async t => {
  const dir = await packageFixture(t);
  const result = await emitStaticBridge(dir);
  const { readBridgeSchema } = await import(pathToFileURL(join(dir, result.staticModulePath)));
  const memory = new WebAssembly.Memory({ initial: 1 });
  new Uint32Array(memory.buffer)[6] = 2_000_000;
  const freed = [];
  assert.throws(() => readBridgeSchema(memory, 16, ptr => freed.push(ptr)), /schema length/);
  assert.deepEqual(freed, [16]);
  assert.throws(() => readBridgeSchema(memory, 17, ptr => freed.push(ptr)), /schema pointer/);
  assert.deepEqual(freed, [16]);
});

test('unexpected bridge shape fails before any artifacts are emitted', async t => {
  const dir = await packageFixture(t);
  await writeFile(join(dir, 'makepad_wasm_bridge/wasm_bridge.js'), pristine.replace('let code=', 'const code='));
  await assert.rejects(emitStaticBridge(dir), /pristine Makepad bridge shape/);
});
