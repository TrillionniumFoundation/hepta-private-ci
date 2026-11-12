
function utf8(s) {
 const out=[]; for(let i=0;i<s.length;i++){let c=s.codePointAt(i);if(c>65535)i++;if(c<128)out.push(c);else if(c<2048)out.push(192|(c>>6),128|(c&63));else if(c<65536)out.push(224|(c>>12),128|((c>>6)&63),128|(c&63));else out.push(240|(c>>18),128|((c>>12)&63),128|((c>>6)&63),128|(c&63));} return out;
}
function b64decode(s) {
 const chars="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
 const out=[];let accum=0,bits=0;for(const c of s){if(c==="=")break;if(/\s/.test(c))continue;const n=chars.indexOf(c);if(n<0)throw Error("invalid base64");accum=(accum<<6)|n;bits+=6;if(bits>=8){bits-=8;out.push((accum>>bits)&255);}}return out;
}
function sha1Bytes(bytes) {
 const b=bytes.slice(), n=bytes.length, bitLo=(n*8)>>>0,bitHi=Math.floor(n/0x20000000); b.push(128);while(b.length%64!==56)b.push(0);for(let i=3;i>=0;i--)b.push((bitHi>>>(8*i))&255);for(let i=3;i>=0;i--)b.push((bitLo>>>(8*i))&255);
 let h=[0x67452301,0xefcdab89,0x98badcfe,0x10325476,0xc3d2e1f0];
 const rol=(x,n)=>(x<<n)|(x>>>(32-n));
 for(let off=0;off<b.length;off+=64){const w=new Array(80);for(let i=0;i<16;i++)w[i]=(b[off+4*i]<<24)|(b[off+4*i+1]<<16)|(b[off+4*i+2]<<8)|b[off+4*i+3];for(let i=16;i<80;i++)w[i]=rol(w[i-3]^w[i-8]^w[i-14]^w[i-16],1);let[a,c,d,e,f]=h;for(let i=0;i<80;i++){let q,k;if(i<20){q=(c&d)|(~c&e);k=0x5a827999;}else if(i<40){q=c^d^e;k=0x6ed9eba1;}else if(i<60){q=(c&d)|(c&e)|(d&e);k=0x8f1bbcdc;}else{q=c^d^e;k=0xca62c1d6;}const t=(rol(a,5)+q+f+k+w[i])|0;f=e;e=d;d=rol(c,30);c=a;a=t;}h=[(h[0]+a)|0,(h[1]+c)|0,(h[2]+d)|0,(h[3]+e)|0,(h[4]+f)|0];}return h.map(x=>(x>>>0).toString(16).padStart(8,"0")).join("");
}
function sha256Bytes(bytes) {
 const k=[0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];
 let h=[0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19];
 const b=bytes.slice(), n=bytes.length,bitLo=(n*8)>>>0,bitHi=Math.floor(n/0x20000000);b.push(128);while(b.length%64!==56)b.push(0);for(let i=3;i>=0;i--)b.push((bitHi>>>(8*i))&255);for(let i=3;i>=0;i--)b.push((bitLo>>>(8*i))&255);
 const rr=(x,n)=>(x>>>n)|(x<<(32-n));
 for(let off=0;off<b.length;off+=64){const w=new Array(64);for(let i=0;i<16;i++)w[i]=(b[off+4*i]<<24)|(b[off+4*i+1]<<16)|(b[off+4*i+2]<<8)|b[off+4*i+3];for(let i=16;i<64;i++){const s0=rr(w[i-15],7)^rr(w[i-15],18)^(w[i-15]>>>3),s1=rr(w[i-2],17)^rr(w[i-2],19)^(w[i-2]>>>10);w[i]=(w[i-16]+s0+w[i-7]+s1)|0;}let[a,c,d,e,f,g,j,l]=h;for(let i=0;i<64;i++){const s1=rr(f,6)^rr(f,11)^rr(f,25),ch=(f&g)^(~f&j),t1=(l+s1+ch+k[i]+w[i])|0,s0=rr(a,2)^rr(a,13)^rr(a,22),maj=(a&c)^(a&d)^(c&d),t2=(s0+maj)|0;l=j;j=g;g=f;f=(e+t1)|0;e=d;d=c;c=a;a=(t1+t2)|0;}h=[(h[0]+a)|0,(h[1]+c)|0,(h[2]+d)|0,(h[3]+e)|0,(h[4]+f)|0,(h[5]+g)|0,(h[6]+j)|0,(h[7]+l)|0];}return h.map(x=>(x>>>0).toString(16).padStart(8,"0")).join("");
}
function metaBytes(bytes){return {bytes:bytes.length,sha256:sha256Bytes(bytes),git_blob:sha1Bytes(utf8("blob "+bytes.length+"\0").concat(bytes))};}
function metaText(s){return metaBytes(utf8(s));}
return {utf8,b64decode,sha1Bytes,sha256Bytes,metaBytes,metaText};
