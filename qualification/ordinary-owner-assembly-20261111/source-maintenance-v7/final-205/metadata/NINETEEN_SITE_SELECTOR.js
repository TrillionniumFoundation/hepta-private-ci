return function sampleActualSharedGuardSuccessors(recipe, sources, api) {
 const clone=x=>JSON.parse(JSON.stringify(x));
 const assert=(x,m)=>{if(!x)throw Error(m);};
 const R=api.R,L=api.L;
 function rawLiteral(raw,desired) {
  if(raw.includes(desired))return desired;
  const hits=L.matches(desired,raw);
  assert(hits.length===1,"raw desired has no unique same-token actual source: "+desired);
  return hits[0].text;
 }
 function actualSelector(code,desired) {
  const direct=R.positions(code,desired);
  if(direct.length===1)return {text:desired,start:direct[0]};
  assert(direct.length===0,"duplicate actual selector "+desired);
  const hits=L.matches(desired,code);
  assert(hits.length===1,"masked selector has no unique source "+desired);
  return {text:hits[0].text,start:hits[0].start};
 }
 function item(code,desired) {
  const a=actualSelector(code,desired),end=R.itemEnd(code,a.start);
  assert(end!==null,"unterminated actual item "+desired);
  return {selector:a.text,start:a.start,end,body:code.slice(a.start,end+1)};
 }
 function lines(body) {
  return body.split("\n").map(x=>x.trim()).filter(x=>x.length>0);
 }
 function topLevel(body) {
  const out=[];
  for(const marker of lines(body)) {
   if(!/[A-Za-z_]/.test(marker)||/^[A-Za-z_]\w*$/.test(marker))continue;
   const hits=R.positions(body,marker);
   if(hits.length!==1)continue;
   const prefix=body.slice(0,hits[0]);
   const depth=(prefix.match(/\{/g)||[]).length-(prefix.match(/\}/g)||[]).length;
   if(depth===1&&!out.includes(marker))out.push(marker);
  }
  return out;
 }
 const changes=[],proofs=[];
 for(const record of recipe.rows) {
  const src=sources[record.path];
  assert(src&&typeof src.raw==="string","missing actual source "+record.path);
  assert(api.gitBlob(src.raw)===src.pin,"actual source hash "+record.path);
  assert(api.fingerprint(record.old_row)===record.expected_full_old_row_fingerprint,"old row fingerprint "+record.origin);
  const old=record.old_row,next=clone(old),code=R.code(src.raw),mapped=[];
  if(!record.no_source_obligation_change) {
   for(const pair of record.raw_replacements??[]) {
    const indices=next.required.map((x,i)=>x===pair[0]?i:-1).filter(i=>i>=0);
    assert(indices.length===1,"exact raw requirement predecessor "+pair[0]);
    const actual=rawLiteral(src.raw,pair[1]);
    next.required[indices[0]]=actual;
    mapped.push({field:"required["+indices[0]+"]",before:pair[0],after:actual,classification:"author-semantic actual-storage successor"});
   }
   for(const desired of record.raw_additions??[]) {
    const actual=rawLiteral(src.raw,desired);
    if(!next.required.includes(actual))next.required.push(actual);
    mapped.push({field:"required",after:actual,classification:"additional actual-custody requirement"});
   }
   for(const pair of record.function_replacements??[]) {
    const hits=(next.required_function_order??[]).filter(x=>x.function===pair[0]);
    assert(hits.length===1,"old actual function selector "+pair[0]);
    hits[0].function=pair[1];
    mapped.push({field:"required_function_order.function",before:pair[0],after:pair[1],classification:"reviewed private-helper obligation migration"});
   }
   for(const name of record.resample_functions??[]) {
    const hits=(next.required_function_order??[]).filter(x=>x.function===name);
    assert(hits.length===1,"actual function guard selector "+name);
    const entry=hits[0],previous=clone(entry),extent=R.fnExtent(code,name);
    entry.sequence=lines(extent.body);
    if(Object.hasOwn(entry,"top_level"))entry.top_level=topLevel(extent.body);
    mapped.push({field:"required_function_order",function:name,before:previous,after:clone(entry),
      source_start:extent.start,source_end_inclusive:extent.end,
      masked_body_sha256:api.sha256(api.utf8(extent.body)),
      raw_body_sha256:api.sha256(api.utf8(src.raw.slice(extent.start,extent.end+1))),
      classification:"complete actual same-source function; author-semantic recipe controls changed obligations"});
   }
   const oldOrders=clone(next.required_order??[]),removed=new Set((record.removed_orders??[]).map(x=>x.index));
   const repl=new Map((record.order_replacements??[]).map(x=>[x.index,x]));
   const refresh=new Set(record.resample_orders??[]);
   next.required_order=oldOrders.flatMap((sequence,index)=>{
    if(removed.has(index)) {
     const specification=record.removed_orders.find(x=>x.index===index);
     assert(sequence[0]===specification.old_selector,"obsolete order origin mismatch");
     assert(R.positions(code,specification.old_selector).length===0,"obsolete item still exists in actual source");
     mapped.push({field:"required_order["+index+"]",before:sequence,mapped_to:specification.mapped_to,
       classification:"obsolete private representation removed; physical ownership obligation mapped to actual complete constructor/cell/join"});
     return [];
    }
    if(refresh.has(index)||repl.has(index)) {
     const specification=repl.get(index);
     if(specification)assert(sequence[0]===specification.old_selector,"old generic item selector mismatch");
     const desired=specification?specification.new_selector:sequence[0],x=item(code,desired);
     const after=[x.selector,x.body.slice(x.selector.length)];
     mapped.push({field:"required_order["+index+"]",before:sequence,after,
       source_start:x.start,source_end_inclusive:x.end,masked_body_sha256:api.sha256(api.utf8(x.body)),
       classification:"complete actual type/impl/generic function"});
     return [after];
    }
    return [sequence];
   });
   for(const desired of record.required_actual_items??[]) {
    const x=item(code,desired);
    if(next.required_order.some(s=>s[0]===x.selector||s[0].startsWith(x.selector)||x.selector.startsWith(s[0])))continue;
    const sequence=[x.selector,x.body.slice(x.selector.length)];
    next.required_order.push(sequence);
    mapped.push({field:"required_order",after:sequence,source_start:x.start,source_end_inclusive:x.end,
      classification:"additional complete actual same-handle storage/Drop/function"});
   }
  }
  assert(next.path===old.path&&api.fingerprint(next.forbidden)===api.fingerprint(old.forbidden),"forbidden/path changed");
  const projection=R.project(next,src.raw);
  const changed=api.fingerprint(next)!==api.fingerprint(old);
  const out={selector:{origin:record.origin,path:record.path,expected_full_row_fingerprint:record.expected_full_old_row_fingerprint},
   old_row:clone(old),new_row:next,expected_new_full_row_fingerprint:api.fingerprint(next),
   source_post:{pin:src.pin,bytes:api.utf8(src.raw).length,sha256:api.sha256(api.utf8(src.raw))},
   semantic_recipe_mapping:record.mapping,changed,field_mapping:mapped,
   preserved_forbidden:true,preserved_distinct_conjunct:true,projection};
  if(changed)changes.push(out);
  proofs.push({origin:record.origin,path:record.path,pin:src.pin,changed,
   old_fingerprint:record.expected_full_old_row_fingerprint,new_fingerprint:api.fingerprint(next),
   function_guards:(next.required_function_order??[]).length,complete_orders:(next.required_order??[]).length,
   mappings:mapped.length,local_projection:"matched",original_checker_executed:false});
 }
 return {schema_version:1,kind:"source_bound_shared_custody_guard_successor",changes,proofs,
  counts:{rows:recipe.rows.length,changed:changes.length,unchanged:proofs.filter(x=>!x.changed).length},
  original_checker_executed:false,formatter_or_compiler_claim:false};
};