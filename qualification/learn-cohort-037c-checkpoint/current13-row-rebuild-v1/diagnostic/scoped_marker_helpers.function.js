return (function scopedHelpers(){
 function parseSelectedRow(text) {
  let out={},target=out;
  for(const raw of text.split("\n")){const line=raw.trim();if(!line||line.startsWith("#"))continue;
   if(line==="[[protected_file]]"||line==="[[boundary]]"){target=out;continue;}
   if(line==="[[protected_file.required_function_order]]"){out.required_function_order??=[];target={};out.required_function_order.push(target);continue;}
   const m=/^([A-Za-z_]\w*) = (.*)$/.exec(line);if(!m||Object.hasOwn(target,m[1]))throw Error("unsupported or duplicate TOML row line "+line.slice(0,120));
   try{target[m[1]]=JSON.parse(m[2]);}catch(e){throw Error("not exact JSON-compatible TOML subset "+m[1]+": "+e);}
  }return out;
 }
 function stripRust(source) {
  if([...source].some(x=>x.length>1))throw Error("supplementary code point requires original Python scanner");
  const output=source.split("");let index=0,state="code",depth=0,hashes=0;
  while(index<source.length){const c=source[index],n=source[index+1]||"";
   if(state==="code"){if(c==="/"&&n==="/"){output[index]=output[index+1]=" ";index+=2;state="line";continue;}
    if(c==="/"&&n==="*"){output[index]=output[index+1]=" ";index+=2;depth=1;state="block";continue;}
    if(c==='"'){output[index++]=" ";state="string";continue;}
    if(c==="'"&&index+2<source.length&&(source[index+1]==="\\"?index+3<source.length&&source[index+3]==="'":source[index+2]==="'")){output[index++]=" ";state="char";continue;}
    if(c==="r"){const m=/^r(#{0,255})"/.exec(source.slice(index));if(m){hashes=m[1].length;for(let j=0;j<m[0].length;j++)output[index+j]=" ";index+=m[0].length;state="raw";continue;}}
    index++;continue;
   }
   if(state==="line"){if(c==="\n")state="code";else output[index]=" ";index++;continue;}
   if(state==="block"){if(c==="/"&&n==="*"){output[index]=output[index+1]=" ";depth++;index+=2;}else if(c==="*"&&n==="/"){output[index]=output[index+1]=" ";depth--;index+=2;if(!depth)state="code";}else{if(c!=="\n")output[index]=" ";index++;}continue;}
   if(state==="string"||state==="char"){const end=state==="string"?'"':"'";if(c==="\\"){output[index]=" ";if(index+1<source.length){if(n!=="\n")output[index+1]=" ";index+=2;}else index++;}else if(c===end){output[index++]=" ";state="code";}else{if(c!=="\n")output[index]=" ";index++;}continue;}
   if(state==="raw"){const end='"'+"#".repeat(hashes);if(source.startsWith(end,index)){for(let j=0;j<end.length;j++)output[index+j]=" ";index+=end.length;state="code";}else{if(c!=="\n")output[index]=" ";index++;}continue;}
   throw Error("mask state");
  }return output.join("");
 }
 function span(code, marker) {
  const start=code.indexOf(marker);if(start<0||code.indexOf(marker,start+marker.length)>=0)throw Error("nonunique function "+marker);
  let par=0,br=0,opening=-1;
  for(let i=start;i<code.length;i++){if(code[i]==="(")par++;else if(code[i]===")"&&par)par--;else if(code[i]==="[")br++;else if(code[i]==="]"&&br)br--;else if(!par&&!br&&code[i]==="{"){opening=i;break;}else if(!par&&!br&&code[i]===";")throw Error("declaration has no body");}
  if(opening<0)throw Error("no opening");let depth=1,end=opening+1;for(;end<code.length;end++){if(code[end]==="{")depth++;else if(code[end]==="}"&&--depth===0)break;}if(depth)throw Error("unclosed function");return{start,opening,end,body:code.slice(start,end+1),inside:code.slice(opening+1,end).trim(),whole:code.slice(opening,end+1)};
 }
 function countText(s,x){return s.split(x).length-1;}
 function checkRow(row,source) {
  const code=stripRust(source),failures=[];
  for(const x of row.required||[])if(!source.includes(x))failures.push({kind:"required",marker:x});
  for(const x of row.forbidden||[]){const q=x.replace(/[.*+?^${}()|[\]\\]/g,"\\$&"),pattern=(/^\w/.test(x)?"(?<!\\w)":"")+q+(/\w$/.test(x)?"(?!\\w)":"");if(new RegExp(pattern).test(code))failures.push({kind:"forbidden",marker:x});}
  function ordered(s,sequence,label){let offset=0;for(const x of sequence){const i=s.indexOf(x,offset);if(i<0){failures.push({kind:"sequence",label,marker:x,offset});break;}offset=i+x.length;}}
  for(const q of row.required_order||[])ordered(code,q,"file");
  for(const f of row.required_function_order||[]){let p;try{p=span(code,f.function);}catch(e){failures.push({kind:"function",function:f.function,error:String(e)});continue;}
   ordered(p.body,f.sequence,f.function);
   for(const x of f.top_level||[]){const i=p.body.indexOf(x);if(i<0||countText(p.body,x)!==1){failures.push({kind:"top_level_unique",function:f.function,marker:x.slice(0,90)});continue;}const pre=p.body.slice(0,i),depth=countText(pre,"{")-countText(pre,"}");if(depth!==1)failures.push({kind:"top_level_depth",function:f.function,depth,marker:x.slice(0,90)});}
  }
  return failures;
 }
 function whitespaceAdapt(sequence,body,log,fn){
  let offset=0;return sequence.map(marker=>{let i=body.indexOf(marker,offset);if(i>=0){offset=i+marker.length;return marker;}
   const escaped=marker.split(/(\s+)/).filter(Boolean).map(x=>/^\s+$/.test(x)?"\\s+":x.replace(/[.*+?^${}()|[\]\\]/g,"\\$&")).join("");
   const r=new RegExp(escaped,"g");r.lastIndex=offset;const m=r.exec(body);if(!m)throw Error("old marker has semantic change: "+fn+" "+marker);
   const after=m[0];if(after.replace(/\s+/g," ")!==marker.replace(/\s+/g," "))throw Error("nonwhitespace adaptation");
   offset=m.index+after.length;log.push({function:fn,before:marker,after,reason:"actual existing code moved under Current/Page branches; whitespace only"});return after;});
 }
 return {parseSelectedRow,stripRust,span,checkRow,whitespaceAdapt,countText};
})();