// Deterministic real HTTP controls, isolated from product APIs and state.
import {createServer} from 'node:http';
export const CONTROL_BODY=Buffer.from('{"ok":true}');
export function writeControl(response,kind,record,cacheControl='no-store'){
 const headers={'Content-Type':'application/octet-stream','Cache-Control':cacheControl,'Connection':'close'};
 if(kind==='revalidated')headers['Cache-Control']='private, no-cache';
 record.cacheControl=headers['Cache-Control'];
 if(kind==='truncated')headers['Content-Length']='12';
 else if(kind==='declared-limit')headers['Content-Length']='256';
 else headers['Transfer-Encoding']='chunked';
 response.writeHead(200,headers);
 record.writes=1;record.bytes=kind==='declared-limit'?256:CONTROL_BODY.length;
 response.write(kind==='declared-limit'?Buffer.alloc(256,1):CONTROL_BODY);
 const timer=setTimeout(()=>{
  if(response.destroyed||kind==='abort')return;
  if(kind==='truncated'){record.fin=true;response.socket.end();}
  else if(kind==='stream-limit'){record.writes++;record.bytes+=256;response.end(Buffer.alloc(256,2));}
  else response.end();
 },30);
 response.once('close',()=>clearTimeout(timer));
 response.once('finish',()=>{record.finished=true;});
}
export async function startControlServer(snapshot){
 const records=[];
 const server=createServer((request,response)=>{
  const url=new URL(request.url,'http://localhost');
  if(request.method!=='GET'){response.writeHead(405);response.end();return;}
  if(url.pathname==='/probe'){response.setHeader('Content-Type','text/html');response.end('<!doctype html><title>SDK transport diagnostic</title>');return;}
  if(url.pathname==='/control'){
   const kind=url.searchParams.get('kind');
   const cache=url.searchParams.get('cache');
   if(cache!==null&&cache!=='private'){response.writeHead(400);response.end();return;}
   if(!['complete','revalidated','truncated','abort','declared-limit','stream-limit'].includes(kind)||records.length>=128){response.writeHead(400);response.end();return;}
   const record={kind};records.push(record);writeControl(response,kind,record,cache==='private'?'private, no-cache':'no-store');return;
  }
  const bytes=snapshot.buffers.get(url.pathname.slice(1));
  if(!bytes){response.writeHead(404);response.end();return;}
  response.writeHead(200,{'Content-Type':'text/javascript','Content-Length':bytes.length,'Cache-Control':'no-store'});response.end(bytes);
 });
 await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
 return {origin:'http://127.0.0.1:'+server.address().port,records,
  async close(){server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}};
}
