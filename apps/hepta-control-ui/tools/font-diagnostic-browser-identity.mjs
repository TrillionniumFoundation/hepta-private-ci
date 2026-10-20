import {createReadStream} from 'node:fs';
import {lstat,open,readlink,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {createRequire} from 'node:module';
export const FIXED_BINARY_SHA='37164bfc553db9c17e11bc19c291738a1179c5b13529ec6f20a39bd665e91be0';
export async function hashDiagnosticFile(path){
 const info=await lstat(path);
 if(!info.isFile()||info.size>512*1024*1024)throw new Error('Invalid diagnostic executable');
 const hash=createHash('sha256');for await(const chunk of createReadStream(path))hash.update(chunk);
 return hash.digest('hex');
}
function browserPid(processInfo){
 if(!Array.isArray(processInfo))throw new Error('Missing diagnostic browser process list');
 const browsers=processInfo.filter(item=>item?.type==='browser');
 if(browsers.length!==1||!Number.isSafeInteger(browsers[0].id)||browsers[0].id<=0)throw new Error('Expected one positive diagnostic browser PID');
 return browsers[0].id;
}
export async function recordDiagnosticBrowser(browser,testInfo,io={platform:process.platform,open,readlink,writeFile,getPlaywrightVersion:()=>createRequire(import.meta.url)('playwright-core/package.json').version}){
 if(!testInfo.project.metadata.diagnosticOnly)return;
 const session=await browser.newBrowserCDPSession();
 const record={diagnosticOnly:true,verified:false,identityMethod:'cdp-browser-pid/proc-exe-fd'};
 try{
  if(io.platform!=='linux')throw new Error('Diagnostic executable identity requires Linux procfs');
  const version=await session.send('Browser.getVersion');
  record.product=version.product;record.revision=version.revision;
  const pid=browserPid((await session.send('SystemInfo.getProcessInfo')).processInfo);
  record.browserPid=pid;
  const executable=await io.open(`/proc/${pid}/exe`,'r');
  try{
   const info=await executable.stat();
   if(!info.isFile()||!Number.isSafeInteger(info.size)||info.size<=0||info.size>512*1024*1024)throw new Error('Invalid running diagnostic executable');
   // The link text is provenance only. Hash the opened process executable,
   // never its resolved pathname, which could have been replaced after launch.
   const path=await io.readlink(`/proc/${pid}/exe`);
   if(typeof path!=='string'||path.length===0||path.length>4096)throw new Error('Invalid diagnostic executable link');
   record.executablePath=path;
   const hash=createHash('sha256');let bytes=0;
   for await(const chunk of executable.createReadStream({autoClose:false})){
    bytes+=chunk.length;
    if(bytes>512*1024*1024||bytes>info.size)throw new Error('Running diagnostic executable exceeded byte bound');
    hash.update(chunk);
   }
   if(bytes!==info.size||(await executable.stat()).size!==info.size)throw new Error('Running diagnostic executable size changed');
   record.executableBytes=bytes;record.executableSha256=hash.digest('hex');
  }finally{await executable.close();}
  if(browserPid((await session.send('SystemInfo.getProcessInfo')).processInfo)!==pid)throw new Error('Diagnostic browser PID changed');
  record.playwrightVersion=io.getPlaywrightVersion();
  if(browser.version()!==testInfo.project.metadata.expectedBrowser)throw new Error('Diagnostic runtime version mismatch');
  if(testInfo.project.name.startsWith('fixed-')){
   if(record.executableSha256!==FIXED_BINARY_SHA)throw new Error('Running diagnostic executable digest mismatch');
   if(!['@94bcda4759263b9a241f5008a68e753c2ebe3081','@3cdad9004f922728bfc61639d120b2ef4bddaf72'].includes(version.revision))throw new Error('Diagnostic runtime revision is outside verified release provenance');
  }
  record.verified=true;
 }catch(error){record.error=String(error?.message??error).slice(0,512);throw error;}
 finally{
  try{await io.writeFile(testInfo.outputPath('browser-identity.json'),JSON.stringify(record,null,2)+'\n');}
  finally{await session.detach();}
 }
}
