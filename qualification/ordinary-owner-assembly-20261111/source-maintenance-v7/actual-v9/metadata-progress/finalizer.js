
return function actualSourceMetadataFinalizer(input, api) {
 const clone=x=>JSON.parse(JSON.stringify(x));
 const eq=(a,b)=>api.fingerprint(a)===api.fingerprint(b);
 const assert=(x,message)=>{if(!x)throw Error(message);};
 const p=clone(input.initial_plan);
 assert(p.counts.boundaries===1010&&p.counts.protected_conjuncts===598,"Exact prepared1010/598 plan required");
 assert(api.fingerprint(p.boundary_rows)==="7a4b0fe6ffc0876db2fc855d5bbd0b3f19ff73ff7e1d16b6f4e5fa363590a2a7","Exact semantic boundary plan");
 assert(api.fingerprint(p.protected_templates)==="71d9e19e2f4d42c8d700d607319506922b6c51d937b207b7818fd99917ca2e2a","Exact semantic protected plan");
 const bpos=new Map(p.boundary_rows.map((r,i)=>[r.id,i]));
 const gpos=new Map(p.protected_origins.map((r,i)=>[r.origin,i]));
 const receipts=[];
 function apply(stage,kind,c){
  const key=kind==="boundary"?c.selector.id:c.selector.origin;
  const at=(kind==="boundary"?bpos:gpos).get(key);
  assert(at!==undefined,"Missing immutable selector "+key);
  const rows=kind==="boundary"?p.boundary_rows:p.protected_templates;
  const old=rows[at];
  assert(eq(old,c.old_row),"Whole old row mismatch "+key);
  assert(api.fingerprint(old)===c.selector.expected_full_row_fingerprint,"Old fingerprint mismatch "+key);
  const next=clone(c.new_row);
  if(kind==="boundary"){
   const a=clone(old),b=clone(next);
   delete a.definition_markers;delete a.caller_markers;
   delete b.definition_markers;delete b.caller_markers;
   assert(eq(a,b),"Actual literal stage changes boundary authority fields "+key);
  }else{
   assert(old.path===next.path&&eq(old.forbidden,next.forbidden),"Path or forbidden changed "+key);
   assert(Array.isArray(next.required)&&Array.isArray(next.forbidden),"Missing mandatory guard arrays "+key);
   const allowed=new Set(["path","required","forbidden","required_order","required_function_order"]);
   assert(Object.keys(next).every(k=>allowed.has(k)),"Unexpected protected field "+key);
  }
  if(c.expected_new_full_row_fingerprint)assert(api.fingerprint(next)===c.expected_new_full_row_fingerprint,"New fingerprint mismatch "+key);
  rows[at]=next;
  receipts.push({stage,kind,key,row_index:at,before:api.fingerprint(old),after:api.fingerprint(next)});
 }
 for(const stage of input.stages){
  assert(typeof stage.pin==="string"&&stage.pin.length===40&&typeof stage.raw==="string","Stage pin/raw required");
  assert(api.gitBlob(stage.raw)===stage.pin,"Exact durable stage bytes "+stage.pin);
  const document=JSON.parse(stage.raw);let boundaries=[],guards=[];
  if(stage.shape==="boundary_updates")boundaries=Object.values(document.updates);
  else if(stage.shape==="guard_updates")guards=Object.values(document.updates);
  else if(stage.shape==="row_delta"){boundaries=document.boundary_changes||[];guards=document.protected_changes||[];}
  else throw Error("Unsupported exact stage schema "+stage.shape);
  for(const c of boundaries)apply(stage.pin,"boundary",c);
  for(const c of guards)apply(stage.pin,"protected",c);
 }
 const add={pin:input.outcome_annex.pin};
 assert(add.pin==="74aa68fe1d20a6bfea82ab7ef9e1644af5cb22d7"&&api.gitBlob(input.outcome_annex.raw)===add.pin,"Exact strengthened Outcome annex required");
 add.data=JSON.parse(input.outcome_annex.raw);
 assert(add.data.new_boundaries.length===1&&add.data.new_protected.length===2,"Outcome additive1/2 expected");
 const extra=add.data.new_boundaries[0];
 assert(extra.id==="same_actor_original_signed_outcome_data_into_original"&&!bpos.has(extra.id),"Outcome ID collision");
 assert(eq(add.data.required_boundary_ids_append,[extra.id]),"Outcome required/declaration mismatch");
 p.boundary_rows.push(clone(extra));p.required_boundary_ids.push(extra.id);
 p.boundary_origins.push({origin:add.pin+"#new_boundary:0",id:extra.id,original_identity:api.fingerprint(extra)});
 for(let i=0;i<add.data.new_protected.length;i++){
  const row=clone(add.data.new_protected[i]);
  assert(Array.isArray(row.required)&&Array.isArray(row.forbidden),"Outcome mandatory guard arrays");
  p.protected_templates.push(row);
  p.protected_origins.push({origin:add.pin+"#new_protected:"+i,path:row.path,original_identity:api.fingerprint(row),forbidden:clone(row.forbidden)});
 }
 assert(p.boundary_rows.length===1011&&p.protected_templates.length===600,"Final1011/600 expected");
 assert(new Set(p.required_boundary_ids).size===1011&&eq([...p.required_boundary_ids].sort(),p.boundary_rows.map(x=>x.id).sort()),"Complete required/declaration equality");
 assert(new Set(p.boundary_rows.map(x=>x.symbol)).size===1011,"Duplicate symbols");
 p.table_header.privileged_inventory.required_boundary_ids=[...p.required_boundary_ids];
 const rowsByPath={};
 for(const row of p.protected_templates)rowsByPath[row.path]=(rowsByPath[row.path]||0)+1;
 const result={table_header:p.table_header,boundaries:p.boundary_rows,protected_file:p.protected_templates,boundary_origins:p.boundary_origins,protected_origins:p.protected_origins,receipts,source_manifest:input.source_manifest,
  counts:{boundaries:1011,required_ids:1011,protected_conjuncts:600,distinct_paths:Object.keys(rowsByPath).length,duplicate_paths:Object.values(rowsByPath).filter(n=>n>1).length,max_conjuncts:Math.max(...Object.values(rowsByPath))},
  status:"source_bound_metadata_candidate_not_original_checker_qualification"};
 function value(v,depth=0){
  if(typeof v==="string")return JSON.stringify(v);
  if(typeof v==="number"||typeof v==="boolean")return String(v);
  if(Array.isArray(v)){
   if(v.length===0)return"[]";
   const pad="  ".repeat(depth+1);
   return "[\n"+v.map(x=>pad+value(x,depth+1)+",").join("\n")+"\n"+"  ".repeat(depth)+"]";
  }
  if(v&&typeof v==="object")return"{ "+Object.entries(v).map(([k,x])=>k+" = "+value(x,depth)).join(", ")+" }";
  throw Error("Unsupported TOML value");
 }
 function table(kind,row){
  let out="[["+kind+"]]\n";
  for(const[k,v]of Object.entries(row)){
   if(k==="required_function_order")continue;
   out+=k+" = "+value(v)+"\n";
  }
  if(Object.hasOwn(row,"required_function_order")){
   if(!row.required_function_order.length)out+="required_function_order = []\n";
   else for(const f of row.required_function_order){
    out+="\n[["+kind+".required_function_order]]\n";
    for(const[k,v]of Object.entries(f))out+=k+" = "+value(v)+"\n";
   }
  }
  return out+"\n";
 }
 function render(){
  assert(api.gitBlob(input.base_raw)==="0f0cc13187dd3f9a09f78ef9ce33f52009c96678","Exact original table required");
  const parsed=api.parseToml(input.base_raw),base=parsed.value;
  assert(base.boundary.length===789&&base.protected_file.length===512,"Exact original row counts");
  const oldHeader=clone(base);delete oldHeader.boundary;delete oldHeader.protected_file;
  const newHeader=clone(result.table_header);
  delete oldHeader.privileged_inventory.required_boundary_ids;
  delete newHeader.privileged_inventory.required_boundary_ids;
  assert(eq(oldHeader,newHeader),"Original non-ID header changed");
  for(let i=0;i<512;i++)assert(base.protected_file[i].path===result.protected_file[i].path&&eq(base.protected_file[i].forbidden,result.protected_file[i].forbidden),"Original conjunct weakened "+i);
  for(let i=0;i<789;i++)assert(base.boundary[i].id===result.boundaries[i].id,"Original boundary order/ID changed "+i);
  const ids=parsed.fields.filter(f=>f.key==="required_boundary_ids");
  assert(ids.length===1&&ids[0].value_end<=parsed.rows[0].start,"Unique original header ID field");
  const ops=[];
  const id=ids[0];
  ops.push({kind:"replace",label:"append all actual required IDs",old:input.base_raw.slice(id.value_start,id.value_end),new:value(result.table_header.privileged_inventory.required_boundary_ids)});
  let kept=0,changed=0;
  for(const r of parsed.rows){
   const before=base[r.kind][r.index];
   const after=(r.kind==="boundary"?result.boundaries:result.protected_file)[r.index];
   if(eq(before,after)){kept++;continue;}
   changed++;
   ops.push({kind:"replace",label:r.kind+":"+r.index,old:input.base_raw.slice(r.start,r.end),new:table(r.kind,after)});
  }
  function count(s,needle){let n=0,at=0;while((at=s.indexOf(needle,at))>=0){n++;at+=needle.length;}return n;}
  let output=input.base_raw;
  for(const op of ops){assert(op.old&&count(output,op.old)===1,"Unique forward "+op.label);output=output.replace(op.old,op.new);}
  const last=parsed.rows.at(-1),lastBefore=base[last.kind][last.index],lastAfter=(last.kind==="boundary"?result.boundaries:result.protected_file)[last.index];
  const tail=eq(lastBefore,lastAfter)?input.base_raw.slice(last.start,last.end):table(last.kind,lastAfter);
  assert(output.endsWith(tail)&&count(output,tail)===1,"Unique original EOF owner");
  const additions=result.boundaries.slice(789).map(r=>table("boundary",r)).join("")+result.protected_file.slice(512).map(r=>table("protected_file",r)).join("");
  const append={kind:"replace",label:"append additive actual boundaries and independent protected conjuncts",old:tail,new:tail+additions};
  output=output.slice(0,-tail.length)+append.new;ops.push(append);
  let reverse=output;
  for(const op of [...ops].reverse()){assert(count(reverse,op.new)===1,"Unique reverse "+op.label);reverse=reverse.replace(op.new,op.old);}
  assert(reverse===input.base_raw,"Exact full reverse");
  const expected={...clone(result.table_header),boundary:result.boundaries,protected_file:result.protected_file};
  assert(eq(api.parseToml(output).value,expected),"Rendered semantic roundtrip");
  return{raw:output,git_blob:api.gitBlob(output),ops,kept_original_rows_exact:kept,changed_original_rows:changed,exact_reverse:true,parsed_roundtrip:true};
 }
 return{result,render};
};
