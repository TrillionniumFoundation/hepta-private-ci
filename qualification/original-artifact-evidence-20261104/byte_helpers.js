// Standalone byte helpers for repository evidence. No IO or environment access.
function utf8(text) {
  return Uint8Array.from(unescape(encodeURIComponent(text)), char => char.charCodeAt(0));
}
function utf8Text(bytes) {
  let text = "";
  for (let i = 0; i < bytes.length; i += 4096) text += String.fromCharCode(...bytes.slice(i, i + 4096));
  return decodeURIComponent(escape(text));
}
function encode64(bytes) {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  const chunks = [];
  for (let i = 0; i < bytes.length; i += 3) {
    const a = bytes[i], b = bytes[i + 1], c = bytes[i + 2];
    const word = (a << 16) | ((b || 0) << 8) | (c || 0);
    chunks.push(alphabet[(word >>> 18) & 63] + alphabet[(word >>> 12) & 63] +
      (i + 1 < bytes.length ? alphabet[(word >>> 6) & 63] : "=") +
      (i + 2 < bytes.length ? alphabet[word & 63] : "="));
  }
  return chunks.join("");
}
function decode64(text) {
  const input = text.replace(/[\r\n\t ]/g, "");
  if (!/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(input)) throw Error("invalid base64");
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  const padding = input.endsWith("==") ? 2 : input.endsWith("=") ? 1 : 0;
  const output = new Uint8Array(input.length / 4 * 3 - padding);
  let at = 0;
  for (let i = 0; i < input.length; i += 4) {
    const word = (alphabet.indexOf(input[i]) << 18) | (alphabet.indexOf(input[i + 1]) << 12) |
      ((input[i + 2] === "=" ? 0 : alphabet.indexOf(input[i + 2])) << 6) |
      (input[i + 3] === "=" ? 0 : alphabet.indexOf(input[i + 3]));
    for (const shift of [16, 8, 0]) if (at < output.length) output[at++] = (word >>> shift) & 255;
  }
  if (encode64(output) !== input) throw Error("noncanonical base64");
  return output;
}
function padded(bytes) {
  const n = bytes.length;
  if (!Number.isSafeInteger(n) || n > 0x7fffffc0) throw Error("byte input exceeds helper bound");
  const data = new Uint8Array(Math.ceil((n + 9) / 64) * 64);
  data.set(bytes); data[n] = 128;
  const bits = n * 8;
  const high = Math.floor(bits / 0x100000000), low = bits >>> 0;
  for (let i = 0; i < 4; i++) {
    data[data.length - 8 + i] = (high >>> (24 - 8 * i)) & 255;
    data[data.length - 4 + i] = (low >>> (24 - 8 * i)) & 255;
  }
  return data;
}
function hexWords(words) { return Array.from(words, word => (word >>> 0).toString(16).padStart(8, "0")).join(""); }
function sha256(bytes) {
  const k = [0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
    0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
    0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
    0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
    0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
    0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
    0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
    0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];
  const h = new Uint32Array([0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19]);
  const w = new Uint32Array(64), data = padded(bytes), r = (x,n) => (x >>> n) | (x << (32-n));
  for (let p = 0; p < data.length; p += 64) {
    for (let i = 0; i < 16; i++) { const j=p+4*i; w[i]=(data[j]<<24)|(data[j+1]<<16)|(data[j+2]<<8)|data[j+3]; }
    for (let i = 16; i < 64; i++) { const x=w[i-15], y=w[i-2]; w[i]=w[i-16]+(r(x,7)^r(x,18)^(x>>>3))+w[i-7]+(r(y,17)^r(y,19)^(y>>>10)); }
    let [a,b,c,d,e,f,g,z] = h;
    for (let i = 0; i < 64; i++) {
      const t1=(z+(r(e,6)^r(e,11)^r(e,25))+((e&f)^((~e)&g))+k[i]+w[i])>>>0;
      const t2=((r(a,2)^r(a,13)^r(a,22))+((a&b)^(a&c)^(b&c)))>>>0;
      z=g;g=f;f=e;e=(d+t1)>>>0;d=c;c=b;b=a;a=(t1+t2)>>>0;
    }
    const next=[a,b,c,d,e,f,g,z];for(let i=0;i<8;i++)h[i]+=next[i];
  }
  return hexWords(h);
}
function sha1(bytes) {
  const data=padded(bytes), h=new Uint32Array([0x67452301,0xefcdab89,0x98badcfe,0x10325476,0xc3d2e1f0]), w=new Uint32Array(80);
  const l=(x,n)=>(x<<n)|(x>>>(32-n));
  for(let p=0;p<data.length;p+=64){
    for(let i=0;i<16;i++){const j=p+4*i;w[i]=(data[j]<<24)|(data[j+1]<<16)|(data[j+2]<<8)|data[j+3];}
    for(let i=16;i<80;i++)w[i]=l(w[i-3]^w[i-8]^w[i-14]^w[i-16],1);
    let[a,b,c,d,e]=h;
    for(let i=0;i<80;i++){
      let f,k;if(i<20){f=(b&c)|((~b)&d);k=0x5a827999;}else if(i<40){f=b^c^d;k=0x6ed9eba1;}else if(i<60){f=(b&c)|(b&d)|(c&d);k=0x8f1bbcdc;}else{f=b^c^d;k=0xca62c1d6;}
      const next=(l(a,5)+f+e+k+w[i])>>>0;e=d;d=c;c=l(b,30);b=a;a=next;
    }
    const next=[a,b,c,d,e];for(let i=0;i<5;i++)h[i]+=next[i];
  }
  return hexWords(h);
}
function gitBlob(bytes) {
  const prefix=utf8("blob "+bytes.length+"\0"), whole=new Uint8Array(prefix.length+bytes.length);
  whole.set(prefix);whole.set(bytes,prefix.length);return sha1(whole);
}
