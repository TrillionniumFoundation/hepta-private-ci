
function utf8(text) {
  const bytes=[];
  for(const ch of text){const cp=ch.codePointAt(0);
    if(cp<0x80)bytes.push(cp);
    else if(cp<0x800)bytes.push(0xc0|(cp>>6),0x80|(cp&63));
    else if(cp<0x10000)bytes.push(0xe0|(cp>>12),0x80|((cp>>6)&63),0x80|(cp&63));
    else bytes.push(0xf0|(cp>>18),0x80|((cp>>12)&63),0x80|((cp>>6)&63),0x80|(cp&63));
  }return new Uint8Array(bytes);
}
function sha1(bytes) {
  const n=bytes.length, size=Math.ceil((n+9)/64)*64;
  const data=new Uint8Array(size); data.set(bytes); data[n]=0x80;
  const dv=new DataView(data.buffer); dv.setUint32(size-8,Math.floor(n/0x20000000));dv.setUint32(size-4,(n*8)>>>0);
  const rol=(v,s)=>(v<<s)|(v>>>(32-s));
  let h=[0x67452301,0xefcdab89,0x98badcfe,0x10325476,0xc3d2e1f0];
  const w=new Int32Array(80);
  for(let o=0;o<size;o+=64){for(let i=0;i<16;i++)w[i]=dv.getInt32(o+4*i);for(let i=16;i<80;i++)w[i]=rol(w[i-3]^w[i-8]^w[i-14]^w[i-16],1);
    let [a,b,c,d,e]=h;
    for(let i=0;i<80;i++){let f,k;if(i<20){f=(b&c)|(~b&d);k=0x5a827999;}else if(i<40){f=b^c^d;k=0x6ed9eba1;}else if(i<60){f=(b&c)|(b&d)|(c&d);k=0x8f1bbcdc;}else{f=b^c^d;k=0xca62c1d6;}const t=(rol(a,5)+f+e+k+w[i])|0;e=d;d=c;c=rol(b,30);b=a;a=t;}
    h=h.map((v,i)=>(v+[a,b,c,d,e][i])|0);
  }return h.map(v=>(v>>>0).toString(16).padStart(8,"0")).join("");
}
function sha256(bytes) {
  const k=[0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];
  const n=bytes.length,size=Math.ceil((n+9)/64)*64,data=new Uint8Array(size);data.set(bytes);data[n]=128;
  const dv=new DataView(data.buffer);dv.setUint32(size-8,Math.floor(n/0x20000000));dv.setUint32(size-4,(n*8)>>>0);
  let hs=[0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19];
  const r=(x,n)=>(x>>>n)|(x<<(32-n)),w=new Int32Array(64);
  for(let o=0;o<size;o+=64){for(let i=0;i<16;i++)w[i]=dv.getInt32(o+i*4);for(let i=16;i<64;i++){let s0=r(w[i-15],7)^r(w[i-15],18)^(w[i-15]>>>3),s1=r(w[i-2],17)^r(w[i-2],19)^(w[i-2]>>>10);w[i]=(w[i-16]+s0+w[i-7]+s1)|0;}
    let [a,b,c,d,e,f,g,h]=hs;
    for(let i=0;i<64;i++){const s1=r(e,6)^r(e,11)^r(e,25),ch=(e&f)^(~e&g),t1=(h+s1+ch+k[i]+w[i])|0,s0=r(a,2)^r(a,13)^r(a,22),maj=(a&b)^(a&c)^(b&c),t2=(s0+maj)|0;h=g;g=f;f=e;e=(d+t1)|0;d=c;c=b;b=a;a=(t1+t2)|0;}
    hs=hs.map((v,i)=>(v+[a,b,c,d,e,f,g,h][i])|0);
  }return hs.map(v=>(v>>>0).toString(16).padStart(8,"0")).join("");
}
function concatBytes(a,b){const r=new Uint8Array(a.length+b.length);r.set(a);r.set(b,a.length);return r;}
function gitBlob(text){const bytes=utf8(text);return sha1(concatBytes(utf8("blob "+bytes.length+"\0"),bytes));}
function identity(text){const b=utf8(text);return {bytes:b.length,git_blob:gitBlob(text),sha256:sha256(b)};}
function base64(bytes){const chars="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";let s="";for(let i=0;i<bytes.length;i+=3){const a=bytes[i],b=bytes[i+1],c=bytes[i+2],n=(a<<16)|((b||0)<<8)|(c||0);s+=chars[(n>>>18)&63]+chars[(n>>>12)&63]+(i+1<bytes.length?chars[(n>>>6)&63]:"=")+(i+2<bytes.length?chars[n&63]:"=");}return s;}
