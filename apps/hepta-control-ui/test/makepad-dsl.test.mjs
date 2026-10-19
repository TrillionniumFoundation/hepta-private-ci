import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,symlink,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {validateImageFitReferences,verifyImageFitApi} from '../tools/check-makepad-dsl.mjs';

// Minimal parser fixtures, not a substitute for build-robrix's verified SDK.
const api='pub enum ImageFit {\n    Stretch,\n    Horizontal,\n    Vertical,\n    Smallest,\n    Biggest,\n    Size,\n    CropToFill,\n}\n';
async function withTree(run){
 const root=await mkdtemp(join(tmpdir(),'hepta-makepad-dsl-'));
 const source=join(root,'src'),sdk=join(root,'image_cache.rs');
 try{await mkdir(source);await writeFile(sdk,api);await run({root,source,sdk});}
 finally{await rm(root,{recursive:true,force:true});}
}
test('ImageFit parser validates each present SDK enum reference',()=>{
 assert.equal(validateImageFitReferences('fit: ImageFit.CropToFill\nfit: ImageFit.Stretch',api),2);
 assert.throws(()=>validateImageFitReferences('fit: ImageFit.CropToFill\nfit: ImageFit.Invented',api),/Unknown pinned Makepad ImageFit.Invented/);
});
test('ImageFit parser still requires a parsed SDK enum when the UI has no image',()=>{
 assert.equal(validateImageFitReferences('View {show_bg: true}',api),0);
 assert.throws(()=>validateImageFitReferences('View {}',''),/enum is unavailable/);
 assert.throws(()=>validateImageFitReferences('View {}','pub enum ImageFit {\n    // No parseable variants\n}\n'),/no parsed variants/);
});
test('nonempty Rust source without an ImageFit use is fully scanned',async()=>withTree(async({source,sdk})=>{
 await mkdir(join(source,'room'));
 await writeFile(join(source,'lib.rs'),'fn main() {}');
 await writeFile(join(source,'room','view.rs'),'fn draw_surface() {}');
 assert.deepEqual(await verifyImageFitApi(source,sdk),{files:2,references:0});
}));
test('nested Rust files remain checked after an earlier file has no ImageFit use',async()=>withTree(async({source,sdk})=>{
 await writeFile(join(source,'lib.rs'),'fn main() {}');
 await mkdir(join(source,'room'));
 const nested=join(source,'room','view.rs');
 await writeFile(nested,'fit: ImageFit.CropToFill');
 assert.deepEqual(await verifyImageFitApi(source,sdk),{files:2,references:1});
 await writeFile(nested,'fit: ImageFit.Invented');
 await assert.rejects(()=>verifyImageFitApi(source,sdk),/Unknown pinned Makepad ImageFit.Invented/);
}));
test('empty or non-Rust inventory cannot masquerade as a zero-reference scan',async()=>withTree(async({source,sdk})=>{
 await assert.rejects(()=>verifyImageFitApi(source,sdk),/contains no Rust files/);
 await writeFile(join(source,'README.md'),'No Rust files');
 await assert.rejects(()=>verifyImageFitApi(source,sdk),/contains no Rust files/);
}));
test('source with no ImageFit use still rejects an unavailable SDK declaration',async()=>withTree(async({source,sdk})=>{
 await writeFile(join(source,'lib.rs'),'fn main() {}');
 await writeFile(sdk,'pub struct NotImageFit;');
 await assert.rejects(()=>verifyImageFitApi(source,sdk),/enum is unavailable/);
}));
test('the scanner rejects symbolic-link source entries',async()=>withTree(async({root,source,sdk})=>{
 const target=join(root,'outside.rs');await writeFile(target,'fit: ImageFit.CropToFill');
 await symlink(target,join(source,'linked.rs'));
 await assert.rejects(()=>verifyImageFitApi(source,sdk),/must not be a symbolic link/);
}));
test('the source-file inventory remains bounded even with zero references',async()=>withTree(async({source,sdk})=>{
 for(let i=0;i<256;i++)await writeFile(join(source,`view_${i}.rs`),'fn draw_surface() {}');
 assert.deepEqual(await verifyImageFitApi(source,sdk),{files:256,references:0});
 await writeFile(join(source,'view_256.rs'),'fn draw_surface() {}');
 await assert.rejects(()=>verifyImageFitApi(source,sdk),/exceeds bound/);
}));
