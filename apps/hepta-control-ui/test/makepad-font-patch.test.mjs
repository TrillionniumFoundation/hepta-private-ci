// Repeatable control-flow regression for the verified draw overlay. This does
// not test real glyph rasterization, font coverage, pixels or browser behavior.
import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('..', import.meta.url));
const draw = process.env.HEPTA_MAKEPAD_DRAW_SOURCE
  ?? join(root, 'rust/target/robrix-build/makepad-draw');
const rustc = process.env.HEPTA_RUSTC ?? 'rustc';
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
let temporary;
let source;

function method(text, signature) {
  const marker = `    ${signature}`;
  assert.equal(text.split(marker).length, 2, `Expected one ${signature}`);
  const start = text.indexOf(marker);
  let end = text.indexOf('{', start) + 1;
  let depth = 1;
  while (depth && end < text.length) {
    depth += Number(text[end] === '{') - Number(text[end] === '}');
    end++;
  }
  assert.equal(depth, 0, `Unclosed ${signature}`);
  return text.slice(start, end);
}

before(async () => {
  const patchRoot = join(root, 'rust/robrix-ui/patches');
  const identity = JSON.parse(await readFile(join(patchRoot, 'makepad-wasm-fonts.json'), 'utf8'));
  const upstream = JSON.parse(await readFile(join(root, 'rust/robrix-ui/UPSTREAM.json'), 'utf8'));
  assert.equal(identity.upstream, upstream.makepad.revision);
  assert.equal(sha(await readFile(join(patchRoot, 'makepad-wasm-fonts.patch'))), identity.patchSha256);
  assert.deepEqual(identity.files.map(file => file.path), [
    'src/text/fonts.rs', 'src/shader/draw_text.rs', 'src/text/rasterizer.rs',
  ]);
  const sources = new Map();
  for (const file of identity.files) {
    const bytes = await readFile(join(draw, file.path));
    assert.equal(sha(bytes), file.afterSha256, `Wrong patched source: ${file.path}`);
    sources.set(file.path, bytes.toString('utf8'));
  }
  const rasterizer = sources.get('src/text/rasterizer.rs');
  const text = sources.get('src/shader/draw_text.rs');
  const marker = '} else if cx\n';
  assert.equal(text.split(marker).length, 2);
  const start = text.indexOf(marker) + '} else if '.length;
  const end = text.indexOf('\n                {\n                    // An async resource', start);
  assert.ok(end > start);
  const condition = text.slice(start, end).trim();

  // Execute the actual patched dispatch and original setter. Only leaf glyph
  // operations are spies, so an MSDF path represents a queued background job.
  source = `#![allow(dead_code)]
use std::cell::RefCell;
#[derive(Clone, Copy)] enum OutlineRasterizationMode { Sdf, Msdf }
struct Font; type GlyphId = u32; struct RasterizedGlyph;
struct Rasterizer { outline_rasterization_mode: OutlineRasterizationMode, sdf: u32, queued: u32 }
impl Rasterizer {
${method(rasterizer, 'pub fn set_outline_rasterization_mode')}
${method(rasterizer, 'fn rasterize_glyph_outline(')}
fn rasterize_glyph_outline_sdf(&mut self, _: &Font, _: GlyphId, _: f32) -> Option<RasterizedGlyph> { self.sdf += 1; Some(RasterizedGlyph) }
fn rasterize_glyph_outline_msdf(&mut self, _: &Font, _: GlyphId, _: f32) -> Option<RasterizedGlyph> { self.queued += 1; Some(RasterizedGlyph) }
}
mod makepad_platform { pub mod script { pub mod res { pub enum CxScriptResourceData { NotLoaded, Loading, Loaded, Error } } } }
use makepad_platform::script::res::CxScriptResourceData as State;
struct Resource { abs_path: String, data: State }
struct Resources { resources: RefCell<Vec<Resource>> }
struct Script { resources: Resources }
struct Cx { script_data: Script }
struct Member { resource_path: String }
fn deferred(cx: &Cx, member: &Member) -> bool { ${condition} }
#[no_mangle] pub extern "C" fn probe_override() -> u32 {
    let mut r = Rasterizer { outline_rasterization_mode: OutlineRasterizationMode::Sdf, sdf: 0, queued: 0 };
    r.rasterize_glyph_outline(&Font, 0, 12.);
    r.set_outline_rasterization_mode(OutlineRasterizationMode::Msdf);
    r.rasterize_glyph_outline(&Font, 0, 12.);
    r.rasterize_glyph_outline(&Font, 1, 12.);
    (r.sdf << 8) | r.queued
}
#[no_mangle] pub extern "C" fn probe_pending() -> u32 {
    let mut mask = 0;
    for (i, state) in [State::NotLoaded, State::Loading, State::Loaded, State::Error].into_iter().enumerate() {
        let cx = Cx { script_data: Script { resources: Resources { resources: RefCell::new(vec![Resource { abs_path: "font".into(), data: state }]) } } };
        if deferred(&cx, &Member { resource_path: "font".into() }) { mask |= 1 << i; }
        assert!(!deferred(&cx, &Member { resource_path: "unknown".into() }));
    }
    mask
}
#[test] fn native_requested_modes_remain_unchanged() { assert_eq!(probe_override(), 258); }
#[test] fn only_registered_loading_defers_diagnostic() { assert_eq!(probe_pending(), 2); }
`;
  temporary = await mkdtemp(join(tmpdir(), 'hepta-font-dispatch-'));
  await writeFile(join(temporary, 'probe.rs'), source);
});

after(async () => { if (temporary) await rm(temporary, { recursive: true, force: true }); });

test('native requested mode and terminal resource diagnostics remain unchanged', () => {
  const binary = join(temporary, process.platform === 'win32' ? 'native-probe.exe' : 'native-probe');
  execFileSync(rustc, ['--edition=2021', '--test', join(temporary, 'probe.rs'), '-o', binary], { timeout: 30_000 });
  execFileSync(binary, [], { timeout: 10_000 });
});

test('non-atomic WASM cannot enqueue MSDF after a mode override', async () => {
  const wasm = join(temporary, 'probe.wasm');
  const cfg = execFileSync(rustc, ['--print=cfg', '--target=wasm32-unknown-unknown'], { encoding: 'utf8', timeout: 10_000 });
  assert.match(cfg, /^target_arch="wasm32"$/m);
  assert.doesNotMatch(cfg, /^target_feature="atomics"$/m);
  execFileSync(rustc, [
    '--edition=2021', '--crate-type=cdylib', '--target=wasm32-unknown-unknown',
    join(temporary, 'probe.rs'), '-o', wasm,
  ], { timeout: 30_000 });
  const { instance } = await WebAssembly.instantiate(await readFile(wasm), {});
  assert.equal(instance.exports.probe_override(), 768, 'Three SDF calls and zero queued MSDF jobs');
  assert.equal(instance.exports.probe_pending(), 2, 'Only the registered Loading state defers');
});
