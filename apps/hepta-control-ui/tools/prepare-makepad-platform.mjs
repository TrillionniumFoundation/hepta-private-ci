// Reproducible generated build overlay; never edits the Cargo Git cache.
import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {cp,mkdir,readFile,rm,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
export async function preparePlatform(workspace,makepadRoot,revision){
 const generated=join(workspace,'target/robrix-build');
 const platform=join(generated,'makepad-platform');
 const app=join(generated,'workspace');
 await mkdir(generated,{recursive:true});
 // These directories contain only our generated source copies, never user state.
 await rm(platform,{recursive:true,force:true});
 await cp(join(makepadRoot,'platform'),platform,{recursive:true});
 const patchRoot=join(workspace,'robrix-ui/patches');
 const identity=JSON.parse(await readFile(join(patchRoot,'makepad-wasm-clock.json'),'utf8'));
 const patch=join(patchRoot,'makepad-wasm-clock.patch');
 if(identity.upstream!==revision||sha(await readFile(patch))!==identity.patchSha256||sha(await readFile(join(platform,identity.path)))!==identity.beforeSha256) throw new Error('Unexpected platform patch inputs');
 execFileSync('patch',['--batch','--forward','--fuzz=0','-p1','-d',platform,'-i',patch],{stdio:'inherit'});
 if(sha(await readFile(join(platform,identity.path)))!==identity.afterSha256) throw new Error('Platform patch output mismatch');
 // The root platform crate's sibling path dependencies remain at the exact Git
 // revision, avoiding duplicate local copies of script/network/math types.
 let manifest=await readFile(join(platform,'Cargo.toml'),'utf8');
 let section='';
 manifest=manifest.split('\n').map(line=>{
  if(line.trim().startsWith('[')) section=line.trim();
  if(!section.includes('dependencies')) return line;
  return line.replace(/path\s*=\s*"[^"]+"/,line.includes('{')
    ? `git = "https://github.com/kevinaboos/makepad", rev = "${revision}"`
    : `git = "https://github.com/kevinaboos/makepad"\nrev = "${revision}"`);
 }).join('\n');
 manifest+='\n[workspace]\n';
 await writeFile(join(platform,'Cargo.toml'),manifest);
 // The no-thread font patch is isolated in the draw crate. Its native and
 // atomics-enabled worker path remains the upstream implementation.
 const draw=join(generated,'makepad-draw');
 await rm(draw,{recursive:true,force:true});
 await cp(join(makepadRoot,'draw'),draw,{recursive:true});
 const drawIdentity=JSON.parse(await readFile(join(patchRoot,'makepad-wasm-fonts.json'),'utf8'));
 const drawPatch=join(patchRoot,'makepad-wasm-fonts.patch');
 if(drawIdentity.upstream!==revision||sha(await readFile(drawPatch))!==drawIdentity.patchSha256) throw new Error('Unexpected draw patch identity');
 for(const file of drawIdentity.files) if(sha(await readFile(join(draw,file.path)))!==file.beforeSha256) throw new Error('Unexpected draw patch input: '+file.path);
 execFileSync('patch',['--batch','--forward','--fuzz=0','-p1','-d',draw,'-i',drawPatch],{stdio:'inherit'});
 for(const file of drawIdentity.files) if(sha(await readFile(join(draw,file.path)))!==file.afterSha256) throw new Error('Unexpected draw patch output: '+file.path);
 let drawManifest=await readFile(join(draw,'Cargo.toml'),'utf8');
 let drawSection='';
 drawManifest=drawManifest.split('\n').map(line=>{
  if(line.trim().startsWith('[')) drawSection=line.trim();
  if(!drawSection.includes('dependencies')) return line;
  return line.replace(/path\s*=\s*"[^"]+"/,`git = "https://github.com/kevinaboos/makepad", rev = "${revision}"`);
 }).join('\n')+'\n[workspace]\n';
 await writeFile(join(draw,'Cargo.toml'),drawManifest);
 await mkdir(app,{recursive:true});
 for(const name of ['core','web','robrix-ui']) {await rm(join(app,name),{recursive:true,force:true});await cp(join(workspace,name),join(app,name),{recursive:true});}
 await cp(join(workspace,'Cargo.lock'),join(app,'Cargo.lock'));
 const sourceManifest=await readFile(join(workspace,'Cargo.toml'),'utf8');
 await writeFile(join(app,'Cargo.toml'),sourceManifest+'\n[patch."https://github.com/kevinaboos/makepad"]\nmakepad-platform = { path = "../makepad-platform" }\nmakepad-draw = { path = "../makepad-draw" }\n');
 return {workspace:app,identity,drawIdentity,platformManifestSha256:sha(manifest),drawManifestSha256:sha(drawManifest)};
}
