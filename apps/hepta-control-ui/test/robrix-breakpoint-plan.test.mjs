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
import {consoleRegion,themeTextRegion,requireThemeText,requireAuthorityWarning} from '../tools/robrix-breakpoint-plan.mjs';
test('all complete theme words are mandatory and wrong or truncated themes fail',()=>{
 requireThemeText('Obsidian Ice','Obsidian');requireThemeText('LunarTitanium }','Lunar');
 for(const value of ['Lunar','Lunar Titani','Aurora Graphite'])assert.throws(()=>requireThemeText(value,'Lunar'));
});
test('authority words stay exact while visible OCR punctuation is retained separately',()=>{
 const text='These observations do not provide current write authority. Chat and operation commands remain unavailable.';
 assert.deepEqual(requireAuthorityWarning(text),{fullWarningWords:true,observedClausePunctuation:'.',observedTerminalPunctuation:'.'});
 assert.equal(requireAuthorityWarning(text.slice(0,-1)+',').observedTerminalPunctuation,',');
 for(const missing of ['not ','current ','write ','Chat and ','operation ','unavailable'])assert.throws(()=>requireAuthorityWarning(text.replace(missing,'')));
 assert.throws(()=>requireAuthorityWarning('No current status is shown. Chat and operation commands remain unavailable.'));
});
test('fixed source regions stay within the exact reviewed viewports',()=>{
 assert.equal(consoleRegion({width:360,height:800},'Aurora').top,190);
 assert.equal(consoleRegion({width:760,height:800},'Aurora').left,312);
 const point={x:322,y:118,textBounds:{left:301,top:112,width:42,height:12}};
 assert.deepEqual(themeTextRegion({width:759,height:800},point),{left:297,top:108,width:140,height:20});
 assert.throws(()=>themeTextRegion({width:760,height:800},point));
});
import {observationHeadingRegion,requireObservationHeading} from '../tools/robrix-breakpoint-plan.mjs';
test('observation heading has a separate fixed source line and cannot be shortened',()=>{
 assert.deepEqual(observationHeadingRegion({width:759,height:800},'Lunar'),{left:16,top:160,width:727,height:56});
 requireObservationHeading('Runtime observations\n');
 for(const text of ['Runtime','observations','Runtime observation','Runtime observations incomplete'])assert.throws(()=>requireObservationHeading(text));
});
