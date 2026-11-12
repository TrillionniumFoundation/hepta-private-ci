
function parseRegistry(text){
 let i=0;const root={},arrayPaths=new Set();
 function ws(){for(;;){while(i<text.length&&/\s/.test(text[i]))i++;if(text[i]==="#"){while(i<text.length&&text[i]!=="\n")i++;}else return;}}
 function key(){if(text[i]==='"'||text[i]==="'"){const v=value();if(typeof v!=="string")throw Error("non-string quoted key");return v;}const m=/^[A-Za-z0-9_-]+/.exec(text.slice(i));if(!m)throw Error("unsupported TOML key at "+i);i+=m[0].length;return m[0];}
 function value(){
  ws();const c=text[i];
  if(c==='"'){const start=i++;for(;;){if(i>=text.length)throw Error("unterminated string");if(text[i]==="\\"){i+=2;continue;}if(text[i++]==='"')break;}const s=text.slice(start,i);return JSON.parse(s);}
  if(c==="'"){const start=++i;while(i<text.length&&text[i]!=="'"){if(text[i]==="\n"||text[i]==="\r")throw Error("unsupported multiline literal");i++;}if(i>=text.length)throw Error("unterminated literal");const s=text.slice(start,i);i++;return s;}
  if(c==="["){i++;const a=[];ws();while(text[i]!=="]"){a.push(value());ws();if(text[i]===","){i++;ws();if(text[i]==="]")break;}else if(text[i]!=="]")throw Error("array separator at "+i);}i++;return a;}
  if(c==="{"){i++;const o={};ws();while(text[i]!=="}"){const k=key();ws();if(text[i++]!=="=")throw Error("inline assignment");if(Object.prototype.hasOwnProperty.call(o,k))throw Error("duplicate inline key");o[k]=value();ws();if(text[i]===","){i++;ws();if(text[i]==="}")break;}else if(text[i]!=="}")throw Error("inline table separator at "+i);}i++;return o;}
  const b=/^(true|false)(?=$|[\s,\]}#])/.exec(text.slice(i));if(b){i+=b[0].length;return b[0]==="true";}
  const n=/^-?(?:0|[1-9][0-9]*)(?=$|[\s,\]}#])/.exec(text.slice(i));if(n){i+=n[0].length;return Number(n[0]);}
  throw Error("unsupported TOML value at "+i+" "+text.slice(i,i+50));
 }
 let current=root;
 while(true){ws();if(i>=text.length)break;
  if(text[i]==="["){
   const isArray=text[i+1]==="[";i+=isArray?2:1;const parts=[key()];while(text[i]==="."){i++;parts.push(key());}if(text.slice(i,i+(isArray?2:1))!==(isArray?"]]":"]"))throw Error("bad table header");i+=isArray?2:1;
   let node=root;for(let j=0;j<parts.length;j++){const k=parts[j],last=j===parts.length-1;if(last&&isArray){if(!Object.prototype.hasOwnProperty.call(node,k))node[k]=[];if(!Array.isArray(node[k]))throw Error("table-array collision");const obj={};node[k].push(obj);node=obj;arrayPaths.add(parts.join("."));}
    else{if(!Object.prototype.hasOwnProperty.call(node,k))node[k]={};node=node[k];if(Array.isArray(node)){if(!node.length)throw Error("empty array parent");node=node[node.length-1];}if(!node||typeof node!=="object")throw Error("scalar table collision");}}
   current=node;
  }else{
   const k=key();while(text[i]===" "||text[i]==="\t")i++;if(text[i++]!=="=")throw Error("expected assignment at "+i);if(Object.prototype.hasOwnProperty.call(current,k))throw Error("duplicate assignment "+k);current[k]=value();
  }
  while(text[i]===" "||text[i]==="\t"||text[i]==="\r")i++;if(text[i]==="#"){while(i<text.length&&text[i]!=="\n")i++;}if(i<text.length&&text[i]!=="\n")throw Error("trailing TOML data at "+i);
 }
 return root;
}
return {parseRegistry};
