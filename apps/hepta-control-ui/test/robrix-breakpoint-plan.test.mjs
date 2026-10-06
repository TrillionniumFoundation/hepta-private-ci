import test from 'node:test';
import assert from 'node:assert/strict';
import {headingRegion,navigationRegion,requireObservedPoint} from '../tools/robrix-breakpoint-plan.mjs';
test('layout switches at760 across themes and all declared widths stay within viewport',()=>{
 for(const theme of ['Aurora','Obsidian','Lunar']){
  assert.equal(headingRegion({width:759,height:800},theme).top,44);assert.equal(headingRegion({width:760,height:800},theme).top,68);
  for(const width of [360,759,760,761]){const r=navigationRegion({width,height:800},theme);assert.ok(r.left>=0&&r.width>0&&r.left+r.width<=width);}
 }
});
test('unsupported viewport, clipped glyphs, and invented click points fail closed',()=>{
 assert.throws(()=>headingRegion({width:360,height:900},'Aurora'));assert.throws(()=>headingRegion({width:500,height:800},'Aurora'));
 const region=navigationRegion({width:360,height:800},'Aurora');const p={x:80,y:112,textBounds:{left:60,top:102,width:40,height:20}};
 assert.equal(requireObservedPoint(p,region),p);
 for(const bad of [{...p,x:81},{...p,textBounds:{left:-1,top:102,width:40,height:20}},{...p,textBounds:{left:60,top:138,width:40,height:20}}])assert.throws(()=>requireObservedPoint(bad,region));
});
