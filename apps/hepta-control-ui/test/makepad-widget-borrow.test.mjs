// Exercises the real pinned Makepad View/WidgetRef/PortalList borrow boundary.
// This is a WASM runtime regression, not browser/GPU acceptance.
import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { robrixSourceIdentity } from '../tools/robrix-source-identity.mjs';
import { mkdtemp, readFile, readdir, rm, mkdir, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = fileURLToPath(new URL('..', import.meta.url));
const generated = join(root, 'rust/target/robrix-build');
const target = join(generated, 'workspace/target');
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

test('actual parent redraw releases child guards and defers draw-generated actions', async t => {
  const artifacts = await filesBelow(target);
  const dependencyDirs = [...new Set(artifacts
    .filter(path => /\.(?:rmeta|so|dylib|dll)$/.test(path))
    .map(dirname))];
  async function exactMetadata(packageName, crateName) {
    const suffix = new RegExp(`[/\\\\]${packageName}[/\\\\][^/\\\\]+[/\\\\]out[/\\\\]lib${crateName}-[^/\\\\]+\\.rmeta$`);
    const candidates = artifacts.filter(path => suffix.test(path) && path.includes('wasm32-unknown-unknown'));
    assert.equal(candidates.length, 1, `Require exactly one built ${crateName} artifact; reject stale/ambiguous cache candidates`);
    return candidates[0];
  }
  const widgets = await exactMetadata('makepad-widgets', 'makepad_widgets');
  const standard = await exactMetadata('std', 'std');
  const provenance = JSON.parse(await readFile(join(root, 'rust/robrix-ui/UPSTREAM.json'), 'utf8'));
  const manifestBytes = await readFile(join(root, 'dist/build-manifest.json'));
  const manifest = JSON.parse(manifestBytes);
  assert.equal(manifest.packagerSource, provenance.makepad.revision);
  assert.equal(manifest.upstream.makepad.revision, provenance.makepad.revision);
  const lock = await readFile(join(generated, 'workspace/Cargo.lock'));
  assert.equal(sha(lock), manifest.generatedLockSha256, 'SDK build lock changed');
  const widgetPackage = lock.toString().split('[[package]]').filter(block => /name = "makepad-widgets"/.test(block));
  assert.equal(widgetPackage.length, 1);
  assert.ok(widgetPackage[0].includes('#' + provenance.makepad.revision + '"'), 'Built widget lock must name the exact SDK revision');
  const dependencyFile = widgets.replace(/libmakepad_widgets-([^/]+)\.rmeta$/, 'makepad_widgets-$1.d');
  const dependencyText = await readFile(dependencyFile, 'utf8');
  const sourceFile = dependencyText.match(/(?:^|\s)(\/[^\s]+\/widgets\/src\/lib\.rs)(?:\s|$)/)?.[1];
  assert.ok(sourceFile, 'Missing actual widgets dependency source');
  const sdkRoot = dirname(dirname(dirname(sourceFile)));
  assert.equal(execFileSync('git', ['-C', sdkRoot, 'rev-parse', 'HEAD'], {encoding:'utf8'}).trim(), provenance.makepad.revision);
  execFileSync('git', ['-C', sdkRoot, 'diff', '--exit-code', provenance.makepad.revision, '--', 'widgets'], {stdio:'pipe'});
  const sourceIdentityCurrent = (await robrixSourceIdentity(root)).sha256 === manifest.sourceIdentity.sha256;
  if(process.env.GITHUB_ACTIONS === 'true') assert.equal(sourceIdentityCurrent, true, 'CI probe must follow this candidate build');
  const compiler = process.env.HEPTA_NIGHTLY_RUSTC;
  const compilerVersion = execFileSync(compiler ?? 'rustup', compiler ? ['--version'] : ['run', 'nightly-2026-10-02', 'rustc', '--version'], {encoding:'utf8'}).trim();
  assert.equal(compilerVersion, manifest.nightly, 'Probe and producer compiler differ');
  const artifactHashes = {};
  for(const path of [widgets, widgets.replace(/\.rmeta$/, '.rlib'), standard, standard.replace(/\.rmeta$/, '.rlib')]) artifactHashes[path] = sha(await readFile(path));
  const temporary = await mkdtemp(join(tmpdir(), 'hepta-real-widget-borrow-'));
  t.after(() => rm(temporary, { recursive: true, force: true }));
  const source = `extern crate makepad_widgets;
use makepad_widgets::*;
use std::sync::atomic::{AtomicU32, Ordering};
static PANIC: AtomicU32 = AtomicU32::new(0);
fn setup() -> (Cx, View, WidgetRef) {
    std::panic::set_hook(Box::new(|info| {
        PANIC.store(u32::from(info.to_string().contains("already borrowed")), Ordering::SeqCst);
    }));
    let mut cx = Cx::new(Box::new(|_, _| {}));
    let (parent, list) = cx.with_vm(|vm| {
        let list = WidgetRef::new_with_inner(Box::new(PortalList::script_new(vm)));
        let mut parent = View::script_new(vm);
        parent.children.push((live_id!(list), list.clone()));
        (parent, list)
    });
    (cx, parent, list)
}
#[no_mangle] pub extern "C" fn held_child_guard_parent_redraw() {
    let (mut cx, mut parent, list) = setup();
    let guard = list.borrow::<PortalList>().expect("real list");
    parent.redraw(&mut cx);
    drop(guard);
}
#[no_mangle] pub extern "C" fn released_child_guard_parent_redraw() -> u32 {
    let (mut cx, mut parent, list) = setup();
    let redraw_parent = list.borrow::<PortalList>().is_some_and(|inner| {
        let _actual_state = inner.is_at_end();
        true
    });
    if redraw_parent { parent.redraw(&mut cx); }
    u32::from(redraw_parent)
}
#[no_mangle] pub extern "C" fn panic_was_reborrow() -> u32 { PANIC.load(Ordering::SeqCst) }
static DRAWS: AtomicU32=AtomicU32::new(0);
static ACTIONS: AtomicU32=AtomicU32::new(0);
static NEXTS: AtomicU32=AtomicU32::new(0);
#[no_mangle] pub extern "C" fn start(mode:u32)->*mut Cx {
 let mut list: Option<DrawList> = None;
 let mut pending: Option<NextFrame> = None;
 let mut cx=Box::new(Cx::new(Box::new(move |cx,event| {
  match event {
   Event::Draw(_) => {if DRAWS.fetch_add(1,Ordering::SeqCst)==0 {list=Some(DrawList::new(cx)); cx.action(1u32);}},
   Event::Actions(_) => {ACTIONS.fetch_add(1,Ordering::SeqCst); if mode==0 {cx.redraw_list(list.as_ref().unwrap().id());} else {pending=Some(cx.new_next_frame());}},
   _ => {if pending.is_some_and(|token|token.is_event(event).is_some()) {pending=None; NEXTS.fetch_add(1,Ordering::SeqCst);cx.redraw_list(list.as_ref().unwrap().id());}}
  }
 })));
 cx.redraw_all();Box::into_raw(cx)
}
#[no_mangle] pub unsafe extern "C" fn pump(cx:*mut Cx,msg:u32)->u32 {(*cx).process_to_wasm(msg)}
#[no_mangle] pub extern "C" fn draws()->u32 {DRAWS.load(Ordering::SeqCst)}
#[no_mangle] pub extern "C" fn actions()->u32 {ACTIONS.load(Ordering::SeqCst)}
#[no_mangle] pub extern "C" fn nexts()->u32 {NEXTS.load(Ordering::SeqCst)}
`;
  const sourcePath = join(temporary, 'probe.rs');
  const wasmPath = join(temporary, 'probe.wasm');
  await writeFile(sourcePath, source);
  const args = ['-Zunstable-options', '--edition=2021', '--crate-type=cdylib',
    '--target', join(target, 'makepad-wasm-target/single/wasm32-unknown-unknown.json'),
    '-C', 'panic=abort', sourcePath, '-o', wasmPath];
  // This pinned nightly stores code and metadata separately. Supply both exact
  // artifacts, so rustc uses the real definitions and their matching object code.
  for (const [name, metadata] of [['makepad_widgets', widgets], ['std', standard]]) {
    args.push('--extern', `${name}=${metadata}`, '--extern', `${name}=${metadata.replace(/\.rmeta$/, '.rlib')}`);
  }
  for (const path of dependencyDirs) args.push('-L', `dependency=${path}`);
  const rustc = process.env.HEPTA_NIGHTLY_RUSTC;
  try {
    execFileSync(rustc ?? 'rustup', rustc ? args : ['run', 'nightly-2026-10-02', 'rustc', ...args], {
      timeout: 60_000, maxBuffer: 1024 * 1024, stdio: 'pipe',
    });
  } catch (error) {
    throw new Error(`Actual Makepad widget borrow probe compilation failed:\n${error.stderr ?? error.message}`);
  }
  const module = await WebAssembly.compile(await readFile(wasmPath));
  const imports = Object.create(null);
  for (const entry of WebAssembly.Module.imports(module)) {
    assert.equal(entry.module, 'env');
    assert.equal(entry.kind, 'function');
    imports[entry.name] = entry.name === 'js_monotonic_now' ? () => performance.now() / 1000
      : entry.name === 'js_time_now' ? () => Date.now() / 1000
      : ['js_console_log', 'js_wake_ui'].includes(entry.name) ? () => {}
      : () => { throw new Error(`Widget probe unexpectedly called ${entry.name}`); };
  }
  const negative = await WebAssembly.instantiate(module, { env: imports });
  assert.throws(() => negative.exports.held_child_guard_parent_redraw(), WebAssembly.RuntimeError);
  assert.equal(negative.exports.panic_was_reborrow(), 1, 'Negative control must hit the actual RefCell reborrow');
  const positive = await WebAssembly.instantiate(module, { env: imports });
  assert.equal(positive.exports.released_child_guard_parent_redraw(), 1);
  assert.equal(positive.exports.panic_was_reborrow(), 0);
  const packaged = join(root,'dist/makepad_wasm_bridge');
  const {WasmBridge,ToWasmMsg,FromWasmMsg}=await import(pathToFileURL(join(packaged,'wasm_bridge.js')));
  const messages=await import(pathToFileURL(join(packaged,'static-message-bridge.js')));
  const observations=[];
  for(const mode of [0,1]) {
    const {exports}=await WebAssembly.instantiate(module,{env:imports});
    const app=new WasmBridge({exports,_memory:exports.memory},{});
    app.msg_class=messages.createMessageClasses(ToWasmMsg,FromWasmMsg);
    const cx=exports.start(mode);
    for(let frame=1;frame<=3;frame++) {
      const msg=app.new_to_wasm();msg.ToWasmAnimationFrame({time:frame});
      const ptr=msg.ptr;msg.release_ownership();const result=exports.pump(cx,ptr);
      exports.wasm_msg_free(result);
      observations.push({mode,frame,draws:exports.draws(),actions:exports.actions(),nexts:exports.nexts()});
    }
    assert.equal(exports.actions(),1);
    assert.equal(exports.draws(),mode===0?1:2);
    assert.equal(exports.nexts(),mode===0?0:1);
  }
  const receipt = {schema:'hepta.makepad-widget-borrow-probe.v1',scope:'SDK borrow contract only',appQualified:false,sourceIdentityCurrent,producerSourceIdentity:manifest.sourceIdentity.sha256,producerManifestSha256:sha(manifestBytes),sdkRevision:provenance.makepad.revision,generatedLockSha256:sha(lock),compilerVersion,artifactHashes,probeSourceSha256:sha(source),probeWasmSha256:sha(await readFile(wasmPath)),negativeReborrowObserved:true,releasedGuardRedrawPassed:true,drawActionRedraw:observations};
  await mkdir(join(root, 'test-results'), {recursive:true});
  await writeFile(join(root, 'test-results/robrix-widget-borrow-results.json'), JSON.stringify(receipt,null,2)+'\n');
  console.log(JSON.stringify(receipt));
});
