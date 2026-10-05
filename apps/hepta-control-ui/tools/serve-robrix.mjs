// Development static-file server, not an owner/API/chat transport.
import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { extname, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import {robrixSourceIdentity} from './robrix-source-identity.mjs';
const root=fileURLToPath(new URL(process.env.HEPTA_ROBRIX_FIXTURES==='1'?'../dist-robrix-fixtures/':'../dist/',import.meta.url));
const port=Number(process.env.PORT ?? 4175);
if (!Number.isInteger(port)||port<1024||port>65535) throw new Error('Invalid local development port');
const manifest=JSON.parse(await readFile(resolve(root,'build-manifest.json'),'utf8'));
const sourceRoot=fileURLToPath(new URL('..',import.meta.url));
if((await robrixSourceIdentity(sourceRoot)).sha256!==manifest.sourceIdentity?.sha256) throw new Error('Built artifact is stale; rebuild current UI source');
if (manifest.browserRuntime!=='rust-makepad-wasm') throw new Error('Build the canonical Robrix UI first');
const mime={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.wasm':'application/wasm','.ttf':'font/ttf','.otf':'font/otf','.png':'image/png','.svg':'image/svg+xml','.json':'application/json'};
createServer(async(req,res)=>{
 try {
  if(req.method!=='GET'&&req.method!=='HEAD'){res.writeHead(405);res.end();return;}
  const pathname=decodeURIComponent(new URL(req.url,'http://localhost').pathname);
  const path=resolve(root,'.'+(pathname==='/'?'/index.html':pathname));
  if(!path.startsWith(root.endsWith(sep)?root:root+sep)||!(await stat(path)).isFile()){res.writeHead(404);res.end();return;}
  res.writeHead(200,{'Content-Type':mime[extname(path)]??'application/octet-stream','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','Content-Security-Policy':"default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self'; connect-src 'self'; img-src 'self' data:; font-src 'self'; worker-src 'self' blob:; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"});
  res.end(req.method==='HEAD'?undefined:await readFile(path));
 }catch{res.writeHead(404);res.end();}
}).listen(port,'127.0.0.1',()=>console.log(`Robrix-derived UI development artifact: http://127.0.0.1:${port}`));
