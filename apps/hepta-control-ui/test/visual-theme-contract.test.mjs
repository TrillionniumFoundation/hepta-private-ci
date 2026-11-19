// Numerical source-token checks, not rendered-pixel or platform accessibility qualification.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source=await readFile(new URL('../rust/robrix-ui/src/visual_theme.rs',import.meta.url),'utf8');
function luminance(value){
 const channels=[24,16,8].map(shift=>((value>>>shift)&255)/255).map(c=>c<=0.04045?c/12.92:((c+0.055)/1.055)**2.4);
 return channels[0]*0.2126+channels[1]*0.7152+channels[2]*0.0722;
}
function contrast(a,b){const x=luminance(a),y=luminance(b);return (Math.max(x,y)+0.05)/(Math.min(x,y)+0.05);}
for(const name of ['ObsidianIce','LunarTitanium','AuroraGraphite'])test(`${name} source text tokens preserve readable contrast`,()=>{
 const match=source.match(new RegExp(`Self::${name} => \\[([^\\]]+)\\]`));assert.ok(match);
 const values=[...match[1].matchAll(/0x([0-9a-f]{8})/g)].map(m=>Number.parseInt(m[1],16));assert.equal(values.length,9);
 const [canvas,panel,surface,text,muted,accent,border,selected]=values;
 for(const background of [canvas,panel,surface,selected])for(const foreground of [text,muted])assert.ok(contrast(foreground,background)>=4.5,`${name} text contrast ${contrast(foreground,background)}`);
 if(name==='LunarTitanium')for(const background of [canvas,panel,surface]){
  assert.ok(contrast(border,background)>=3,'Lunar boundary contrast');
  assert.ok(contrast(accent,background)>=3,'Lunar focus indicator contrast');
 }
});
test('unavailable Send retains disabled owner boundary and a separate lock glyph',async()=>{
 const composer=await readFile(new URL('../rust/robrix-ui/src/robrix/composer.rs',import.meta.url),'utf8');
 const styles=await readFile(new URL('../rust/robrix-ui/src/robrix/styles.rs',import.meta.url),'utf8');
 assert.match(composer,/send_message_button := mod.widgets.SendButton \{\s*enabled: false/);
 const send=styles.split('mod.widgets.SendButton =')[1].split('mod.widgets.HeptaMark =')[0];
 assert.match(send,/if self.disabled > 0.5/);assert.match(send,/return sdf.result/);
 assert.match(send,/mix\(self.accent, self.color_disabled, self.disabled\)/);
});

test('shared preview serves the added CFF fonts with an explicit OTF content type',async()=>{
 const server=await readFile(new URL('../tools/serve-robrix.mjs',import.meta.url),'utf8');
 assert.match(server,/\'.otf\':\'font\/otf\'/);
});
