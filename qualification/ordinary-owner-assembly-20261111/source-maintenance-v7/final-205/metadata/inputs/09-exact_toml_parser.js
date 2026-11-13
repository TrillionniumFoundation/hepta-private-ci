const utf8 = function utf8Bytes(s){const a=[];for(const ch of s){let n=ch.codePointAt(0);if(n>=0xd800&&n<=0xdfff)n=0xfffd;if(n<0x80)a.push(n);else if(n<0x800)a.push(0xc0|(n>>6),0x80|(n&63));else if(n<0x10000)a.push(0xe0|(n>>12),0x80|((n>>6)&63),0x80|(n&63));else a.push(0xf0|(n>>18),0x80|((n>>12)&63),0x80|((n>>6)&63),0x80|(n&63));}return new Uint8Array(a);};
const sha1 = function sha1Bytes(input){const n=input.length,len=Math.ceil((n+9)/64)*64,b=new Uint8Array(len);b.set(input);b[n]=128;const v=new DataView(b.buffer);v.setUint32(len-8,Math.floor(n/0x20000000),false);v.setUint32(len-4,(n*8)>>>0,false);let h0=0x67452301,h1=0xefcdab89,h2=0x98badcfe,h3=0x10325476,h4=0xc3d2e1f0;const w=new Uint32Array(80),rol=(x,k)=>(x<<k)|(x>>>(32-k));for(let p=0;p<len;p+=64){for(let i=0;i<16;i++)w[i]=v.getUint32(p+4*i,false);for(let i=16;i<80;i++)w[i]=rol(w[i-3]^w[i-8]^w[i-14]^w[i-16],1);let a=h0,b=h1,c=h2,d=h3,e=h4;for(let i=0;i<80;i++){let f,k;if(i<20){f=(b&c)|(~b&d);k=0x5a827999;}else if(i<40){f=b^c^d;k=0x6ed9eba1;}else if(i<60){f=(b&c)|(b&d)|(c&d);k=0x8f1bbcdc;}else{f=b^c^d;k=0xca62c1d6;}const t=(rol(a,5)+f+e+k+w[i])>>>0;e=d;d=c;c=rol(b,30);b=a;a=t;}h0=(h0+a)>>>0;h1=(h1+b)>>>0;h2=(h2+c)>>>0;h3=(h3+d)>>>0;h4=(h4+e)>>>0;}return[h0,h1,h2,h3,h4].map(n=>n.toString(16).padStart(8,"0")).join("");};
const sha256 = function sha256Bytes(input){const K=[0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];const n=input.length,len=Math.ceil((n+9)/64)*64,b=new Uint8Array(len);b.set(input);b[n]=128;const v=new DataView(b.buffer);v.setUint32(len-8,Math.floor(n/0x20000000),false);v.setUint32(len-4,(n*8)>>>0,false);const h=[0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19],w=new Uint32Array(64),r=(x,k)=>(x>>>k)|(x<<(32-k));for(let p=0;p<len;p+=64){for(let i=0;i<16;i++)w[i]=v.getUint32(p+4*i,false);for(let i=16;i<64;i++){let s0=r(w[i-15],7)^r(w[i-15],18)^(w[i-15]>>>3),s1=r(w[i-2],17)^r(w[i-2],19)^(w[i-2]>>>10);w[i]=(w[i-16]+s0+w[i-7]+s1)>>>0;}let[a,b,c,d,e,f,g,hh]=h;for(let i=0;i<64;i++){const s1=r(e,6)^r(e,11)^r(e,25),ch=(e&f)^(~e&g),t1=(hh+s1+ch+K[i]+w[i])>>>0,s0=r(a,2)^r(a,13)^r(a,22),maj=(a&b)^(a&c)^(b&c),t2=(s0+maj)>>>0;hh=g;g=f;f=e;e=(d+t1)>>>0;d=c;c=b;b=a;a=(t1+t2)>>>0;}[a,b,c,d,e,f,g,hh].forEach((x,i)=>h[i]=(h[i]+x)>>>0);}return h.map(n=>n.toString(16).padStart(8,"0")).join("");};
const gitBlob = function gitBlob(s){const data=typeof s==="string"?utf8(s):s,head=utf8("blob "+data.length+"\0");const b=new Uint8Array(head.length+data.length);b.set(head);b.set(data,head.length);return sha1(b);};
const toml = (() => { 
function parseToml(text) {
 let i=0, current, owner=null;
 const root={}; current=root; const rows=[]; const fields=[];
 const err=m=>{throw Error(m+" at "+i+" "+text.slice(i,i+100));};
 function skip(){while(i<text.length){if(/\s/.test(text[i])){i++;continue;}if(text[i]==="#"){while(i<text.length&&text[i]!=="\n")i++;continue;}break;}}
 function string(){
  const q=text[i]; const triple=text.slice(i,i+3)===q.repeat(3);i+=triple?3:1;let s="";
  if(triple&&text[i]==="\n")i++;
  while(i<text.length){
   if(triple?text.slice(i,i+3)===q.repeat(3):text[i]===q){i+=triple?3:1;return s;}
   if(q==='"'&&text[i]==="\\"){
    i++;const c=text[i++];const map={b:"\b",t:"\t",n:"\n",f:"\f",r:"\r",'"':'"',"\\":"\\"};
    if(c in map)s+=map[c];
    else if(c==="u"||c==="U"){const n=c==="u"?4:8;const h=text.slice(i,i+n);if(!new RegExp("^[0-9a-fA-F]{"+n+"}$").test(h))err("unicode");s+=String.fromCodePoint(parseInt(h,16));i+=n;}
    else if(triple&&(c==="\n"||c==="\r")){while(/\s/.test(text[i]??""))i++;}
    else err("escape "+c);
   }else{s+=text[i++];}
  }err("unclosed string");
 }
 function key(){skip();if(text[i]==='"'||text[i]==="'")return string();const m=/^[A-Za-z0-9_-]+/.exec(text.slice(i));if(!m)err("key");i+=m[0].length;return m[0];}
 function value(){
  skip();const c=text[i];if(c==='"'||c==="'")return string();
  if(c==="["){i++;const a=[];skip();while(text[i]!=="]"){a.push(value());skip();if(text[i]===","){i++;skip();}else if(text[i]!=="]")err("array comma");}i++;return a;}
  if(c==="{"){i++;const o={};skip();while(text[i]!=="}"){const k=key();skip();if(text[i++]!=="=")err("inline equals");if(k in o)err("duplicate inline");o[k]=value();skip();if(text[i]===","){i++;skip();}else if(text[i]!=="}")err("inline comma");}i++;return o;}
  const m=/^(?:true|false|[-+]?[0-9]+(?:\.[0-9]+)?)/.exec(text.slice(i));if(!m)err("value");i+=m[0].length;return m[0]==="true"?true:m[0]==="false"?false:Number(m[0]);
 }
 while(true){
  skip();if(i>=text.length)break;
  if(text[i]==="["){
   const start=i;const arr=text[i+1]==="[";const close=arr?"]]":"]";i+=arr?2:1;const j=text.indexOf(close,i);if(j<0)err("header");const name=text.slice(i,j).trim();i=j+close.length;
   const parts=name.split(".");let at=root;
   for(let n=0;n<parts.length-1;n++){const k=parts[n];if(!(k in at))at[k]={};at=Array.isArray(at[k])?at[k][at[k].length-1]:at[k];if(!at)err("missing parent");}
   const k=parts.at(-1);
   if(arr){if(!(k in at))at[k]=[];if(!Array.isArray(at[k]))err("not array table");current={};at[k].push(current);}
   else {if(!(k in at))at[k]={};current=at[k];}
   if(arr&&parts.length===1&&(name==="boundary"||name==="protected_file")){
    if(rows.length)rows.at(-1).end=start;
    owner={kind:name,index:root[name].length-1,start,end:null,fields:[]};rows.push(owner);
   }
   continue;
  }
  const start=i,k=key();skip();if(text[i++]!=="=")err("equals");skip();const vs=i;const v=value(),ve=i;
  if(Object.hasOwn(current,k))err("duplicate field "+k);
  current[k]=v;const f={key:k,start,value_start:vs,value_end:ve,value:v,table:current};fields.push(f);if(owner)owner.fields.push(f);
  while(i<text.length&&text[i]!=="\n"){if(text[i]==="#"){while(i<text.length&&text[i]!=="\n")i++;break;}if(!/[ \t\r]/.test(text[i]))err("trailing");i++;}
 }
 if(rows.length)rows.at(-1).end=text.length;
 return {value:root,rows,fields};
}
return {parseToml};

})();

return {parseToml:toml.parseToml,gitBlob,sha256,utf8};