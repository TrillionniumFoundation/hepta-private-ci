// Build/packaging tooling only. Product UI and event handling live in Rust/Makepad.
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { cp, mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import {preparePlatform} from './prepare-makepad-platform.mjs';
import {robrixSourceIdentity} from './robrix-source-identity.mjs';
import {emitStaticBridge} from './emit-static-makepad-bridge.mjs';
const root = fileURLToPath(new URL('..', import.meta.url));
const workspace = join(root, 'rust');
let source;
const fixtures=process.argv.includes('--fixtures');
const output = join(root, fixtures?'dist-robrix-fixtures':'dist');
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const provenance = JSON.parse(await readFile(join(workspace, 'robrix-ui/UPSTREAM.json'), 'utf8'));
const sourceIdentity=await robrixSourceIdentity(root);
const metadata=JSON.parse(execFileSync('cargo',['+1.95.0','metadata','--locked','--format-version','1','--manifest-path',join(workspace,'Cargo.toml')],{encoding:'utf8',maxBuffer:16*1024*1024}));
const widgets=metadata.packages.find(p=>p.name==='makepad-widgets');
if(!widgets?.source?.endsWith('#'+provenance.makepad.revision)) throw new Error('Makepad lock does not match provenance');
const makepadRoot=dirname(dirname(widgets.manifest_path));
if(execFileSync('git',['-C',makepadRoot,'rev-parse','HEAD'],{encoding:'utf8'}).trim()!==provenance.makepad.revision) throw new Error('Wrong Makepad checkout');
execFileSync('git',['-C',makepadRoot,'diff','--quiet','HEAD','--']);
const nightly=execFileSync('rustup',['run','nightly','rustc','--version'],{encoding:'utf8'}).trim();
if(nightly!=='rustc 1.101.0-nightly (c36f14571 2026-10-01)') throw new Error('Unqualified nightly: '+nightly);
const toolTarget=join(workspace,'target/robrix-tools');
// Upstream intentionally has no tracked lockfile. Build its tool in an isolated
// exact Git archive with our reviewed lock; never depend on or modify cache state.
const toolSource=join(workspace,'target/robrix-tool-source');
const toolArchive=join(workspace,'target/robrix-tool-source.tar');
await mkdir(dirname(toolSource),{recursive:true});
await rm(toolSource,{recursive:true,force:true});
await mkdir(toolSource,{recursive:true});
execFileSync('git',['-C',makepadRoot,'archive','--format=tar','--output='+toolArchive,provenance.makepad.revision]);
try {execFileSync('tar',['-xf',toolArchive,'-C',toolSource]);}
finally {await rm(toolArchive,{force:true});}
const packagerLock=await readFile(join(workspace,'robrix-ui/patches/cargo-makepad.Cargo.lock'));
await writeFile(join(toolSource,'Cargo.lock'),packagerLock);
const toolEnv={...process.env,CARGO_BUILD_JOBS:'1',CARGO_INCREMENTAL:'0',CARGO_PROFILE_DEV_DEBUG:'0'};
for(const name of ['CARGO_BUILD_TARGET','CARGO_ENCODED_RUSTFLAGS','RUSTFLAGS']) delete toolEnv[name];
execFileSync('cargo',['+1.95.0','build','--locked','--manifest-path',join(toolSource,'tools/cargo_makepad/Cargo.toml'),'--bin','cargo-makepad','--target-dir',toolTarget],{stdio:'inherit',env:toolEnv});
if(sha(await readFile(join(toolSource,'Cargo.lock')))!==sha(packagerLock)) throw new Error('Packager lock changed');
const packager=join(toolTarget,'debug',process.platform==='win32'?'cargo-makepad.exe':'cargo-makepad');
const overlay=await preparePlatform(workspace,makepadRoot,provenance.makepad.revision);
source=join(overlay.workspace,'target/makepad-wasm-app/release/hepta-robrix-ui');
const packageEnv={...process.env,CARGO_TARGET_DIR:join(overlay.workspace,'target'),CARGO_BUILD_JOBS:'1',CARGO_INCREMENTAL:'0',CARGO_PROFILE_RELEASE_DEBUG:'0'};
delete packageEnv.CARGO_ENCODED_RUSTFLAGS;
delete packageEnv.RUSTFLAGS;
delete packageEnv.CARGO_BUILD_TARGET;
execFileSync(packager,['wasm','--no-threads','build','-p','hepta-robrix-ui','--bin','hepta-robrix','--release',...(fixtures?['--features','hepta-robrix-ui/ui-fixtures']:[])],{cwd:overlay.workspace,stdio:'inherit',env:packageEnv});
const canonicalLock=await readFile(join(workspace,'Cargo.lock'),'utf8');
const generatedLock=await readFile(join(overlay.workspace,'Cargo.lock'),'utf8');
let expectedLock=canonicalLock;
const expectedSource=`source = "git+https://github.com/kevinaboos/makepad?rev=${provenance.makepad.revision}#${provenance.makepad.revision}"\n`;
for(const name of ['makepad-platform','makepad-draw']){
 const header=`[[package]]\nname = "${name}"\nversion = "2.0.0"\n`;
 const start=expectedLock.indexOf(header)+header.length;
 const end=expectedLock.indexOf('\n',start)+1;
 if(start<header.length||expectedLock.slice(start,end)!==expectedSource) throw new Error('Unexpected locked overlay source: '+name);
 expectedLock=expectedLock.slice(0,start)+expectedLock.slice(end);
}
if(expectedLock!==generatedLock) throw new Error('Generated lock changed beyond the exact platform/draw overlays');
if((await robrixSourceIdentity(root)).sha256!==sourceIdentity.sha256) throw new Error('UI source changed during build; rebuild before qualification');
const rawHtml = await readFile(join(source, 'index.html'), 'utf8');
const wasmName = rawHtml.match(/['"]\.\/(hepta-robrix\.[a-f0-9]+\.wasm)['"]/)?.[1];
if (!wasmName) throw new Error('Unexpected pinned Makepad bootstrap; refusing to package');
await rm(output, { recursive: true, force: true });
await mkdir(output, { recursive: true });
await cp(source, output, { recursive: true });
// The app entry is a bin backed by a Rust library. Bind the library resource
// alias explicitly instead of depending on the packager's bin-only alias.
const art=JSON.parse(await readFile(join(workspace,'robrix-ui/resources/ASSETS.json'),'utf8'));
for(const asset of art.assets){
 if(asset.path!=='lunar-titanium.png')throw new Error('Unexpected UI art asset');
 const bytes=await readFile(join(workspace,'robrix-ui/resources',asset.path));
 if(bytes.length!==asset.bytes||sha(bytes)!==asset.sha256)throw new Error('UI art source identity drift');
 const destination=join(output,'hepta_robrix_ui/resources',asset.path);
 await mkdir(dirname(destination),{recursive:true});await writeFile(destination,bytes);
}

const frameworkPath = join(output, 'makepad_platform/web.js');
let framework = await readFile(frameworkPath, 'utf8');
const originalFrameworkSha256 = sha(framework);
// Remove upstream network crash upload at its transport boundary. No report is
// sent, including pagehide sendBeacon/fallback GET; runtime error state remains.
const start = framework.indexOf('const fallback_get=async payload=>{');
const end = framework.indexOf('const take_pending_panic=()=>{', start);
if (start < 0 || end <= start || !framework.slice(start, end).includes("fetch('/api/crash'")) throw new Error('Pinned crash transport changed');
framework = framework.slice(0, start) + 'const send=async()=>false;\n' + framework.slice(end);
// Move the pinned framework textarea stylesheet to a same-origin CSS asset.
// Property-level runtime positioning remains platform glue, not inline rules.
const styleStart = framework.indexOf("var style=document.createElement('style')");
const styleEndToken = 'document.body.appendChild(style)';
const styleEnd = framework.indexOf(styleEndToken, styleStart);
if (styleStart < 0 || styleEnd < 0) throw new Error('Pinned input stylesheet changed');
const expression = framework.slice(styleStart, styleEnd).split('style.innerHTML=')[1];
if (!expression) throw new Error('Missing pinned input stylesheet');
const literals = [...expression.matchAll(/"(?:[^"\\]|\\.)*"/g)].map(match => JSON.parse(match[0]));
if (!literals.length) throw new Error('Empty input stylesheet');
await writeFile(join(output, 'input-platform.css'), literals.join(''));
framework = framework.slice(0, styleStart) + framework.slice(styleEnd + styleEndToken.length);
if (framework.includes("fetch('/api/crash'") || framework.includes("fetch('/$report_error") || framework.includes("sendBeacon('/api/crash'")) throw new Error('Crash transport survived packaging');
await writeFile(frameworkPath, framework);
// Generated loader glue contains no application state/actions or transcript.
await writeFile(join(output, 'bootstrap.js'), `import {WasmWebGL} from './makepad_platform/web_gl.js';\ndocument.documentElement.dataset.heptaBootPhase='fetch-and-instantiate-wasm';\ntry {\n const wasm=await WasmWebGL.fetch_and_instantiate_wasm('./${wasmName}');\n document.documentElement.dataset.heptaBootPhase='construct-webgl-host';\n const host=new WasmWebGL(wasm, {}, document.querySelector('canvas'));\n if(!host.gl){\n  document.documentElement.dataset.heptaBootPhase='webgl2-unavailable';\n  const loader=document.querySelector('.canvas_loader');\n  loader.textContent='WebGL2 is unavailable in this browser or graphics environment. Conversations cannot be rendered here.';\n  loader.setAttribute('role','alert');\n }else document.documentElement.dataset.heptaBootPhase='webgl-host-constructed';\n} catch(error) {\n document.documentElement.dataset.heptaBootPhase='bootstrap-failed';\n throw error;\n}\n`);
const csp = "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self'; connect-src 'self'; img-src 'self' data:; font-src 'self'; worker-src 'self' blob:; object-src 'none'; base-uri 'none'; form-action 'none'";
await writeFile(join(output, 'index.html'), `<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="Content-Security-Policy" content="${csp}"><title>Hepta Conversations</title><link rel="stylesheet" href="./makepad_platform/full_canvas.css"><link rel="stylesheet" href="./input-platform.css"><script type="module" src="./bootstrap.js"></script></head><body><canvas class="full_canvas" aria-label="Hepta conversations"></canvas><div class="canvas_loader">Loading conversations…</div></body></html>\n`);
await cp(join(workspace, 'robrix-ui/licenses'), join(output, 'licenses'), { recursive: true });
await cp(join(makepadRoot,'LICENSE'),join(output,'licenses/MAKEPAD-MIT.txt'));
await cp(join(workspace,'robrix-ui/UPSTREAM.json'),join(output,'UPSTREAM.json'));
const staticBridge=await emitStaticBridge(output);
const files = {};
async function inventory(dir) {
 for (const entry of (await readdir(dir, {withFileTypes:true})).sort((a,b)=>a.name.localeCompare(b.name))) {
  const path=join(dir,entry.name);
  if (entry.isDirectory()) await inventory(path);
  else {const bytes=await readFile(path);files[relative(output,path).replaceAll('\\','/')]={bytes:bytes.length,sha256:sha(bytes)};}
 }
}
await inventory(output);
await writeFile(join(output,'build-manifest.json'),JSON.stringify({schema:'hepta.robrix-ui.build.v1',browserRuntime:'rust-makepad-wasm',fixtures,sourceIdentity,staticBridge,upstream:provenance,artAssets:art,nightly,platformPatch:overlay.identity,instanceLayoutPatch:overlay.layoutIdentity,drawPatch:overlay.drawIdentity,drawManifestSha256:overlay.drawManifestSha256,platformManifestSha256:overlay.platformManifestSha256,canonicalLockSha256:sha(canonicalLock),generatedLockSha256:sha(await readFile(join(overlay.workspace,'Cargo.lock'))),packagerSource:provenance.makepad.revision,packagerLockSha256:sha(packagerLock),packagerSha256:sha(await readFile(packager)),threads:false,automaticCrashUpload:false,viewportZoomRestrictionRemoved:true,originalFrameworkSha256,packagedFrameworkSha256:sha(framework),files},null,2)+'\n');
console.log(`Packaged Robrix-derived Rust UI (${Object.keys(files).length} assets); rendering still requires host acceptance`);
