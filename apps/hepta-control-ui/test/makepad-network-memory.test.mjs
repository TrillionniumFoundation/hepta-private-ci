// Real package libraries and HTTP callback, not browser/GPU visual acceptance.
// The transport import captures a request; it never opens a network connection.
import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtemp, readFile, readdir, rm, stat, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = process.env.HEPTA_CONTROL_UI_ROOT ?? fileURLToPath(new URL('..', import.meta.url));
const target = process.env.HEPTA_MAKEPAD_TARGET_PATH ?? join(root, 'rust/target/robrix-build/workspace/target');
const { patchMessageMemoryRefresh } = await import(pathToFileURL(join(root, 'tools/emit-static-makepad-bridge.mjs')));
async function filesBelow(path) {
  const files = [];
  for (const item of await readdir(path, { withFileTypes: true })) {
    const child = join(path, item.name);
    if (item.isDirectory()) files.push(...await filesBelow(child));
    else if (item.isFile()) files.push(child);
  }
  return files;
}

test('actual large HTTP callback preserves its UI wake after WASM memory growth', async t => {
  const artifacts = await filesBelow(target);
  const dependencyDirs = [...new Set(artifacts.filter(path => /\.(?:rmeta|so|dylib|dll)$/.test(path)).map(dirname))];
  async function latestMetadata(packageName, crateName) {
    const suffix = new RegExp(`[/\\\\]${packageName}[/\\\\][^/\\\\]+[/\\\\]out[/\\\\]lib${crateName}-[^/\\\\]+\\.rmeta$`);
    const candidates = await Promise.all(artifacts.filter(path => suffix.test(path)
      && path.includes('wasm32-unknown-unknown')).map(async path => ({ path, modified: (await stat(path)).mtimeMs })));
    assert.ok(candidates.length, `Build the actual WASM package first: missing ${crateName}`);
    candidates.sort((a, b) => b.modified - a.modified);
    return candidates[0].path;
  }
  const widgets = await latestMetadata('makepad-widgets', 'makepad_widgets');
  const standard = await latestMetadata('std', 'std');
  const temporary = await mkdtemp(join(tmpdir(), 'hepta-http-memory-'));
  t.after(() => rm(temporary, { recursive: true, force: true }));
  const source = `extern crate makepad_widgets;
use makepad_widgets::*;
#[no_mangle] pub extern "C" fn start_request() -> *mut Cx {
    let cx = Box::new(Cx::new(Box::new(|_, _| {})));
    cx.net.http_start(LiveId(42), makepad_widgets::makepad_platform::makepad_network::HttpRequest::new(
        "https://probe.invalid/font.ttf".into(), Default::default())).unwrap();
    Box::into_raw(cx)
}
#[no_mangle] pub unsafe extern "C" fn queued_body_len(cx: *mut Cx) -> u32 {
    let mut length = 0;
    while let Some(response) = (*cx).net.try_recv() {
        if let makepad_widgets::makepad_platform::makepad_network::NetworkResponse::HttpResponse { request_id, response } = response {
            let body = response.get_body().unwrap();
            assert_eq!(request_id, LiveId(42));
            assert_eq!(body.first(), Some(&42));
            assert_eq!(body.last(), Some(&42));
            length = body.len() as u32;
        }
    }
    length
}
`;
  const sourcePath = join(temporary, 'probe.rs'), wasmPath = join(temporary, 'probe.wasm');
  await writeFile(sourcePath, source);
  const args = ['-Zunstable-options', '--edition=2021', '--crate-type=cdylib', '--target',
    join(target, 'makepad-wasm-target/single/wasm32-unknown-unknown.json'), '-C', 'panic=abort',
    '-C', 'opt-level=0', '-C', 'debuginfo=0', sourcePath, '-o', wasmPath];
  for (const [name, metadata] of [['makepad_widgets', widgets], ['std', standard]]) {
    args.push('--extern', `${name}=${metadata}`, '--extern', `${name}=${metadata.replace(/\.rmeta$/, '.rlib')}`);
  }
  for (const path of dependencyDirs) args.push('-L', `dependency=${path}`);
  const rustc = process.env.HEPTA_NIGHTLY_RUSTC;
  execFileSync(rustc ?? 'rustup', rustc ? args : ['run', 'nightly-2026-10-02', 'rustc', ...args], {
    timeout: 60_000, maxBuffer: 1024 * 1024, stdio: 'pipe',
  });
  const module = await WebAssembly.compile(await readFile(wasmPath));
  const packaged = join(root, 'dist/makepad_wasm_bridge');
  const bridge = await readFile(join(packaged, 'wasm_bridge.js'), 'utf8');
  const originalAnchor = 'reserve_u32(u32_capacity){\nlet app=this.app;\n';
  const fixedAnchor = originalAnchor + 'app.update_array_buffer_refs();\n';
  // Keep an explicit red control from the exact pinned bridge. Only undo this
  // one reviewed insertion; keep all its other packaging/security changes.
  const original = bridge.includes(fixedAnchor) ? bridge.replace(fixedAnchor, originalAnchor) : bridge;
  assert.equal(original.split(originalAnchor).length, 2);
  const fixed = patchMessageMemoryRefresh(original);
  await writeFile(join(temporary, 'package.json'), '{"type":"module"}');
  await writeFile(join(temporary, 'static-message-bridge.js'), await readFile(join(packaged, 'static-message-bridge.js')));
  await writeFile(join(temporary, 'red.mjs'), original);
  await writeFile(join(temporary, 'fixed.mjs'), fixed);
  const messages = await import(pathToFileURL(join(temporary, 'static-message-bridge.js')));
  const evidence = [];
  for (const mode of ['red', 'fixed']) {
    const { WasmBridge, ToWasmMsg, FromWasmMsg } = await import(pathToFileURL(join(temporary, `${mode}.mjs`)));
    for (const size of [181792, 10643852, 19073964]) {
      let exports, request;
      const env = Object.create(null);
      for (const item of WebAssembly.Module.imports(module)) {
        assert.equal(item.module, 'env'); assert.equal(item.kind, 'function');
        env[item.name] = ['js_monotonic_now', 'js_time_now'].includes(item.name) ? () => 1
          : item.name === 'js_wake_ui' ? () => {}
          : item.name === 'js_network_http_request' ? (...args) => { request = args; }
          : () => { throw new Error(`HTTP memory probe unexpectedly called ${item.name}`); };
      }
      ({ exports } = await WebAssembly.instantiate(module, { env }));
      const app = new WasmBridge({ exports, _memory: exports.memory }, {});
      app.msg_class = messages.createMessageClasses(ToWasmMsg, FromWasmMsg);
      const cx = exports.start_request(); assert.ok(request);
      const pending = app.new_to_wasm();
      const headers = new TextEncoder().encode('content-type: font/ttf\r\n');
      const hp = app.wasm_new_data_u8(headers.length);
      new Uint8Array(exports.memory.buffer, hp, headers.length).set(headers);
      const bp = app.wasm_new_data_u8(size);
      new Uint8Array(exports.memory.buffer, bp, size).fill(42);
      const before = exports.memory.buffer.byteLength;
      // This is the actual SDK callback that changes Vec<u8> into Arc<[u8]>.
      exports.wasm_network_http_response(request[0], request[1], 0, 0, 200, hp, headers.length, bp, size);
      const after = exports.memory.buffer.byteLength, staleBytes = app.u32.byteLength;
      const flags = exports.wasm_check_signal(); assert.equal(flags, 5);
      pending.ToWasmSignal({ flags });
      const ptr = pending.ptr;
      app.new_to_wasm(); // Actual do_wasm_pump allocates next writer first.
      pending.release_ownership();
      const words = Array.from(new Uint32Array(exports.memory.buffer, ptr + 8, 4));
      const serialized = JSON.stringify(words) === JSON.stringify([761687900, 15491, 3, flags]);
      assert.equal(exports.queued_body_len(cx), size, 'complete body remains in the real Rust network queue');
      assert.equal(serialized, mode === 'fixed' || size === 181792);
      if (size > 181792) { assert.ok(after > before); assert.equal(staleBytes, 0); }
      evidence.push({ mode, size, before, after, staleBytes, flags, serialized });
    }
  }
  t.diagnostic(JSON.stringify(evidence));
});
