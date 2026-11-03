// Uses the real built Makepad types and DrawVars::as_slice on the package's
// actual WASM target. It checks ABI packing, not browser/GPU visual acceptance.
import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdtemp, readFile, readdir, rm, stat, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('..', import.meta.url));
const generated = join(root, 'rust/target/robrix-build');
const target = process.env.HEPTA_MAKEPAD_TARGET_PATH ?? join(generated, 'workspace/target');
const sha = bytes => createHash('sha256').update(bytes).digest('hex');

async function filesBelow(path) {
  const files = [];
  for (const item of await readdir(path, { withFileTypes: true })) {
    const child = join(path, item.name);
    if (item.isDirectory()) files.push(...await filesBelow(child));
    else if (item.isFile()) files.push(child);
  }
  return files;
}

test('actual WASM instance arrays continue directly into live shader fields', async t => {
  const patchRoot = join(root, 'rust/robrix-ui/patches');
  const identity = JSON.parse(await readFile(join(patchRoot, 'makepad-wasm-instance-layout.json'), 'utf8'));
  const upstream = JSON.parse(await readFile(join(root, 'rust/robrix-ui/UPSTREAM.json'), 'utf8'));
  assert.equal(identity.upstream, upstream.makepad.revision);
  assert.equal(sha(await readFile(join(patchRoot, 'makepad-wasm-instance-layout.patch'))), identity.patchSha256);
  for (const file of identity.files) {
    assert.equal(sha(await readFile(join(generated, 'makepad-platform', file.path))), file.afterSha256, file.path);
  }
  const platformSource = await readFile(join(generated, 'makepad-platform/src/draw_vars.rs'), 'utf8');
  const slots = platformSource.match(/pub const DRAW_CALL_DYN_INSTANCES: usize = (\d+);/)?.[1];
  assert.ok(slots, 'Missing pinned dynamic instance capacity');

  const artifacts = await filesBelow(target);
  const dependencyDirs = [...new Set(artifacts
    .filter(path => /\.(?:rmeta|so|dylib|dll)$/.test(path))
    .map(dirname))];
  async function latestMetadata(packageName, crateName) {
    const suffix = new RegExp(`[/\\\\]${packageName}[/\\\\][^/\\\\]+[/\\\\]out[/\\\\]lib${crateName}-[^/\\\\]+\\.rmeta$`);
    const candidates = await Promise.all(artifacts.filter(path => suffix.test(path)
      && path.includes('wasm32-unknown-unknown')).map(async path => ({ path, modified: (await stat(path)).mtimeMs })));
    assert.ok(candidates.length, `Build the actual WASM package first: missing ${crateName}`);
    candidates.sort((a, b) => b.modified - a.modified);
    return candidates[0].path;
  }
  const draw = process.env.HEPTA_MAKEPAD_DRAW_RMETA ?? await latestMetadata('makepad-draw', 'makepad_draw');
  const standard = await latestMetadata('std', 'std');
  const temporary = await mkdtemp(join(tmpdir(), 'hepta-real-instance-'));
  t.after(() => rm(temporary, { recursive: true, force: true }));
  const source = `extern crate makepad_draw;
use makepad_draw::{Area, Cx, DrawText, DrawVars, LiveId, ScriptNew, ScriptVmCx, live_id, vec2, vec4};
use std::mem::{offset_of, size_of};
const DRAW_CALL_DYN_INSTANCES: usize = ${slots};
const _: () = assert!(offset_of!(DrawVars, dyn_instances) + size_of::<[f32; DRAW_CALL_DYN_INSTANCES]>() == size_of::<DrawVars>());
const _: () = assert!(offset_of!(DrawText, rect_pos) == offset_of!(DrawText, draw_vars) + size_of::<DrawVars>());
#[repr(C)] struct Payload { vars: DrawVars, following: [f32; 4] }
#[no_mangle] pub extern "C" fn array_end() -> usize { offset_of!(DrawVars, dyn_instances) + size_of::<[f32; DRAW_CALL_DYN_INSTANCES]>() }
#[no_mangle] pub extern "C" fn vars_size() -> usize { size_of::<DrawVars>() }
#[no_mangle] pub extern "C" fn text_first_field() -> usize { offset_of!(DrawText, rect_pos) - offset_of!(DrawText, draw_vars) }
#[no_mangle] pub extern "C" fn known_floats_are_contiguous() -> u32 {
    let payload = Payload {
        vars: DrawVars {
            area: Area::Empty,
            dyn_instance_start: DRAW_CALL_DYN_INSTANCES - 2,
            dyn_instance_slots: 6,
            options: Default::default(),
            append_group_id: 0,
            draw_shader_id: None,
            geometry_id: None,
            dyn_uniforms: std::array::from_fn(|_| 0.),
            texture_slots: std::array::from_fn(|_| None),
            uniform_buffer_slots: std::array::from_fn(|_| None),
            dyn_instances_padding: 0.,
            dyn_instances: std::array::from_fn(|i| if i == DRAW_CALL_DYN_INSTANCES - 2 { 11. } else if i == DRAW_CALL_DYN_INSTANCES - 1 { 22. } else { 0. }),
        },
        following: [33., 44., 55., 66.],
    };
    u32::from(payload.vars.as_slice() == [11., 22., 33., 44., 55., 66.])
}
#[no_mangle] pub extern "C" fn actual_text_fields_are_contiguous() -> u32 {
    let mut cx = Cx::new(Box::new(|_, _| {}));
    cx.with_vm(|vm| {
        makepad_draw::script_mod(vm);
        let mut text = DrawText::script_new_with_default(vm);
        text.rect_pos = vec2(11., 22.);
        text.color = vec4(0.125, 0.25, 0.5, 1.);
        let mut position = [0.; 2];
        let mut color = [0.; 4];
        vm.with_cx_mut(|cx| {
            text.draw_vars.get_instance(cx, live_id!(rect_pos), &mut position);
            text.draw_vars.get_instance(cx, live_id!(color), &mut color);
        });
        u32::from(position == [11., 22.] && color == [0.125, 0.25, 0.5, 1.])
    })
}
`;
  const sourcePath = join(temporary, 'probe.rs');
  const wasmPath = join(temporary, 'probe.wasm');
  await writeFile(sourcePath, source);
  const args = ['-Zunstable-options', '--edition=2021', '--crate-type=cdylib',
    '--target', join(target, 'makepad-wasm-target/single/wasm32-unknown-unknown.json'),
    '-C', 'panic=abort', sourcePath, '-o', wasmPath];
  // This pinned nightly stores code and metadata separately. Supply both exact
  // artifacts, so rustc uses the real definitions and their matching object code.
  for (const [name, metadata] of [['makepad_draw', draw], ['std', standard]]) {
    args.push('--extern', `${name}=${metadata}`, '--extern', `${name}=${metadata.replace(/\.rmeta$/, '.rlib')}`);
  }
  for (const path of dependencyDirs) args.push('-L', `dependency=${path}`);
  const rustc = process.env.HEPTA_NIGHTLY_RUSTC;
  try {
    execFileSync(rustc ?? 'rustup', rustc ? args : ['run', 'nightly', 'rustc', ...args], {
      timeout: 60_000, maxBuffer: 1024 * 1024, stdio: 'pipe',
    });
  } catch (error) {
    throw new Error(`Actual Makepad WASM ABI probe compilation failed:\n${error.stderr ?? error.message}`);
  }
  const module = await WebAssembly.compile(await readFile(wasmPath));
  const imports = Object.create(null);
  for (const entry of WebAssembly.Module.imports(module)) {
    assert.equal(entry.module, 'env');
    assert.equal(entry.kind, 'function');
    imports[entry.name] = entry.name === 'js_monotonic_now' ? () => performance.now() / 1000
      : entry.name === 'js_time_now' ? () => Date.now() / 1000
      : ['js_console_log', 'js_wake_ui'].includes(entry.name) ? () => {}
      : () => { throw new Error(`ABI probe unexpectedly called ${entry.name}`); };
  }
  const { exports } = await WebAssembly.instantiate(module, { env: imports });
  assert.equal(exports.array_end(), exports.vars_size());
  assert.equal(exports.text_first_field(), exports.vars_size());
  assert.equal(exports.known_floats_are_contiguous(), 1);
  assert.equal(exports.actual_text_fields_are_contiguous(), 1);
});
