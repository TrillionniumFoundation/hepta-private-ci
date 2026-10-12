import {createReadStream} from 'node:fs';
import {lstat,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {createRequire} from 'node:module';
export const FIXED_BINARY_SHA='37164bfc553db9c17e11bc19c291738a1179c5b13529ec6f20a39bd665e91be0';
export async function hashDiagnosticFile(path){
 const info=await lstat(path);
 if(!info.isFile()||info.size>512*1024*1024)throw new Error('Invalid diagnostic executable');
 const hash=createHash('sha256');for await(const chunk of createReadStream(path))hash.update(chunk);
 return hash.digest('hex');
}
export async function recordDiagnosticBrowser(browser,testInfo){
 if(!testInfo.project.metadata.diagnosticOnly)return;
 const session=await browser.newBrowserCDPSession();let record;
 try{
  const version=await session.send('Browser.getVersion');
  const {arguments:args}=await session.send('Browser.getBrowserCommandLine');
  const executableSha256=await hashDiagnosticFile(args[0]);
  record={diagnosticOnly:true,product:version.product,revision:version.revision,executableSha256,playwrightVersion:createRequire(import.meta.url)('playwright-core/package.json').version};
  await writeFile(testInfo.outputPath('browser-identity.json'),JSON.stringify(record,null,2)+'\n');
  if(browser.version()!==testInfo.project.metadata.expectedBrowser)throw new Error('Diagnostic runtime version mismatch');
  if(testInfo.project.name.startsWith('fixed-')){
   if(executableSha256!==FIXED_BINARY_SHA)throw new Error('Running diagnostic executable digest mismatch');
   if(!['@94bcda4759263b9a241f5008a68e753c2ebe3081','@3cdad9004f922728bfc61639d120b2ef4bddaf72'].includes(version.revision))throw new Error('Diagnostic runtime revision is outside verified release provenance');
  }
 }finally{await session.detach();}
}
