import {createHash} from 'node:crypto';
import {readFile,readdir} from 'node:fs/promises';
import {join,relative} from 'node:path';
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
export async function robrixSourceIdentity(root){
 const files={};
 async function add(path){
  files[relative(root,path).replaceAll('\\','/')]=sha(await readFile(path));
 }
 async function walk(path){
  for(const entry of(await readdir(path,{withFileTypes:true})).sort((a,b)=>a.name.localeCompare(b.name))){
   const child=join(path,entry.name);if(entry.isDirectory())await walk(child);else await add(child);
  }
 }
 for(const name of ['Cargo.toml','Cargo.lock'])await add(join(root,'rust',name));
 for(const name of ['core','robrix-ui']){await add(join(root,'rust',name,'Cargo.toml'));await walk(join(root,'rust',name,'src'));}
 await walk(join(root,'rust/robrix-ui/patches'));
 await walk(join(root,'rust/robrix-ui/resources'));
 await add(join(root,'rust/robrix-ui/UPSTREAM.json'));
 await add(join(root,'rust/robrix-ui/build.rs'));
 for(const name of ['build.mjs','build-robrix.mjs','check-makepad-dsl.mjs','prepare-makepad-platform.mjs','emit-static-makepad-bridge.mjs','robrix-source-identity.mjs','prepare-fonts.py','run-desktop.py','run-product.py','owned-artifact-lease.mjs','artifact-lock.py','serve-robrix.mjs'])await add(join(root,'tools',name));
 return {sha256:sha(JSON.stringify(files)),files};
}
