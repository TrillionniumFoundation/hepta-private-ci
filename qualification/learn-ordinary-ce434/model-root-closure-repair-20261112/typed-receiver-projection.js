// Exact scoped transliteration for source comparison only. Original Python remains the gate.
return (function makeTypedProjection() {
 const esc = s => s.replace(/[.*+?^${}()|[\]\\]/g,"\\$&");
 function end(code,start,opening,closing){let d=0;for(let i=start;i<code.length;i++){if(code[i]===opening)d++;else if(code[i]===closing){d--;if(d===0)return i;}}throw Error("unbalanced Rust authority context");}
 function aliases(code,target){const out=new Set();for(const m of code.matchAll(new RegExp("\\b"+esc(target)+"\\s+as\\s+(\\w+)","g")))out.add(m[1]);for(const m of code.matchAll(new RegExp("\\btype\\s+(\\w+)\\s*=\\s*(?:\\w+::)*"+esc(target)+"\\s*;","g")))out.add(m[1]);return out;}
 function normalized(code,target,al=[]){const names=new Set([...al,...aliases(code,target)]);for(const a of names)code=code.replace(new RegExp("\\b"+esc(a)+"\\b","g"),()=>target);return code;}
 function type(raw,target){if(new RegExp("\\b"+esc(target)+"\\b").test(raw))return target;const n=raw.match(/\b[A-Za-z_]\w*\b/g)||[];const names=n.filter(x=>!["mut","pub","crate","self","super"].includes(x));return names.at(-1)??null;}
 function fields(index,target){const as=new Set([target]);while(true){const added=new Set();for(const code of Object.values(index))for(const n of as)for(const a of aliases(code,n))added.add(a);if([...added].every(x=>as.has(x)))break;for(const x of added)as.add(x);}
 const out=new Map();out.aliases=new Set([...as].filter(x=>x!==target));
 for(let code of Object.values(index)){code=normalized(code,target,out.aliases);if(!code.includes(target))continue;for(const d of code.matchAll(/\bstruct\s+(\w+)(?:\s*<[^{};]*>)?\s*\{/g)){const e=end(code,d.index+d[0].length-1,"{","}");for(const f of code.slice(d.index+d[0].length,e).matchAll(/\b(\w+)\s*:\s*([^,;{}]+)/g)){if(type(f[2],target)===target)out.set(d[1]+"."+f[1],target);}}}return out;
 }
 function implOwner(code,pos){let owner=null;for(const m of code.slice(0,pos).matchAll(/\bimpl(?:\s*<[^{}]*>)?\s+(?:[\w:]+(?:\s*<[^{}]*>)?\s+for\s+)?([\w:]+)(?:\s*<[^{}]*>)?\s*\{/g)){if(end(code,m.index+m[0].length-1,"{","}")>=pos)owner=m[1].split("::").at(-1);}return owner;}
 function functionStart(code,pos){let start=0;for(const m of code.slice(0,pos).matchAll(/\bfn\s+\w+/g)){const o=code.indexOf("(",m.index+m[0].length);if(o<0)continue;const c=end(code,o,"(",")"),brace=code.indexOf("{",c),semi=code.indexOf(";",c);if(brace>=0&&(semi<0||brace<semi)&&end(code,brace,"{","}")>=pos)start=m.index;}return start;}
 function receiverType(r,b,o,f){const ps=r.replace(/\s+/g,"").split(".");let cur=ps[0]==="self"?o:b.get(ps[0]);for(const p of ps.slice(1))cur=cur?f.get(cur+"."+p):null;return cur??null;}
 function bindings(code,pos,target,owner,f){const scope=code.slice(functionStart(code,pos),pos),b=new Map();for(const p of scope.matchAll(/\b(\w+)\s*:\s*([^,;={}]+)/g))b.set(p[1],type(p[2],target));for(const a of scope.matchAll(/\blet\s+(?:mut\s+)?(\w+)(?:\s*:\s*([^=;]+))?\s*=\s*([^;]+)/g)){const [_,name,annotation,expr]=a;if(annotation){b.set(name,type(annotation,target));continue;}
 const cloned=expr.match(/^\s*(?:std\s*::\s*(?:sync|rc)\s*::\s*)?(?:Arc|Rc)\s*::\s*clone\s*\(/);
 if(cloned){const arg=expr.slice(cloned[0].length).match(/^\s*&?\s*((?:self|[A-Za-z_]\w*)(?:\s*\.\s*\w+)*)\s*\)\s*$/);b.set(name,arg?receiverType(arg[1],b,owner,f):null);continue;}
 const construct=expr.match(/^(?:[A-Za-z_]\w*::)*([A-Za-z_]\w*)\s*::\s*\w+\s*\(/);if(construct){b.set(name,construct[1]);continue;}
 const alias=expr.match(/^\s*&?\s*(?:mut\s+)?((?:[A-Za-z_]\w*)(?:\s*\.\s*\w+)*?)(?:\s*\.\s*(?:clone|as_ref|borrow|deref)\s*\(\s*\))?\s*$/);b.set(name,alias?receiverType(alias[1],b,owner,f):null);}
 return b;
 }
 function has(code,target,method,f){code=normalized(code,target,f.aliases);const types=new Set([target,...[...f.keys()].map(k=>k.slice(0,k.lastIndexOf(".")))]);if(![...types].some(n=>new RegExp("\\b"+esc(n)+"\\b").test(code)))return false;
 let found=new RegExp("\\b"+esc(target)+"\\s*::\\s*"+esc(method)+"\\s*\\(").test(code);
 for(const c of code.matchAll(new RegExp("\\.\\s*"+esc(method)+"\\s*\\(","g"))){const owner=implOwner(code,c.index),b=bindings(code,c.index,target,owner,f),r=code.slice(0,c.index).match(/\b(?:self|[A-Za-z_]\w*)(?:\s*\.\s*\w+)*\s*$/);const resolved=r?receiverType(r[0],b,owner,f):null;if(resolved===target)found=true;else if(resolved===null)throw Error("unresolved "+target+"::"+method+" receiver="+(r?.[0]??"(expression)")+" at "+c.index);}
 return found;
 }
 function check(boundaries,index){const result=[];for(const row of boundaries){let observed=[],errors=[],f;try{f=row.receiver_type?fields(index,row.receiver_type):null;}catch(e){errors.push(String(e));}
 if(!errors.length)for(const [path,code]of Object.entries(index)){if(path===row.definition_path)continue;try{let matches=row.receiver_type?(row.receiver_methods??[row.symbol.split("::").at(-1)]).some(m=>has(code,row.receiver_type,m,f)):new RegExp(row.call_pattern??esc(row.symbol)+"\\s*\\(").test(code);if(matches)observed.push(path);}catch(e){errors.push({path,error:String(e)});}}
 const expected=new Set(row.product_callers),seen=new Set(observed);result.push({id:row.id,observed,missing:[...expected].filter(x=>!seen.has(x)),unexpected:[...seen].filter(x=>!expected.has(x)),errors,aliases:f?[...f.aliases]:[]});}return result;}
 return {check,fields,has,bindings,implOwner,functionStart,normalized};
})();
