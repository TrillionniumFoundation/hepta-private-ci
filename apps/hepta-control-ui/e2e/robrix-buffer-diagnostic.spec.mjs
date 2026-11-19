// Diagnostic comparison only. The unmodified host's strict OCR acceptance runs separately.
import {test,expect} from '@playwright/test';
import {writeFile} from 'node:fs/promises';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {fileURLToPath} from 'node:url';
import {readScreenshotText} from '../tools/verify-robrix-pixels.mjs';
const run=promisify(execFile);

test('compare the same WASM with discarded and retained drawing buffers',async({browser},testInfo)=>{
 const observations=[];const diagnosticErrors=[];
 for(const preserve of [false,true]){
  const context=await browser.newContext({viewport:{width:1280,height:800}});
  const page=await context.newPage();const events=[];const pending=new Set();
  await page.addInitScript(()=>{
   window.__heptaGlSubmit={draws:0,cpuMs:0};
   for(const name of ['drawArrays','drawElements','drawArraysInstanced','drawElementsInstanced']){
    const original=WebGL2RenderingContext.prototype[name];
    WebGL2RenderingContext.prototype[name]=function(...args){
     const start=performance.now();
     try{return original.apply(this,args);}finally{window.__heptaGlSubmit.draws++;window.__heptaGlSubmit.cpuMs+=performance.now()-start;}
    };
   }
  });
  page.on('console',message=>events.push({type:message.type(),text:message.text().slice(0,2000)}));
  page.on('pageerror',error=>events.push({type:'pageerror',text:error.message}));
  page.on('request',request=>{if(/\.(ttf|otf)(?:[?#]|$)/.test(request.url()))pending.add(request);});
  page.on('requestfinished',request=>pending.delete(request));
  page.on('requestfailed',request=>pending.delete(request));
  // One explicit platform attribute is the sole comparison variable. Keep the
  // same origin, WASM, CSS, CSP headers and application state for both subjects.
  if(!preserve) await page.route('http://127.0.0.1:4175/',async route=>{
   const response=await route.fetch();const body=await response.text();
   expect(body.match(/<canvas /g)).toHaveLength(1);
   expect(body.match(/ preserveDrawingBuffer\b/g)).toHaveLength(1);
   await route.fulfill({response,body:body.replace(' preserveDrawingBuffer','')});
  });
  try{
   await page.goto('http://127.0.0.1:4175/');
   await expect(page.locator('.canvas_loader')).toBeHidden({timeout:60000});
   await expect.poll(()=>pending.size,{timeout:60000}).toBe(0);
   for(const stage of ['initial','resize','settled']){
    if(stage==='resize')await page.setViewportSize({width:640,height:800});
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    const pixels=await page.locator('canvas').evaluate(canvas=>{
     const gl=canvas.getContext('webgl2');if(!gl)return{available:false};
     const width=gl.drawingBufferWidth,height=gl.drawingBufferHeight;
     if(width*height>8*1024*1024)throw new Error('Diagnostic framebuffer exceeds bound');
     const data=new Uint8Array(width*height*4);const binding=gl.getParameter(gl.FRAMEBUFFER_BINDING);
     gl.bindFramebuffer(gl.FRAMEBUFFER,null);
     try{gl.readPixels(0,0,width,height,gl.RGBA,gl.UNSIGNED_BYTE,data);}finally{gl.bindFramebuffer(gl.FRAMEBUFFER,binding);}
     const colors=new Set();let nonzero=0;
     for(let i=0;i<data.length;i+=64){const value=data[i]*16777216+data[i+1]*65536+data[i+2]*256+data[i+3];if(value)nonzero++;if(colors.size<256)colors.add(value);}
     return{available:true,width,height,devicePixelRatio:devicePixelRatio,cssWidth:canvas.clientWidth,cssHeight:canvas.clientHeight,rgbaSurfaceEquivalentBytes:width*height*4,contextLost:gl.isContextLost(),attributes:gl.getContextAttributes(),glError:gl.getError(),sampleColors:colors.size,nonzeroSamples:nonzero};
    });
    expect(pixels.available).toBe(true);
    expect(pixels.attributes.preserveDrawingBuffer).toBe(preserve);
    const name=`buffer-${preserve?'retained':'discarded'}-${stage}`;
    // Capture the actual isolated X display immediately around Playwright's
    // page capture. They are adjacent observations, not claimed atomic frames.
    const captureStarted=Date.now();
    for(const position of ['before','after']){
     if(position==='after')await page.screenshot({path:testInfo.outputPath(name+'.png'),caret:'initial'});
     const displayPath=testInfo.outputPath(name+`-display-${position}.png`);
     await run('python3',[fileURLToPath(new URL('../tools/capture-xvfb-display.py',import.meta.url)),displayPath],{timeout:10000,maxBuffer:65536});
     await writeFile(testInfo.outputPath(name+`-display-${position}-ocr.txt`),await readScreenshotText(displayPath));
    }
    const path=testInfo.outputPath(name+'.png');
    const ocr=await readScreenshotText(path);await writeFile(testInfo.outputPath(name+'-ocr.txt'),ocr);
    observations.push({preserve,stage,pixels,ocr,captureStarted,captureFinished:Date.now()});
   }
   const frameSamples=[];
   for(const width of [1280,640,960,1280]){
    await page.setViewportSize({width,height:800});
    await page.mouse.move(width*0.75,350);await page.mouse.wheel(0,width===640?-240:240);
    const sample=await page.evaluate(async()=>{
     const before={...window.__heptaGlSubmit};const gaps=[];let previous;
     for(let i=0;i<31;i++){
      const time=await new Promise(resolve=>requestAnimationFrame(resolve));
      if(previous!==undefined)gaps.push(time-previous);previous=time;
     }
     const sorted=[...gaps].sort((a,b)=>a-b);const canvas=document.querySelector('canvas');const gl=canvas.getContext('webgl2');
     return{gapsMs:gaps,p50Ms:sorted[15],p95Ms:sorted[28],maxMs:sorted[29],drawCalls:window.__heptaGlSubmit.draws-before.draws,submitCpuMs:window.__heptaGlSubmit.cpuMs-before.cpuMs,drawingBuffer:[gl.drawingBufferWidth,gl.drawingBufferHeight],devicePixelRatio,rgbaSurfaceEquivalentBytes:gl.drawingBufferWidth*gl.drawingBufferHeight*4,contextLost:gl.isContextLost()};
    });
    frameSamples.push({width,...sample});
   }
   observations.push({preserve,frameSamples,measurementScope:'RAF cadence and CPU submission intervals, not total GPU memory or a calibrated performance benchmark'});
  }catch(error){diagnosticErrors.push({preserve,message:String(error)});}
  finally{observations.push({preserve,events});await context.close();}
 }
 await writeFile(testInfo.outputPath('host-diagnostics.json'),JSON.stringify({scope:'diagnostic-only; does not qualify either product host',observations,diagnosticErrors},null,2));
 expect(diagnosticErrors).toEqual([]);
});
