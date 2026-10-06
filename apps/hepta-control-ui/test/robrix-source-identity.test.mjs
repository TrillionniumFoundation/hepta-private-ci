import test from 'node:test';
import assert from 'node:assert/strict';
import {cp,mkdtemp,mkdir,readFile,rm,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {dirname,join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {robrixSourceIdentity} from '../tools/robrix-source-identity.mjs';

const sourceRoot=fileURLToPath(new URL('..',import.meta.url));
const licenseDirectory='rust/robrix-ui/licenses';
const licensePath=`${licenseDirectory}/ROBRIX-MIT.txt`;
async function fixture(t){
 const root=await mkdtemp(join(tmpdir(),'hepta-source-identity-'));
 t.after(()=>rm(root,{recursive:true,force:true}));
 const source=await robrixSourceIdentity(sourceRoot);
 for(const path of Object.keys(source.files)){
  await mkdir(dirname(join(root,path)),{recursive:true});
  await writeFile(join(root,path),await readFile(join(sourceRoot,path)));
 }
 // Copy the actual packaging input independently of the identity's inventory.
 await cp(join(sourceRoot,licenseDirectory),join(root,licenseDirectory),{recursive:true});
 return root;
}

test('editing a shipped license invalidates source identity and restoring it recovers identity',async t=>{
 const root=await fixture(t);
 const before=await robrixSourceIdentity(root);
 const original=await readFile(join(root,licensePath));
 await writeFile(join(root,licensePath),Buffer.concat([original,Buffer.from('\nfixture change\n')]));
 const changed=await robrixSourceIdentity(root);
 assert.notEqual(changed.sha256,before.sha256);
 assert.notEqual(changed.files[licensePath],before.files[licensePath]);
 await writeFile(join(root,licensePath),original);
 assert.deepEqual(await robrixSourceIdentity(root),before);
});

test('adding and removing nested shipped licenses changes the complete source inventory',async t=>{
 const root=await fixture(t);
 const before=await robrixSourceIdentity(root);
 const added=`${licenseDirectory}/nested/NOTICE.txt`;
 await mkdir(dirname(join(root,added)),{recursive:true});
 await writeFile(join(root,added),'fixture notice\n');
 const changed=await robrixSourceIdentity(root);
 assert.notEqual(changed.sha256,before.sha256);
 assert.equal(typeof changed.files[added],'string');
 await rm(join(root,added));
 assert.deepEqual(await robrixSourceIdentity(root),before);
 await rm(join(root,licensePath));
 const removed=await robrixSourceIdentity(root);
 assert.notEqual(removed.sha256,before.sha256);
 assert.equal(Object.hasOwn(removed.files,licensePath),false);
});

test('missing shipped-license directory fails closed',async t=>{
 const root=await fixture(t);
 await rm(join(root,licenseDirectory),{recursive:true});
 await assert.rejects(robrixSourceIdentity(root),{code:'ENOENT'});
});
