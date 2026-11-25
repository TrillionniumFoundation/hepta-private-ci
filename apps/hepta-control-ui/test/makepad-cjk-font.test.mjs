// Executes both pinned CJK faces through actual Makepad parsing/shaping/outlines.
// CPU glyph rasterization is not GPU or multilingual layout qualification.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile,readdir,writeFile,mkdir,mkdtemp,rm} from 'node:fs/promises';
import {dirname,join} from 'node:path';
import {tmpdir} from 'node:os';
import {fileURLToPath} from 'node:url';
import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {robrixSourceIdentity} from '../tools/robrix-source-identity.mjs';
const root=fileURLToPath(new URL('..',import.meta.url));
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
async function filesBelow(path){
 const files=[];
 for(const item of await readdir(path,{withFileTypes:true})){
  const child=join(path,item.name);
  if(item.isDirectory())files.push(...await filesBelow(child));
  else if(item.isFile())files.push(child);
 }
 return files;
}
test('pinned SC fonts parse, shape and rasterize with the actual Makepad SDK',async t=>{
 const target=join(root,'rust/target/robrix-build/workspace/target');
 const files=await filesBelow(target);
 const dirs=[...new Set(files.filter(f=>/\.(rmeta|so|dylib|dll)$/.test(f)).map(dirname))];
 const manifestBytes=await readFile(join(root,'dist/build-manifest.json'));
 const manifest=JSON.parse(manifestBytes);
 const upstream=JSON.parse(await readFile(join(root,'rust/robrix-ui/UPSTREAM.json'),'utf8'));
 assert.equal(manifest.packagerSource,upstream.makepad.revision);
 const sourceIdentity=await robrixSourceIdentity(root);
 const sourceIdentityCurrent=sourceIdentity.sha256===manifest.sourceIdentity.sha256;
 if(process.env.GITHUB_ACTIONS==='true')assert.equal(sourceIdentityCurrent,true,'CI probe requires current candidate build');
 const compiler=execFileSync('rustup',['run','nightly-2026-10-02','rustc','--version'],{encoding:'utf8'}).trim();
 assert.equal(compiler,manifest.nightly);
 const fonts=JSON.parse(execFileSync('python3',[join(root,'tools/prepare-fonts.py'),'--offline'],{encoding:'utf8'}));
 const fontDirectory=dirname(fonts.assets[0].inputPath);
 for(const asset of fonts.assets)assert.equal(sha(await readFile(asset.inputPath)),asset.sha256);
 const temporary=await mkdtemp(join(tmpdir(),'hepta-cjk-font-'));
 t.after(()=>rm(temporary,{recursive:true,force:true}));
 const source=join(root,'test/fixtures/cjk-font-probe.rs');
 const wasm=join(temporary,'probe.wasm');
 const args=['-Zunstable-options','--edition=2024','--crate-type=cdylib','--target',join(target,'makepad-wasm-target/single/wasm32-unknown-unknown.json'),'-C','panic=abort',source,'-o',wasm];
 const artifactHashes={};
 for(const name of ['makepad_widgets','rustybuzz','std']){
  const matches=files.filter(f=>f.includes('wasm32-unknown-unknown')&&new RegExp('/lib'+name+'-[^/]+\\.rmeta$').test(f));
  assert.equal(matches.length,1,'Require one exact '+name+' artifact');
  for(const file of [matches[0],matches[0].replace(/\.rmeta$/,'.rlib')]){
   args.push('--extern',name+'='+file);artifactHashes[file]=sha(await readFile(file));
  }
 }
 for(const dir of dirs)args.push('-L','dependency='+dir);
 execFileSync('rustup',['run','nightly-2026-10-02','rustc',...args],{stdio:'pipe',timeout:120000,env:{...process.env,CARGO_MANIFEST_DIR:dirname(source),HEPTA_CJK_FONT_DIR:fontDirectory}});
 const bytes=await readFile(wasm),module=await WebAssembly.compile(bytes),env={};
 for(const entry of WebAssembly.Module.imports(module)){
  assert.equal(entry.module,'env');assert.equal(entry.kind,'function');
  env[entry.name]=entry.name==='js_monotonic_now'?()=>performance.now()/1000
   :entry.name==='js_time_now'?()=>Date.now()/1000
   :['js_console_log','js_wake_ui'].includes(entry.name)?()=>{}
   :()=>{throw Error('Unexpected probe import: '+entry.name);};
 }
 const results=[];
 const cases={check_fonts:48};
 for(const [name,expected] of Object.entries(cases)){
  const {exports}=await WebAssembly.instantiate(module,{env});
  let count;
  try{count=exports[name]();}catch(error){throw Error(`${name}: SDK font probe failed`,{cause:error});}
  assert.equal(count,expected);results.push({name,count,passed:true});
 }
 const sourceFiles={};
 for(const path of ['test/fixtures/cjk-font-probe.rs','rust/robrix-ui/resources/fonts/MANIFEST.json','rust/robrix-ui/resources/fonts/OFL.txt'])sourceFiles[path]=sha(await readFile(join(root,path)));
 const receipt={schema:'hepta.cjk-font-probe.v1',scope:'actual SDK CFF parsing/shaping/outlines/CPU rasterization only; no GPU/layout qualification',appQualified:false,sourceIdentityCurrent,sourceIdentity:sourceIdentity.sha256,producerManifestSha256:sha(manifestBytes),sdkRevision:upstream.makepad.revision,compiler,fontAssets:fonts.assets.map(({inputPath,...asset})=>asset),sourceFiles,artifactHashes,probeWasmSha256:sha(bytes),results};
 await mkdir(join(root,'test-results'),{recursive:true});
 await writeFile(join(root,'test-results/robrix-cjk-font-results.json'),JSON.stringify(receipt,null,2)+'\n');
});
