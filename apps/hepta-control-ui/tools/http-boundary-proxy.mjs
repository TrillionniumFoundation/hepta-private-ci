// The URL remains HTTP loopback while the actual transport is an HTTPS HTTP/2 proxy.
// This is the previously demonstrated counterexample to URL-based framing guesses.
import {createSecureServer} from 'node:http2';
import {mkdtemp,readFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {pageHtml} from './http-boundary-fixture.mjs';

export async function startBoundaryProxy(script){
 const directory=await mkdtemp(join(tmpdir(),'hepta-http2-boundary-'));
 const keyPath=join(directory,'key.pem'),certPath=join(directory,'cert.pem');
 let server;
 try{
  execFileSync('openssl',['req','-x509','-newkey','rsa:2048','-sha256','-days','2','-nodes','-subj','/CN=localhost','-keyout',keyPath,'-out',certPath],{stdio:'ignore'});
  const publicKey=execFileSync('openssl',['x509','-in',certPath,'-pubkey','-noout']);
  const spki=execFileSync('openssl',['pkey','-pubin','-outform','DER'],{input:publicKey});
  const certificateSpki=createHash('sha256').update(spki).digest('base64');
  const certificate=await readFile(certPath);
  const sessions=new Set(),records=new Map();
  server=createSecureServer({key:await readFile(keyPath),cert:certificate,allowHTTP1:false});
  server.on('session',session=>{sessions.add(session);session.on('error',()=>{});session.once('close',()=>sessions.delete(session));});
  server.on('stream',(stream,headers)=>{
   const url=new URL(headers[':path'],'http://fixture');
   const key=url.pathname+url.search;
   stream.on('error',error=>{const record=records.get(key);if(record)record.error=String(error.message).slice(0,256);});
   if(url.pathname==='/'||url.pathname==='/sdk.js'){
    const bytes=url.pathname==='/'?pageHtml:script;
    stream.respond({':status':200,'cache-control':'no-store','content-type':url.pathname==='/'?'text/html':'text/javascript','content-length':bytes.length});stream.end(bytes);return;
   }
   if(url.pathname!=='/control/h2-small-length'){stream.respond({':status':404});stream.end();return;}
   const complete=url.searchParams.get('wire')!=='open';
   const record={key,name:'h2-small-length',protocol:'h2',declaredBytes:1,writtenBytes:65536,complete,finished:false,closed:false};records.set(key,record);
   stream.once('finish',()=>{record.finished=true;});stream.once('close',()=>{record.closed=true;});
   stream.respond({':status':503,'cache-control':'no-store','content-type':'application/octet-stream','content-length':'1'});
   if(complete)stream.end(Buffer.alloc(65536,0x61));
   else stream.write(Buffer.alloc(65536,0x61));
  });
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
  return {proxy:{server:'https://127.0.0.1:'+server.address().port,bypass:'<-loopback>'},certificate,certificateSpki,records,async close(){for(const session of sessions)session.destroy();await new Promise(resolve=>server.close(resolve));await rm(directory,{recursive:true,force:true});}};
 }catch(error){if(server)server.close();await rm(directory,{recursive:true,force:true});throw error;}
}
