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
export function consoleRegion(viewport,theme){
 const navigation=navigationRegion(viewport,theme);
 // The360px compact row wraps its fourth(theme)button onto a second40px row,
 // with6px spacing. All declared wider compact subjects keep one row.
 const top=viewport.width===360?190:navigation.top+navigation.height;
 return{left:navigation.left,top,width:navigation.width,height:viewport.height-top};
}
export function themeTextRegion(viewport,point){
 assert.equal(viewport.width,759,'Theme selection is observed before target resizing');
 requireObservedPoint(point,{left:0,top:92,width:759,height:104});
 const b=point.textBounds;const region={left:b.left-4,top:b.top-4,width:140,height:b.height+8};
 assert.ok(region.left>=0&&region.top>=92&&region.left+region.width<=viewport.width&&region.top+region.height<=196,'Theme line crop must fit its observed control band');return region;
}
export function requireThemeText(text,theme){
 const labels={Aurora:'Aurora\\s*Graphite',Obsidian:'Obsidian\\s*Ice',Lunar:'Lunar\\s*Titanium'};
 assert.ok(Object.hasOwn(labels,theme));assert.match(text,new RegExp('\\b'+labels[theme]+'\\b','i'),'Complete selected theme words must be present');
}
export function requireAuthorityWarning(text){
 const words=text.replace(/\s+/g,' ');
 const match=words.match(/\bThese observations do not provide current write authority([.,]?)\s+Chat and operation commands remain unavailable([.,]?)(?=\s|$)/i);
 assert.ok(match,'Complete authority warning words must remain readable');
 // Semantic content is exact; OCR punctuation is retained separately for visual review.
 return{fullWarningWords:true,observedClausePunctuation:match[1],observedTerminalPunctuation:match[2]};
}
