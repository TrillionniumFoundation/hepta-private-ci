// Build-time API checking for dynamic Makepad DSL enum references. Rust's
// compiler validates the macro tokens but does not resolve these script names.
import {readFile,readdir} from 'node:fs/promises';
import {join} from 'node:path';

export function validateImageFitReferences(source,apiSource){
 const body=apiSource.match(/pub enum ImageFit\s*\{([\s\S]*?)\n\}/)?.[1];
 if(!body)throw new Error('Pinned SDK ImageFit enum is unavailable');
 const variants=new Set([...body.matchAll(/^\s*([A-Z]\w*)\s*,\s*$/gm)].map(match=>match[1]));
 if(!variants.size)throw new Error('Pinned SDK ImageFit enum has no parsed variants');
 const references=[...source.matchAll(/\bImageFit\.([A-Za-z_]\w*)/g)].map(match=>match[1]);
 for(const name of references)if(!variants.has(name))throw new Error(`Unknown pinned Makepad ImageFit.${name}`);
 return references.length;
}

export async function verifyImageFitApi(sourceDirectory,apiPath){
 const apiSource=await readFile(apiPath,'utf8');let references=0,files=0;
 async function walk(directory){
  for(const entry of await readdir(directory,{withFileTypes:true})){
   const path=join(directory,entry.name);
   if(entry.isSymbolicLink())throw new Error('UI DSL source must not be a symbolic link');
   if(entry.isDirectory())await walk(path);
   else if(entry.isFile()&&entry.name.endsWith('.rs')){
    if(++files>256)throw new Error('UI DSL source inventory exceeds bound');
    references+=validateImageFitReferences(await readFile(path,'utf8'),apiSource);
   }
  }
 }
 await walk(sourceDirectory);
 if(!references)throw new Error('Expected live ImageFit reference was not checked');
 return{files,references};
}
