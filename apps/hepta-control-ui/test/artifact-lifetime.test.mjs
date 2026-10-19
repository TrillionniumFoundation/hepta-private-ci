import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,readFile,rm,rename,symlink,readdir} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {spawn,spawnSync} from 'node:child_process';
import {withStagedArtifact,recoverArtifact,loadArtifactSnapshot} from '../tools/owned-artifact-lease.mjs';
const helper=new URL('../tools/owned-artifact-lease.mjs',import.meta.url).href;
const runner=fileURLToPath(new URL('../tools/artifact-lock.py',import.meta.url));
const sha=b=>createHash('sha256').update(b).digest('hex');
async function fixture(t){const root=await mkdtemp(join(tmpdir(),'hepta-artifact-'));t.after(()=>rm(root,{recursive:true,force:true}));return root;}
async function artifact(path,text,extra={}){await mkdir(path,{recursive:true});const files={'index.html':text,...extra};const pins={};for(const [name,body] of Object.entries(files)){await writeFile(join(path,name),body);pins[name]={bytes:Buffer.byteLength(body),sha256:sha(body)};}const manifest=JSON.stringify({schema:'hepta.robrix-ui.build.v1',browserRuntime:'rust-makepad-wasm',sourceIdentity:{sha256:'a'.repeat(64)},files:pins});await writeFile(join(path,'build-manifest.json'),manifest);return sha(manifest);}
const locked=(root,script)=>spawnSync('python3',[runner,root,process.execPath,'--input-type=module','-e',script],{encoding:'utf8',timeout:5000});
async function waitFor(check){const end=Date.now()+5000;while(Date.now()<end){try{if(await check())return;}catch{}await new Promise(r=>setTimeout(r,20));}throw new Error('Process fixture timed out');}

test('kernel lock survives killed parent and child, then releases after final grandchild',{skip:process.platform==='win32',timeout:12000},async t=>{
 const root=await fixture(t);
 const grand=`require('fs').writeFileSync(${JSON.stringify(join(root,'grand.pid'))},String(process.pid));setInterval(()=>{},1000)`;
 const child=`import {execOwned} from ${JSON.stringify(helper)};import{writeFileSync}from'node:fs';writeFileSync(${JSON.stringify(join(root,'child.pid'))},String(process.pid));execOwned(process.execPath,['-e',${JSON.stringify(grand)}],{stdio:'inherit'});`;
 const script=`import{withArtifactLease,execOwned}from ${JSON.stringify(helper)};await withArtifactLease(${JSON.stringify(root)},'build',async()=>execOwned(process.execPath,['--input-type=module','-e',${JSON.stringify(child)}],{stdio:'inherit'}));`;
 const worker=spawn('python3',[runner,root,process.execPath,'--input-type=module','-e',script],{stdio:'ignore'});
 const pids=[worker.pid];t.after(()=>{for(const pid of pids)try{process.kill(pid,'SIGKILL');}catch{}});
 await waitFor(async()=>Boolean(await readFile(join(root,'grand.pid'),'utf8')));
 pids.push(Number(await readFile(join(root,'child.pid'),'utf8')),Number(await readFile(join(root,'grand.pid'),'utf8')));
 process.kill(pids[0],'SIGKILL');process.kill(pids[1],'SIGKILL');
 assert.notEqual(locked(root,'').status,0);
 process.kill(pids[2],'SIGKILL');
 await waitFor(()=>locked(root,'').status===0);
});

test('SIGINT, SIGTERM and startup exceptions release the kernel lock',{skip:process.platform==='win32',timeout:12000},async t=>{
 const root=await fixture(t);
 for(const signal of ['SIGINT','SIGTERM']){
  const marker=join(root,signal);
  const script=`import{withArtifactLease}from ${JSON.stringify(helper)};import{writeFileSync}from'node:fs';await withArtifactLease(${JSON.stringify(root)},'build',async()=>{writeFileSync(${JSON.stringify(marker)},'ready');await new Promise(()=>setInterval(()=>{},1000));});`;
  const worker=spawn('python3',[runner,root,process.execPath,'--input-type=module','-e',script],{stdio:'ignore'});
  t.after(()=>{try{worker.kill('SIGKILL');}catch{}});
  await waitFor(()=>readFile(marker));worker.kill(signal);await waitFor(()=>locked(root,'').status===0);
 }
 const failed=locked(root,`import{withArtifactLease}from ${JSON.stringify(helper)};await withArtifactLease(${JSON.stringify(root)},'preview',async()=>{throw Error('startup');});`);
 assert.notEqual(failed.status,0);assert.equal(locked(root,'').status,0);
});

test('verified snapshot survives replacement and does not retain a preview lock',async t=>{
 const root=await fixture(t);await artifact(join(root,'dist'),'old');
 const script=`import{withArtifactLease,loadArtifactSnapshot}from ${JSON.stringify(helper)};const snapshot=await withArtifactLease(${JSON.stringify(root)},'preview',()=>loadArtifactSnapshot(${JSON.stringify(join(root,'dist'))}));console.log(snapshot.buffers.get('index.html').toString());`;
 assert.equal(locked(root,script).stdout.trim(),'old');assert.equal(locked(root,'').status,0);
 const snapshot=await loadArtifactSnapshot(join(root,'dist'));
 await withStagedArtifact({root},'dist',stage=>artifact(stage,'new'));
 assert.equal(snapshot.buffers.get('index.html').toString(),'old');assert.equal((await loadArtifactSnapshot(join(root,'dist'))).buffers.get('index.html').toString(),'new');
});

test('failed verification and journal initialization preserve the previous artifact',async t=>{
 const root=await fixture(t);const old=await artifact(join(root,'dist'),'old');
 await assert.rejects(withStagedArtifact({root},'dist',async()=>{throw Object.assign(Error('disk full'),{code:'ENOSPC'});}),/disk full/);
 await mkdir(join(root,'.robrix-dist.journal.json'));
 await assert.rejects(withStagedArtifact({root},'dist',stage=>artifact(stage,'new')));
 assert.equal((await loadArtifactSnapshot(join(root,'dist'))).manifestDigest,old);
 assert.deepEqual((await readdir(root)).sort(),['.robrix-dist.journal.json','dist']);
});

test('publication removes resources deleted from a reused package',async t=>{
 const root=await fixture(t);await artifact(join(root,'dist'),'old',{'removed.png':'archive'});
 await withStagedArtifact({root},'dist',stage=>artifact(stage,'new'));
 assert.deepEqual((await readdir(join(root,'dist'))).sort(),['build-manifest.json','index.html']);
});

for(const crash of ['prepared','old-moved','new-moved'])test(`SIGKILL ${crash} recovers pinned complete version`,{skip:process.platform==='win32'},async t=>{
 const root=await fixture(t);const stage='.robrix-artifact-stage-Test123';const previous='.robrix-artifact-previous-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';
 const old=await artifact(join(root,'dist'),'old'),next=await artifact(join(root,stage),'new');
 const record={version:1,name:'dist',stage,previous,next,previousDigest:old};
 const script=`import{open,rename}from'node:fs/promises';const f=await open(${JSON.stringify(join(root,'.robrix-dist.journal.json'))},'wx');await f.writeFile(${JSON.stringify(JSON.stringify(record))});await f.sync();await f.close();${crash!=='prepared'?`await rename(${JSON.stringify(join(root,'dist'))},${JSON.stringify(join(root,previous))});`:''}${crash==='new-moved'?`await rename(${JSON.stringify(join(root,stage))},${JSON.stringify(join(root,'dist'))});`:''}process.kill(process.pid,'SIGKILL');`;
 assert.equal(locked(root,script).signal,'SIGKILL');
 await recoverArtifact({root},'dist');
 assert.equal((await loadArtifactSnapshot(join(root,'dist'))).manifestDigest,next);
 assert.deepEqual((await readdir(root)).sort(),['.robrix-artifact.lock','dist']);
});

test('tampered journal, retained digest mismatch and symlink are fail-closed',async t=>{
 const root=await fixture(t);const old=await artifact(join(root,'dist'),'old');
 const path=join(root,'.robrix-dist.journal.json');await writeFile(path,JSON.stringify({stage:'../../escape'}));
 await assert.rejects(recoverArtifact({root},'dist'),/Unknown publication/);
 await rm(path);const stage='.robrix-artifact-stage-Test123';await artifact(join(root,stage),'new');
 await writeFile(path,JSON.stringify({version:1,name:'dist',stage,previous:'.robrix-artifact-previous-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',next:'b'.repeat(64),previousDigest:old}));
 await assert.rejects(recoverArtifact({root},'dist'),/does not match/);
 assert.equal((await loadArtifactSnapshot(join(root,'dist'))).manifestDigest,old);
 await rm(path);await rename(join(root,'dist'),join(root,'actual'));await symlink('actual',join(root,'dist'));
 await assert.rejects(withStagedArtifact({root},'dist',p=>artifact(p,'new')),/regular directory/);
 assert.equal((await loadArtifactSnapshot(join(root,'actual'))).manifestDigest,old);
});


test('real journal write failure under a file-size limit keeps prior output and releases ownership',{skip:process.platform==='win32'},async t=>{
 const root=await fixture(t);const old=await artifact(join(root,'dist'),'old');await artifact(join(root,'prepared'),'new');
 const script=`import{withArtifactLease,withStagedArtifact}from ${JSON.stringify(helper)};import{rm,rename}from'node:fs/promises';await withArtifactLease(${JSON.stringify(root)},'build',lease=>withStagedArtifact(lease,'dist',async stage=>{await rm(stage,{recursive:true});await rename(${JSON.stringify(join(root,'prepared'))},stage);}));`;
 const python="import resource,signal,os,sys; resource.setrlimit(resource.RLIMIT_FSIZE,(0,0)); signal.signal(signal.SIGXFSZ,signal.SIG_IGN); os.execvp(sys.argv[1],sys.argv[1:])";
 const result=spawnSync('python3',['-c',python,'python3',runner,root,process.execPath,'--input-type=module','-e',script],{encoding:'utf8',timeout:5000});
 assert.notEqual(result.status,0);assert.match(result.stderr,/EFBIG/);
 assert.equal((await loadArtifactSnapshot(join(root,'dist'))).manifestDigest,old);
 assert.equal(locked(root,'').status,0);
 assert.deepEqual((await readdir(root)).sort(),['.robrix-artifact.lock','dist']);
});

test('ordinary Node wrapper forwards termination without retaining a preview process',{skip:process.platform==='win32',timeout:10000},async t=>{
 const root=await fixture(t),marker=join(root,'ready'),entry=join(root,'entry.mjs');
 await writeFile(entry,`import{withArtifactLease}from ${JSON.stringify(helper)};import{writeFileSync}from'node:fs';await withArtifactLease(${JSON.stringify(root)},'preview',async()=>{writeFileSync(${JSON.stringify(marker)},String(process.pid));await new Promise(()=>setInterval(()=>{},1000));});`);
 const outer=spawn(process.execPath,[entry],{stdio:'ignore'});let inner;
 t.after(()=>{for(const pid of [outer.pid,inner])if(pid)try{process.kill(pid,'SIGKILL');}catch{}});
 await waitFor(async()=>{inner=Number(await readFile(marker,'utf8'));return inner;});
 outer.kill('SIGTERM');await waitFor(()=>locked(root,'').status===0);
 await waitFor(()=>{try{process.kill(inner,0);return false;}catch{return true;}});
});

test('two live previews keep immutable bytes while a rebuild publishes new output',{skip:process.platform==='win32',timeout:10000},async t=>{
 const root=await fixture(t);await artifact(join(root,'dist'),'old');const servers=[];
 t.after(()=>{for(const server of servers)server.kill('SIGTERM');});
 for(let i=0;i<2;i++){
  const marker=join(root,`preview-${i}`);
  const script=`import{withArtifactLease,loadArtifactSnapshot}from ${JSON.stringify(helper)};import{createServer}from'node:http';import{writeFileSync}from'node:fs';const snapshot=await withArtifactLease(${JSON.stringify(root)},'preview',()=>loadArtifactSnapshot(${JSON.stringify(join(root,'dist'))}));const server=createServer((req,res)=>res.end(snapshot.buffers.get('index.html')));server.listen(0,'127.0.0.1',()=>writeFileSync(${JSON.stringify(marker)},String(server.address().port)));`;
  servers.push(spawn('python3',[runner,root,process.execPath,'--input-type=module','-e',script],{stdio:'ignore'}));
  await waitFor(()=>readFile(marker));
 }
 const rebuild=locked(root,`import{withArtifactLease}from ${JSON.stringify(helper)};await withArtifactLease(${JSON.stringify(root)},'build',async()=>{});`);
 assert.equal(rebuild.status,0,rebuild.stderr);
 await withStagedArtifact({root},'dist',p=>artifact(p,'new'));
 for(let i=0;i<2;i++){const port=Number(await readFile(join(root,`preview-${i}`),'utf8'));assert.equal(await(await fetch(`http://127.0.0.1:${port}`)).text(),'old');}
 assert.equal((await loadArtifactSnapshot(join(root,'dist'))).buffers.get('index.html').toString(),'new');
});

test('real Rust Command descendant retains the compiler lock after both parents die',{skip:process.platform==='win32',timeout:30000},async t=>{
 const root=await fixture(t),source=join(root,'child.rs'),binary=join(root,'child');
 await writeFile(source,`fn main(){let a:Vec<String>=std::env::args().collect();std::fs::write(&a[1],std::process::id().to_string()).unwrap();let status=std::process::Command::new(&a[2]).args(&a[3..]).status().unwrap();std::process::exit(status.code().unwrap_or(1));}`);
 const compile=spawnSync('rustup',['run','1.95.0','rustc','--edition=2024',source,'-o',binary],{encoding:'utf8',timeout:20000});
 assert.equal(compile.status,0,compile.stderr??String(compile.error));
 for(const mode of ['parent-sigkill','wrapper-sigterm']){
 const marker=join(root,mode+'.pid'),rustMarker=join(root,mode+'-rust.pid');
 const grand=`require('fs').writeFileSync(${JSON.stringify(marker)},String(process.pid));setInterval(()=>{},1000)`;
 const script=`import{withArtifactLease,execOwned}from ${JSON.stringify(helper)};await withArtifactLease(${JSON.stringify(root)},'build',async()=>execOwned(${JSON.stringify(binary)},[${JSON.stringify(rustMarker)},process.execPath,'-e',${JSON.stringify(grand)}],{stdio:'inherit'}));`;
 const entry=join(root,mode+'.mjs');await writeFile(entry,script);
 const worker=mode==='parent-sigkill'?spawn('python3',[runner,root,process.execPath,entry],{stdio:'ignore'}):spawn(process.execPath,[entry],{stdio:'ignore'});
 const pids=[worker.pid];t.after(()=>{for(const pid of pids)try{process.kill(pid,'SIGKILL');}catch{}});
 await waitFor(()=>readFile(marker));
 pids.push(Number(await readFile(rustMarker,'utf8')),Number(await readFile(marker,'utf8')));
 process.kill(pids[0],mode==='parent-sigkill'?'SIGKILL':'SIGTERM');
 assert.notEqual(locked(root,'').status,0);
 process.kill(pids[1],'SIGKILL');assert.notEqual(locked(root,'').status,0);
 process.kill(pids[2],'SIGKILL');await waitFor(()=>locked(root,'').status===0);
 }

});
