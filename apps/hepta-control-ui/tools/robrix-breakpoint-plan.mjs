// Fixed source-bound layout contract for additional breakpoint coverage.
import assert from 'node:assert/strict';
export const breakpointWidths=Object.freeze([360,759,760,761]);
export const breakpointThemes=Object.freeze(['Aurora','Obsidian','Lunar']);
const sidebar={Aurora:248,Obsidian:300,Lunar:280};
export function headingRegion(viewport,theme){
 assert.ok(breakpointWidths.includes(viewport.width)&&viewport.height===800,'Only declared breakpoint viewports are accepted');
 assert.ok(Object.hasOwn(sidebar,theme),'Unknown theme');
 return viewport.width<760?{left:20,top:44,width:viewport.width-40,height:48}:{left:64+sidebar[theme],top:68,width:viewport.width-64-sidebar[theme],height:theme==='Obsidian'?76:80};
}
export function navigationRegion(viewport,theme){
 const heading=headingRegion(viewport,theme);
 return viewport.width<760?{left:0,top:92,width:viewport.width,height:52}:{left:heading.left,top:heading.top+heading.height,width:heading.width,height:44};
}
export function requireObservedPoint(point,region){
 const b=point.textBounds;
 assert.ok(b&&[b.left,b.top,b.width,b.height,point.x,point.y].every(Number.isFinite),'Observed OCR bounds required');
 assert.ok(b.width>0&&b.height>0&&b.left>=region.left&&b.top>=region.top&&b.left+b.width<=region.left+region.width&&b.top+b.height<=region.top+region.height,'Glyphs must be wholly inside the declared control region');
 assert.equal(point.x,b.left+b.width/2);assert.equal(point.y,b.top+b.height/2);return point;
}
