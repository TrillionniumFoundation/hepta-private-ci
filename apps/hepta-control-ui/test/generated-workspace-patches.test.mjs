// Exercise the generated Cargo root, including the original AccessKit patches.
import test from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync,spawnSync} from 'node:child_process';
import {cp,mkdir,mkdtemp,readFile,rm,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {rebaseWorkspacePatches} from '../tools/prepare-makepad-platform.mjs';

const workspace=fileURLToPath(new URL('../rust',import.meta.url));
const parse=text=>JSON.parse(execFileSync('python3',['-c','import json,sys,tomllib; print(json.dumps(tomllib.loads(sys.argv[1])))',text],{encoding:'utf8',timeout:10000}));

test('generated root resolves all four original AccessKit packages without changing other manifest fields',async()=>{
 const source=await readFile(join(workspace,'Cargo.toml'),'utf8');
 const destination=join(workspace,'target/robrix-build/workspace');
 const original=parse(source),generated=parse(rebaseWorkspacePatches(source,workspace,destination));
 const expected=['accesskit','accesskit_consumer','accesskit_atspi_common','accesskit_unix'];
 assert.deepEqual(Object.keys(original.patch['crates-io']).sort(),expected.sort());
 for(const name of expected){
  const before=original.patch['crates-io'][name],after=generated.patch['crates-io'][name];
  const location=resolve(workspace,before.path);
  assert.equal(resolve(destination,after.path),location);
  assert.equal(parse(await readFile(join(location,'Cargo.toml'),'utf8')).package.name,name);
  after.path=before.path;
 }
 assert.deepEqual(generated,original);
});

test('Cargo offline metadata selects the same patched package from a relocated workspace',{
 skip:spawnSync('cargo',['--version'],{encoding:'utf8',timeout:10000}).status!==0,
},async t=>{
 const root=await mkdtemp(join(tmpdir(),'hepta-workspace-patches-'));
 t.after(()=>rm(root,{recursive:true,force:true}));
 const source=join(root,'apps/control/rust'),destination=join(source,'target/robrix-build/workspace');
 const dependency=join(root,'codex-rs/third_party/fixture');
 for(const path of [join(source,'src'),join(destination,'src'),join(dependency,'src')])await mkdir(path,{recursive:true});
 const manifest='[package]\nname="overlay-patch-fixture"\nversion="0.1.0"\nedition="2021"\n[workspace]\n[dependencies]\npatch-fixture="=0.1.0"\n[patch.crates-io]\npatch-fixture={path="../../../codex-rs/third_party/fixture"}\n';
 await writeFile(join(dependency,'Cargo.toml'),'[package]\nname="patch-fixture"\nversion="0.1.0"\nedition="2021"\n');
 await writeFile(join(dependency,'src/lib.rs'),'pub fn fixture() {}\n');
 await writeFile(join(source,'Cargo.toml'),manifest);
 await writeFile(join(source,'src/lib.rs'),'pub use patch_fixture::fixture;\n');
 await cp(join(source,'src/lib.rs'),join(destination,'src/lib.rs'));
 const metadata=(path,locked)=>JSON.parse(execFileSync('cargo',['metadata','--offline',...(locked?['--locked']:[]),'--format-version=1','--manifest-path',join(path,'Cargo.toml')],{cwd:path,encoding:'utf8',timeout:30000}));
 const before=metadata(source,false);
 await cp(join(source,'Cargo.lock'),join(destination,'Cargo.lock'));
 await writeFile(join(destination,'Cargo.toml'),rebaseWorkspacePatches(manifest,source,destination));
 const after=metadata(destination,true);
 assert.equal(after.packages.find(p=>p.name==='patch-fixture').manifest_path,before.packages.find(p=>p.name==='patch-fixture').manifest_path);
 assert.deepEqual(await readFile(join(destination,'Cargo.lock')),await readFile(join(source,'Cargo.lock')));
});
