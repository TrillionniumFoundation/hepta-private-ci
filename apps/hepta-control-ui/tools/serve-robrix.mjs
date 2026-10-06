// Development static-file server, not an owner/API/chat transport.
import { createServer } from 'node:http';
import { extname } from 'node:path';
import { fileURLToPath } from 'node:url';
import {robrixSourceIdentity} from './robrix-source-identity.mjs';
import {withArtifactLease,loadArtifactSnapshot} from './owned-artifact-lease.mjs';
const sourceRoot=fileURLToPath(new URL('..',import.meta.url));
const fixtures=process.env.HEPTA_ROBRIX_FIXTURES==='1';
const keyboardFocusTrace=process.env.HEPTA_KEYBOARD_FOCUS_TRACE==='1';
if(fixtures&&keyboardFocusTrace)throw new Error('Keyboard trace preview cannot use fixtures');
const snapshot=await withArtifactLease(sourceRoot,'preview',async()=>{
const root=fileURLToPath(new URL(keyboardFocusTrace?'../dist-robrix-keyboard-trace/':fixtures?'../dist-robrix-fixtures/':'../dist/',import.meta.url));
const snapshot=await loadArtifactSnapshot(root);
const {manifest}=snapshot;
if(keyboardFocusTrace){
 if(manifest.fixtures!==false||manifest.diagnostic?.kind!=='keyboard-focus-trace'||manifest.diagnostic?.qualification!==false||manifest.diagnostic?.buildFeature!=='hepta-robrix-ui/keyboard-focus-trace')throw new Error('Expected explicit keyboard diagnostic artifact');
}else if(manifest.diagnostic)throw new Error('Diagnostic artifacts require explicit diagnostic preview');
if((await robrixSourceIdentity(sourceRoot)).sha256!==manifest.sourceIdentity?.sha256) throw new Error('Built artifact is stale; rebuild current UI source');
if (manifest.browserRuntime!=='rust-makepad-wasm') throw new Error('Build the canonical Robrix UI first');
return snapshot;
});
const port=Number(process.env.PORT ?? 4175);
if (!Number.isInteger(port)||port<1024||port>65535) throw new Error('Invalid local development port');
const mime={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.wasm':'application/wasm','.ttf':'font/ttf','.otf':'font/otf','.png':'image/png','.svg':'image/svg+xml','.json':'application/json'};
const server=createServer(async(req,res)=>{
 try {
  if(req.method!=='GET'&&req.method!=='HEAD'){res.writeHead(405);res.end();return;}
  const pathname=decodeURIComponent(new URL(req.url,'http://localhost').pathname);
  const path=pathname==='/'?'index.html':pathname.slice(1);
  const body=snapshot.buffers.get(path);
  if(!body){res.writeHead(404);res.end();return;}
  res.writeHead(200,{'Content-Length':body.length,'Content-Type':mime[extname(path)]??'application/octet-stream','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','Content-Security-Policy':"default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self'; connect-src 'self'; img-src 'self' data:; font-src 'self'; worker-src 'self' blob:; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"});
  res.end(req.method==='HEAD'?undefined:body);
 }catch{res.writeHead(404);res.end();}
});
await new Promise((done,fail)=>{
 let closing=false;
 const stop=()=>{if(!closing){closing=true;server.close();}};
 const release=()=>{process.off('SIGINT',stop);process.off('SIGTERM',stop);done();};
 server.once('error',fail);server.once('close',release);
 process.once('SIGINT',stop);process.once('SIGTERM',stop);
 server.listen(port,'127.0.0.1',()=>console.log(`Robrix-derived UI development artifact: http://127.0.0.1:${port}`));
});
