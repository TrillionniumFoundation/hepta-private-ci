
function gunzip(bytes,maxOutput){
 if(bytes[0]!==31||bytes[1]!==139||bytes[2]!==8)throw Error("not gzip DEFLATE");
 const flags=bytes[3];if(flags&224)throw Error("reserved gzip flags");let p=10;
 if(flags&4){const n=bytes[p]|bytes[p+1]<<8;p+=2+n;}
 if(flags&8){while(p<bytes.length&&bytes[p++]!==0){}}
 if(flags&16){while(p<bytes.length&&bytes[p++]!==0){}}
 if(flags&2)p+=2;
 const end=bytes.length-8;if(p>end)throw Error("truncated gzip header");
 let bit=p*8;const output=[];
 function read(n){if(bit+n>end*8)throw Error("DEFLATE truncated");let v=0;for(let i=0;i<n;i++,bit++)v|=((bytes[bit>>3]>>(bit&7))&1)<<i;return v;}
 function tree(lengths){
  let max=0;const counts=new Array(16).fill(0);for(const n of lengths){if(n<0||n>15)throw Error("invalid code length");if(n){counts[n]++;max=Math.max(max,n);}}
  if(!max) return {max:0,maps:[]};
  let available=1;for(let n=1;n<=15;n++){available=(available<<1)-counts[n];if(available<0)throw Error("oversubscribed Huffman");}
  const next=new Array(16).fill(0),maps=Array.from({length:16},()=>new Map());let code=0;
  for(let n=1;n<=15;n++){code=(code+counts[n-1])<<1;next[n]=code;}
  for(let sym=0;sym<lengths.length;sym++){const n=lengths[sym];if(!n)continue;const c=next[n]++;let rev=0;for(let j=0;j<n;j++)rev=(rev<<1)|((c>>j)&1);maps[n].set(rev,sym);}
  return{max,maps};
 }
 function decode(t){if(!t.max)throw Error("empty Huffman tree used");let c=0;for(let n=1;n<=t.max;n++){c|=read(1)<<(n-1);const sym=t.maps[n].get(c);if(sym!==undefined)return sym;}throw Error("invalid Huffman code");}
 const lengths=[3,4,5,6,7,8,9,10,11,13,15,17,19,23,27,31,35,43,51,59,67,83,99,115,131,163,195,227,258];
 const extraL=[0,0,0,0,0,0,0,0,1,1,1,1,2,2,2,2,3,3,3,3,4,4,4,4,5,5,5,5,0];
 const distances=[1,2,3,4,5,7,9,13,17,25,33,49,65,97,129,193,257,385,513,769,1025,1537,2049,3073,4097,6145,8193,12289,16385,24577];
 const extraD=[0,0,0,0,1,1,2,2,3,3,4,4,5,5,6,6,7,7,8,8,9,9,10,10,11,11,12,12,13,13];
 let final=0;
 do{
  final=read(1);const type=read(2);
  if(type===0){bit=(bit+7)&~7;const n=read(16),inv=read(16);if((n^inv)!==65535)throw Error("bad stored block length");for(let i=0;i<n;i++)output.push(read(8));}
  else if(type===1||type===2){
   let lt,dt;
   if(type===1){lt=tree(Array.from({length:288},(_,i)=>i<144?8:i<256?9:i<280?7:8));dt=tree(new Array(32).fill(5));}
   else{
    const nl=read(5)+257,nd=read(5)+1,nc=read(4)+4;
    const order=[16,17,18,0,8,7,9,6,10,5,11,4,12,3,13,2,14,1,15],cl=new Array(19).fill(0);
    for(let i=0;i<nc;i++)cl[order[i]]=read(3);
    const ct=tree(cl),all=[];
    while(all.length<nl+nd){const s=decode(ct);if(s<=15)all.push(s);else if(s===16){if(!all.length)throw Error("repeat without previous code");const n=read(2)+3,v=all[all.length-1];for(let i=0;i<n;i++)all.push(v);}else if(s===17){const n=read(3)+3;for(let i=0;i<n;i++)all.push(0);}else if(s===18){const n=read(7)+11;for(let i=0;i<n;i++)all.push(0);}else throw Error("invalid code length symbol");if(all.length>nl+nd)throw Error("too many code lengths");}
    if(!all[256])throw Error("missing end-of-block");lt=tree(all.slice(0,nl));dt=tree(all.slice(nl));
   }
   for(;;){const s=decode(lt);if(s<256)output.push(s);else if(s===256)break;else{const j=s-257;if(j<0||j>=lengths.length)throw Error("reserved length symbol");const n=lengths[j]+read(extraL[j]),d=decode(dt);if(d>=distances.length)throw Error("reserved distance symbol");const dist=distances[d]+read(extraD[d]);if(dist>output.length)throw Error("distance beyond output");for(let i=0;i<n;i++)output.push(output[output.length-dist]);}if(output.length>maxOutput)throw Error("output budget");}
  }else throw Error("reserved DEFLATE type");
  if(output.length>maxOutput)throw Error("output budget");
 }while(!final);
 if(Math.ceil(bit/8)!==end)throw Error("extra gzip payload");
 const le=(off)=>(bytes[off]|(bytes[off+1]<<8)|(bytes[off+2]<<16)|(bytes[off+3]<<24))>>>0;
 let crc=0xffffffff;for(const b of output){crc^=b;for(let j=0;j<8;j++)crc=(crc>>>1)^((crc&1)?0xedb88320:0);}
 crc=(crc^0xffffffff)>>>0;if(crc!==le(end))throw Error("CRC32 mismatch");if((output.length>>>0)!==le(end+4))throw Error("ISIZE mismatch");
 return output;
}
function utf8decode(bytes){
 let text="",units=[];function flush(){if(units.length){text+=String.fromCharCode(...units);units=[];}}
 for(let i=0;i<bytes.length;){const first=bytes[i++];let cp,n,min;if(first<128){cp=first;n=0;min=0;}else if(first>=194&&first<=223){cp=first&31;n=1;min=128;}else if(first>=224&&first<=239){cp=first&15;n=2;min=2048;}else if(first>=240&&first<=244){cp=first&7;n=3;min=65536;}else throw Error("invalid UTF8 leading");if(i+n>bytes.length)throw Error("truncated UTF8");for(let j=0;j<n;j++){const b=bytes[i++];if((b&192)!==128)throw Error("invalid UTF8 trailing");cp=(cp<<6)|(b&63);}if(cp<min||cp>0x10ffff||(cp>=0xd800&&cp<=0xdfff))throw Error("invalid UTF8 scalar");if(cp<65536)units.push(cp);else{cp-=65536;units.push(0xd800+(cp>>10),0xdc00+(cp&1023));}if(units.length>4096)flush();}
 flush();return text;
}
return {gunzip,utf8decode};
