// Required after the ordinary build: exercise actual packaged SDK bytes.
// This qualifies extraction and rejection behavior, not network completion.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFile} from 'node:fs/promises';
import {Script} from 'node:vm';
import {extractHttpBoundaryMethods} from '../tools/http-boundary-sdk.mjs';

const asset=await readFile(new URL('../dist/makepad_platform/web.js',import.meta.url));
const manifest=JSON.parse(await readFile(new URL('../dist/build-manifest.json',import.meta.url),'utf8'));
const source=asset.toString('utf8');
const methods=extractHttpBoundaryMethods(asset,manifest);
const digest=value=>createHash('sha256').update(value).digest('hex');
function withAsset(value){
 const bytes=Buffer.from(value),changed=structuredClone(manifest);
 changed.files['makepad_platform/web.js']={bytes:bytes.length,sha256:digest(bytes)};
 return [bytes,changed];
}

test('shipping minified methods extract intact and form the same transport host',()=>{
 const network=new Script(`class PinnedNetwork {\n${methods}\n}; PinnedNetwork`).runInNewContext();
 assert.deepEqual(Object.getOwnPropertyNames(network.prototype),[
  'constructor','network_http_dispatch','network_http_finish','js_network_http_cancel',
 ]);
 assert.equal(source.slice(source.indexOf('\nnetwork_http_dispatch(entry){\n')+1,
  source.indexOf('\njs_network_ws_open(')),methods,'do not normalize or replace the shipping bytes');
});

test('fixture, unreviewed revision, and stale SDK manifest are rejected',()=>{
 const fixtures=structuredClone(manifest);fixtures.fixtures=true;
 assert.throws(()=>extractHttpBoundaryMethods(asset,fixtures),/ordinary product build/);
 const revision=structuredClone(manifest);revision.packagerSource='unreviewed';
 assert.throws(()=>extractHttpBoundaryMethods(asset,revision),/Unreviewed SDK revision/);
 const stale=structuredClone(manifest);stale.files['makepad_platform/web.js'].bytes+=1;
 assert.throws(()=>extractHttpBoundaryMethods(asset,stale),/does not match the built manifest/);
 assert.throws(()=>extractHttpBoundaryMethods(Buffer.concat([asset,Buffer.from('\n')]),manifest),/does not match the built manifest/);
});

test('missing duplicate and reordered method boundaries fail before execution',()=>{
 const cancel='\njs_network_http_cancel(request_id_lo,request_id_hi){\n';
 const finish='\nnetwork_http_finish(entry){\n';
 for(const changed of [source.replace(cancel,'\nmissing_cancel(){\n'),source+cancel,
  source.replace(cancel,'\n__swap__\n').replace(finish,cancel).replace('\n__swap__\n',finish)]){
  assert.throws(()=>extractHttpBoundaryMethods(...withAsset(changed)),/SDK method boundary changed/);
 }
});

test('nested closures cannot truncate cancellation or bypass the reviewed reader hash',()=>{
 for(const changed of [
  source.replace('entry.controller.abort();\nthis.network_http_requests.delete(request_key);','this.network_http_requests.delete(request_key);'),
  source.replace('response_body_len>entry.max_body','response_body_len>Infinity'),
  source.replace('},20000);','},2000);'),
 ]){
  assert.notEqual(changed,source,'mutation must reach the real SDK method');
  assert.throws(()=>extractHttpBoundaryMethods(...withAsset(changed)),/Shipping SDK reader changed/);
 }
});
