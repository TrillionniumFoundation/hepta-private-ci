// Bounded diagnostic helpers; they do not add application keyboard behavior.
import assert from 'node:assert/strict';
export function observedControl(point,region){
 const b=point.textBounds;assert.ok(b&&[b.left,b.top,b.width,b.height,point.x,point.y].every(Number.isFinite));
 assert.ok(b.width>0&&b.height>0&&b.left>=region.left&&b.top>=region.top&&b.left+b.width<=region.left+region.width&&b.top+b.height<=region.top+region.height,'Observed glyphs must fit the declared region');
 assert.equal(point.x,b.left+b.width/2);assert.equal(point.y,b.top+b.height/2);return point;
}
export function themeLine(point){
 observedControl(point,{left:0,top:92,width:640,height:52});const b=point.textBounds;
 const region={left:b.left-4,top:b.top-4,width:140,height:b.height+8};assert.ok(region.left>=0&&region.left+region.width<=640&&region.top>=92&&region.top+region.height<=144);return region;
}
export function requireCompleteText(text,expected){
 assert.ok(['Back to conversation','Conversations','Obsidian Ice','Aurora Graphite'].includes(expected));
 const pattern=expected.split(' ').join('\\s+');assert.match(text.trim(),new RegExp('^'+pattern+'$','i'),'Complete exact diagnostic text is required');
}
export function summarizeAx(nodes){
 assert.ok(Array.isArray(nodes)&&nodes.length<=4096);
 const exposed=nodes.filter(node=>!node.ignored).map(node=>({role:node.role?.value??'',name:node.name?.value??''}));
 return{observationOnly:true,screenReaderQualified:false,exposed,buttons:exposed.filter(node=>node.role==='button'),textboxes:exposed.filter(node=>node.role==='textbox')};
}
