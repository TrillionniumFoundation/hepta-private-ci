// Git-only evidence publication verifier.

// These functions operate on complete Git API text/tree reads; no local or H observation is inferred.

function utf8Bytes(s){const b=[];for(const c of s){const n=c.codePointAt(0);if(n<128)b.push(n);else if(n<2048)b.push(192|(n>>6),128|(n&63));else if(n<65536)b.push(224|(n>>12),128|((n>>6)&63),128|(n&63));else b.push(240|(n>>18),128|((n>>12)&63),128|((n>>6)&63),128|(n&63));}return b;}

function hash256(s){
const a=utf8Bytes(s),bytes=a.length,K=[0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];
const H=[0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19],r=(n,k)=>(n>>>k)|(n<<(32-k));a.push(128);while(a.length%64!==56)a.push(0);for(let i=7;i>=0;i--)a.push(i>=4?0:((bytes*8)>>>i*8)&255);
for(let start=0;start<a.length;start+=64){let w=[];for(let i=0;i<16;i++){let j=start+i*4;w[i]=((a[j]<<24)|(a[j+1]<<16)|(a[j+2]<<8)|a[j+3])>>>0;}for(let i=16;i<64;i++){let p=w[i-15],q=w[i-2],s0=r(p,7)^r(p,18)^(p>>>3),s1=r(q,17)^r(q,19)^(q>>>10);w[i]=(w[i-16]+s0+w[i-7]+s1)>>>0;}let [aa,b,c,d,e,f,g,h]=H;for(let i=0;i<64;i++){let s1=r(e,6)^r(e,11)^r(e,25),ch=(e&f)^(~e&g),t1=(h+s1+ch+K[i]+w[i])>>>0,s0=r(aa,2)^r(aa,13)^r(aa,22),maj=(aa&b)^(aa&c)^(b&c),t2=(s0+maj)>>>0;h=g;g=f;f=e;e=(d+t1)>>>0;d=c;c=b;b=aa;aa=(t1+t2)>>>0;}const v=[aa,b,c,d,e,f,g,h];for(let i=0;i<8;i++)H[i]=(H[i]+v[i])>>>0;}
return {bytes,sha256:H.map(n=>n.toString(16).padStart(8,"0")).join("")};}

function sha1Bytes(input) {
  const a=Array.from(input), n=a.length, bitlen=n*8;
  a.push(128); while(a.length%64!==56)a.push(0);
  const hi=Math.floor(bitlen/4294967296),lo=bitlen>>>0;
  for(let i=3;i>=0;i--)a.push((hi>>>(i*8))&255);
  for(let i=3;i>=0;i--)a.push((lo>>>(i*8))&255);
  let h0=0x67452301,h1=0xefcdab89,h2=0x98badcfe,h3=0x10325476,h4=0xc3d2e1f0;
  const rol=(v,k)=>((v<<k)|(v>>>(32-k)))>>>0;
  for(let off=0;off<a.length;off+=64){
    const w=new Array(80);
    for(let i=0;i<16;i++){const j=off+i*4;w[i]=((a[j]<<24)|(a[j+1]<<16)|(a[j+2]<<8)|a[j+3])>>>0}
    for(let i=16;i<80;i++)w[i]=rol(w[i-3]^w[i-8]^w[i-14]^w[i-16],1);
    let x=h0,y=h1,z=h2,u=h3,v=h4;
    for(let i=0;i<80;i++){
      let f,k;
      if(i<20){f=(y&z)|(~y&u);k=0x5a827999}
      else if(i<40){f=y^z^u;k=0x6ed9eba1}
      else if(i<60){f=(y&z)|(y&u)|(z&u);k=0x8f1bbcdc}
      else{f=y^z^u;k=0xca62c1d6}
      const t=(rol(x,5)+f+v+k+w[i])>>>0;
      v=u;u=z;z=rol(y,30);y=x;x=t;
    }
    h0=(h0+x)>>>0;h1=(h1+y)>>>0;h2=(h2+z)>>>0;h3=(h3+u)>>>0;h4=(h4+v)>>>0;
  }
  return [h0,h1,h2,h3,h4].map(x=>x.toString(16).padStart(8,"0")).join("");
}

function gitTreeHash(entries){
 const cmp=(a,b)=>{
   const aa=utf8Bytes(a.path+(a.type==="tree"?"/":"")),bb=utf8Bytes(b.path+(b.type==="tree"?"/":""));
   for(let i=0;i<Math.min(aa.length,bb.length);i++)if(aa[i]!==bb[i])return aa[i]-bb[i];
   return aa.length-bb.length;
 };
 const sorted=[...entries].sort(cmp),body=[];
 for(const e of sorted){
   if(e.path.includes("/")||e.path.includes("\0")||!e.path||!/^[0-9a-f]{40}$/.test(e.sha))throw Error("invalid tree entry "+e.path);
   const mode=e.mode.replace(/^0+/,"");
   for(const b of utf8Bytes(mode+" "+e.path+"\0"))body.push(b);
   for(let i=0;i<40;i+=2)body.push(parseInt(e.sha.slice(i,i+2),16));
 }
 return sha1Bytes(utf8Bytes("tree "+body.length+"\0").concat(body));
}

function merkleFromFileMap(map){
 const root={files:new Map(),dirs:new Map()},trees={};
 for(const [path,sha]of Object.entries(map)){
  if(path.startsWith("/")||path.includes("\0")||!/^[0-9a-f]{40}$/.test(sha))throw Error("invalid path/blob");
  const parts=path.split("/");if(parts.some(p=>!p||p==="."||p===".."))throw Error("invalid component");
  let cur=root;
  for(const part of parts.slice(0,-1)){
   if(cur.files.has(part))throw Error("file/dir conflict "+path);
   if(!cur.dirs.has(part))cur.dirs.set(part,{files:new Map(),dirs:new Map()});
   cur=cur.dirs.get(part);
  }
  const name=parts.at(-1);if(cur.dirs.has(name)||cur.files.has(name))throw Error("duplicate path");
  cur.files.set(name,sha);
 }
 const visit=(node,path)=>{
  const entries=[...node.files].map(([path,sha])=>({path,sha,mode:"100644",type:"blob"}));
  for(const[name,dir]of node.dirs)entries.push({path:name,sha:visit(dir,path?path+"/"+name:name),mode:"040000",type:"tree"});
  const sha=gitTreeHash(entries);trees[path]={sha,entries};return sha;
 };
 const sha=visit(root,"");return {sha,trees,files:Object.keys(map).length};
}

function gitBlobSha(s){const bytes=utf8Bytes(s);return sha1Bytes(utf8Bytes("blob "+bytes.length+"\0").concat(bytes))}


