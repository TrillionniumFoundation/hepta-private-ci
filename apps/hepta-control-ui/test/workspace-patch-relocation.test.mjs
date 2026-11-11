import test from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync,spawnSync} from 'node:child_process';
import {mkdtemp,mkdir,writeFile,readFile,cp,rm,realpath} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {relocateWorkspacePatches} from '../tools/prepare-makepad-platform.mjs';

test('Cargo resolves the original patch after the workspace moves into the build overlay',async()=>{
 const root=await mkdtemp(join(tmpdir(),'hepta-workspace-patch-'));
 try{
  const workspace=join(root,'source');
  const dependency=join(root,'repository-dep');
  const overlay=join(workspace,'target/robrix-build/workspace');
  await mkdir(join(workspace,'app/src'),{recursive:true});
  await mkdir(join(dependency,'src'),{recursive:true});
  await mkdir(overlay,{recursive:true});
  const manifest='[workspace]\nmembers = ["app"]\nresolver = "2"\n\n[patch.crates-io]\nfixture-patched-dep = { path = "../repository-dep" }\n';
  await writeFile(join(workspace,'Cargo.toml'),manifest);
  await writeFile(join(workspace,'app/Cargo.toml'),'[package]\nname = "fixture-overlay-app"\nversion = "1.0.0"\nedition = "2021"\n[dependencies]\nfixture-patched-dep = "1.0.0"\n');
  await writeFile(join(workspace,'app/src/lib.rs'),'');
  await writeFile(join(dependency,'Cargo.toml'),'[package]\nname = "fixture-patched-dep"\nversion = "1.0.0"\nedition = "2021"\n');
  await writeFile(join(dependency,'src/lib.rs'),'');
  await cp(join(workspace,'app'),join(overlay,'app'),{recursive:true});
  await writeFile(join(overlay,'Cargo.toml'),manifest);
  const args=['metadata','--offline','--format-version','1','--manifest-path',join(overlay,'Cargo.toml')];
  const old=spawnSync('cargo',args,{cwd:overlay,encoding:'utf8'});
  assert.notEqual(old.status,0,old.stdout);
  assert.match(old.stderr,/failed to load source for dependency/);
  await writeFile(join(overlay,'Cargo.toml'),relocateWorkspacePatches(manifest,workspace));
  const graph=JSON.parse(execFileSync('cargo',args,{cwd:overlay,encoding:'utf8',stdio:['ignore','pipe','pipe']}));
  const selected=graph.packages.find(entry=>entry.name==='fixture-patched-dep');
  assert.equal(await realpath(selected.manifest_path),await realpath(join(dependency,'Cargo.toml')));
  assert.equal(graph.packages.find(entry=>entry.name==='fixture-overlay-app').manifest_path,join(overlay,'app/Cargo.toml'));
  assert.equal(await readFile(join(workspace,'Cargo.toml'),'utf8'),manifest);
 }finally{await rm(root,{recursive:true,force:true});}
});
