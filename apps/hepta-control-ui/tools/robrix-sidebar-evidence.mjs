// Fixture evidence validation only. Never writes app state or controls rendering.
import assert from 'node:assert/strict';
export function validateSidebarSurface({viewport,metrics,drawDpiFactor,pngSize}){
 assert.ok([viewport.width,viewport.height].every(value=>Number.isInteger(value)&&value>0),'Viewport must be positive integer CSS dimensions');
 assert.deepEqual(metrics.css,{x:0,y:0,...viewport},'Canvas CSS bounds must match the full capture viewport');
 assert.ok(Number.isFinite(metrics.dpr)&&metrics.dpr>0,'Browser DPR must be finite and positive');
 assert.ok(Number.isFinite(drawDpiFactor)&&drawDpiFactor>0&&drawDpiFactor<=metrics.dpr,'Real Rust draw-pass DPI must be positive and bounded by browser DPR');
 // Pinned web.js budgets the drawable and floors physical dimensions, then
 // sends the same effective scale to Rust in window_info.dpi_factor. PNGs use
 // the browser device scale independently; neither scale is inferred from text.
 assert.deepEqual(metrics.buffer,{width:Math.floor(viewport.width*drawDpiFactor),height:Math.floor(viewport.height*drawDpiFactor)},'Backing dimensions must agree with the observed Rust draw-pass DPI');
 assert.deepEqual(metrics.drawingBuffer,metrics.buffer,'Actual GL drawable and canvas backing dimensions must agree');
 assert.equal(metrics.contextLost,false,'GL context must remain live');
 assert.equal(metrics.retained,true,'The qualified host retains its drawable');
 if(pngSize)assert.deepEqual(pngSize,{width:Math.round(viewport.width*metrics.dpr),height:Math.round(viewport.height*metrics.dpr)},'PNG dimensions must agree with the independent browser DPR');
}
export function requireSidebarLabel(text,label){
 const patterns={brand:/\bHEPTA\b/,group:/\bCONVERSATIONS\b/,newDraft:/\bNew\s+draft\b/i};
 assert.ok(Object.hasOwn(patterns,label),'Unknown sidebar text assertion');
 assert.match(text,patterns[label],'The complete exact sidebar label must be visible');
}
export function requireCompletedSidebarEvidence(evidence,finalTest){
 assert.equal(evidence.scenarioComplete,true,'All required input actions and assertions must have completed');
 assert.equal(finalTest.status,'expected','The final Playwright reporter must accept this case');
 assert.equal(finalTest.expectedStatus,'passed','Expected failures cannot qualify the scenario');
 assert.equal(finalTest.results.length,1,'A retry cannot silently qualify the scenario');
 assert.equal(finalTest.results[0].status,'passed','The final test execution must have passed');
}

export function observedAreaCenter(area,viewport){
 assert.ok(Array.isArray(area)&&area.length===4,'A current real draw Area is required');
 const [x,y,width,height]=area;
 assert.ok(area.every(Number.isFinite)&&width>0&&height>0,'Draw Area must be finite and positive');
 assert.ok(x>=0&&y>=0&&x+width<=viewport.width&&y+height<=viewport.height,'Complete draw Area must remain strictly inside the viewport');
 return{x:x+width/2,y:y+height/2};
}
