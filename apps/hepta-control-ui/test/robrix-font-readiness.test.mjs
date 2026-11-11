import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {sharedFontFamilyReady} from '../tools/robrix-font-readiness.mjs';
const ready='robrix-ui/src/robrix/room.rs:585:28 - HEPTA_FIXTURE_FONT_STATE index=59 loaded_fonts=4 complete=true members=["latin", "cjk", "rare", "emoji"]';
test('all four actual shared font members must finish loading',()=>{
 assert.equal(sharedFontFamilyReady(ready),true);
 for(const value of [ready.replace('loaded_fonts=4','loaded_fonts=3'),ready.replace('complete=true','complete=false'),ready.replace(', "rare"',''),ready.replace('"rare"','"unknown"'),ready.replace('"rare", "emoji"','"emoji", "rare"'),ready+' trailing',null,'x'.repeat(8193)])assert.equal(sharedFontFamilyReady(value),false);
});
test('both Rust font families retain exact Latin/SC/rare/emoji order',async()=>{
 const styles=await readFile(new URL('../rust/robrix-ui/src/robrix/styles.rs',import.meta.url),'utf8');
 for(const name of ['HEPTA_REGULAR','HEPTA_BOLD']){
  const family=styles.split('mod.widgets.'+name+' =')[1].split('\n }')[0];
  assert.deepEqual([...family.matchAll(/(\w+) := FontMember/g)].map(m=>m[1]),['latin','cjk','rare','emoji']);
 }
});
