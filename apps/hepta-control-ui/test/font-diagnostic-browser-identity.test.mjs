import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {recordDiagnosticBrowser,recordProductBrowser,FIXED_BROWSER_VERSION} from '../tools/font-diagnostic-browser-identity.mjs';

const DATA=Buffer.from('mock running executable');
function fixture(options={}){
 const calls=[],records=[];let processReads=0,closed=0,detached=0;
 const info={isFile:()=>true,size:DATA.length,...options.info};
 const executable={
  async stat(){calls.push('fstat');return info;},
  createReadStream(value){
   assert.deepEqual(value,{autoClose:false});calls.push('stream-from-open-handle');
   return (async function*(){if(options.readError)throw new Error('mock read failed');yield* options.chunks??[DATA];})();
  },
  async close(){closed++;},
 };
 const session={
  async send(method){
   calls.push(method);
   if(method==='Browser.getVersion')return {product:'HeadlessChrome/153.0.8010.12',revision:'@mock-baseline'};
   if(method==='Browser.getBrowserCommandLine')throw new Error('Protocol error (Browser.getBrowserCommandLine): Command line not returned because --enable-automation not set.');
   assert.equal(method,'SystemInfo.getProcessInfo');
   if(options.cdpError)throw new Error('mock CDP failed');
   processReads++;
   return {processInfo:processReads===2&&options.afterProcesses!==undefined?options.afterProcesses:options.processes??[{type:'browser',id:123},{type:'renderer',id:456}]};
  },
  async detach(){detached++;},
 };
 const browser={async newBrowserCDPSession(){calls.push('browser-session');return session;},version:()=>options.version??'153.0.8010.12'};
 const testInfo={project:{name:options.project??'baseline-untouched',metadata:{diagnosticOnly:options.diagnosticOnly??true,expectedBrowser:options.expectedBrowser??'153.0.8010.12',productBrowserQualification:options.productBrowserQualification}},outputPath:name=>name};
 const io={
  platform:options.platform??'linux',
  async open(path,mode){calls.push(['open',path,mode]);if(options.openError)throw new Error('mock open failed');return executable;},
  async readlink(path){calls.push(['readlink',path]);if(options.linkError)throw new Error('mock link failed');return '/different/on-disk/path (deleted)';},
  async writeFile(path,value){assert.equal(path,'browser-identity.json');records.push(JSON.parse(value));},
  getPlaywrightVersion:()=> '1.63.0',
 };
 return {run:()=>(options.product?recordProductBrowser:recordDiagnosticBrowser)(browser,testInfo,io),calls,records,closed:()=>closed,detached:()=>detached};
}

test('records actual browser process executable through one bounded open handle',async()=>{
 const f=fixture();await f.run();
 assert.deepEqual(f.records,[{
  diagnosticOnly:true,verified:true,identityMethod:'cdp-browser-pid/proc-exe-fd',
  product:'HeadlessChrome/153.0.8010.12',revision:'@mock-baseline',browserPid:123,
  executablePath:'/different/on-disk/path (deleted)',executableBytes:DATA.length,
  executableSha256:createHash('sha256').update(DATA).digest('hex'),playwrightVersion:'1.63.0',
 }]);
 assert.deepEqual(f.calls,['browser-session','Browser.getVersion','SystemInfo.getProcessInfo',['open','/proc/123/exe','r'],'fstat',['readlink','/proc/123/exe'],'stream-from-open-handle','fstat','SystemInfo.getProcessInfo']);
 assert.equal(f.closed(),1);assert.equal(f.detached(),1);
});

test('primary runs return without CDP or filesystem access',async()=>{
 const f=fixture({diagnosticOnly:false});await f.run();
 assert.deepEqual(f.calls,[]);assert.deepEqual(f.records,[]);
});

test('unsupported diagnostic platforms fail before CDP queries or executable access',async()=>{
 const f=fixture({platform:'win32'});await assert.rejects(f.run(),/requires Linux procfs/);
 assert.deepEqual(f.calls,['browser-session']);assert.equal(f.closed(),0);assert.equal(f.detached(),1);
 assert.equal(f.records[0].verified,false);assert.match(f.records[0].error,/requires Linux procfs/);
});

test('missing duplicate and invalid browser PIDs fail before opening a file',async()=>{
 for(const processes of [{},[],[{type:'renderer',id:123}],[{type:'browser',id:1},{type:'browser',id:2}],...[-1,0,1.5,Number.MAX_SAFE_INTEGER+1,NaN,Infinity,'123',null,undefined].map(id=>[{type:'browser',id}])]){
  const f=fixture({processes});await assert.rejects(f.run(),/browser process list|browser PID/);
  assert.equal(f.calls.some(call=>Array.isArray(call)&&call[0]==='open'),false);
  assert.equal(f.records[0].verified,false);assert.equal(f.detached(),1);
 }
});

test('nonregular empty oversized and short executable reads fail closed',async()=>{
 for(const options of [{info:{isFile:()=>false}},{info:{size:0}},{info:{size:512*1024*1024+1}},{info:{size:DATA.length+1}},{chunks:[DATA,Buffer.from('growth')]}]){
  const f=fixture(options);await assert.rejects(f.run(),/Invalid running|byte bound|size changed/);
  assert.equal(f.records[0].verified,false);assert.equal(f.closed(),1);assert.equal(f.detached(),1);
 }
});

test('CDP open link and stream read errors retain failed evidence and release acquired resources',async()=>{
 for(const kind of ['cdpError','openError','linkError','readError']){
  const f=fixture({[kind]:true});await assert.rejects(f.run(),/mock .* failed/);
  assert.equal(f.records[0].verified,false);assert.match(f.records[0].error,/mock .* failed/);
  assert.equal(f.closed(),['linkError','readError'].includes(kind)?1:0);assert.equal(f.detached(),1);
 }
});

test('PID replacement runtime version and fixed digest mismatches remain failures',async()=>{
 for(const [options,message] of [[{afterProcesses:[{type:'browser',id:124}]},/PID changed/],[{version:'unexpected'},/version mismatch/],[{project:'fixed-untouched'},/digest mismatch/]]){
  const f=fixture(options);await assert.rejects(f.run(),message);
  assert.equal(f.records[0].verified,false);assert.match(f.records[0].error,message);
  assert.equal(f.closed(),1);assert.equal(f.detached(),1);
 }
});

test('product qualification cannot fall back to an unconfigured or old browser profile',async()=>{
 for(const options of [{},{productBrowserQualification:true},{expectedBrowser:FIXED_BROWSER_VERSION}]){
  const f=fixture({product:true,diagnosticOnly:false,...options});
  await assert.rejects(f.run(),/requires the reviewed fixed browser profile/);
  assert.deepEqual(f.calls,[]);assert.deepEqual(f.records,[]);
 }
});

test('product profile hashes the running executable and rejects an unpinned binary',async()=>{
 const f=fixture({product:true,diagnosticOnly:false,productBrowserQualification:true,expectedBrowser:FIXED_BROWSER_VERSION,version:FIXED_BROWSER_VERSION});
 await assert.rejects(f.run(),/digest mismatch/);
 assert.equal(f.records.length,1);assert.equal(f.records[0].verified,false);
 assert.equal(f.records[0].diagnosticOnly,false);assert.equal(f.records[0].productBrowserQualification,true);
 assert.equal(f.records[0].executableSha256,createHash('sha256').update(DATA).digest('hex'));
 assert.equal(f.closed(),1);assert.equal(f.detached(),1);
});

test('product spec retains separately labeled diagnostic baseline observations',async()=>{
 const f=fixture({product:true});await f.run();
 assert.equal(f.records[0].diagnosticOnly,true);assert.equal(f.records[0].verified,true);
 assert.equal(f.records[0].productBrowserQualification,undefined);
});
