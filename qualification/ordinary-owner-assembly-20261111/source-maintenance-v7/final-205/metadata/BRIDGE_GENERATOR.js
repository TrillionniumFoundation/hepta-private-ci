return function deriveMetadataExactBridge(preRaw, postRaw, api) {
 const assert=(ok,message)=>{if(!ok)throw Error(message);};
 const pre=api.parseToml(preRaw),post=api.parseToml(postRaw);
 const eq=(a,b)=>api.fingerprint(a)===api.fingerprint(b);
 const count=(s,n)=>{let at=0,total=0;while((at=s.indexOf(n,at))!==-1){total++;at+=n.length;}return total;};
 assert(post.rows.length>=pre.rows.length,"Rows may not be removed");
 const originalRows=[],fieldChanges=[],ops=[];
 const headerPre=preRaw.slice(0,pre.rows[0].start),headerPost=postRaw.slice(0,post.rows[0].start);
 const ph={...pre.value},qh={...post.value};delete ph.boundary;delete ph.protected_file;delete qh.boundary;delete qh.protected_file;
 const oldIds=ph.privileged_inventory.required_boundary_ids,newIds=qh.privileged_inventory.required_boundary_ids;
 assert(oldIds.every((id,i)=>newIds[i]===id),"Required IDs must remain an exact prefix");
 delete ph.privileged_inventory;delete qh.privileged_inventory;
 assert(eq(ph,qh),"Other header sections changed");
 const pi={...pre.value.privileged_inventory},qi={...post.value.privileged_inventory};delete pi.required_boundary_ids;delete qi.required_boundary_ids;
 assert(eq(pi,qi),"Other inventory fields changed");
 if(headerPre!==headerPost)ops.push({kind:"replace",label:"header:append-only-required-IDs",old:headerPre,new:headerPost});
 for(let ordinal=0;ordinal<pre.rows.length;ordinal++){
  const a=pre.rows[ordinal],b=post.rows[ordinal];
  assert(a.kind===b.kind&&a.index===b.index,"Original raw row order changed");
  const x=pre.value[a.kind][a.index],y=post.value[b.kind][b.index];
  const identity=a.kind==="boundary"?x.id:x.path;
  assert(identity===(a.kind==="boundary"?y.id:y.path),"Original row identity changed");
  if(a.kind==="protected_file")assert(eq(x.forbidden,y.forbidden),"Forbidden weakened");
  const old=preRaw.slice(a.start,a.end),next=postRaw.slice(b.start,b.end);
  const fields=[...new Set([...Object.keys(x),...Object.keys(y)])].filter(k=>!eq({present:Object.hasOwn(x,k),value:x[k]},{present:Object.hasOwn(y,k),value:y[k]}));
  const record={kind:a.kind,index:a.index,ordinal,identity,pre_range:[a.start,a.end],post_range:[b.start,b.end],pre_row_fingerprint:api.fingerprint(x),post_row_fingerprint:api.fingerprint(y),pre_raw_sha256:api.sha256(api.utf8(old)),post_raw_sha256:api.sha256(api.utf8(next)),raw_preserved:old===next,changed_fields:fields};
  originalRows.push(record);
  if(fields.length)fieldChanges.push({...record,fields:fields.map(k=>({field:k,old_present:Object.hasOwn(x,k),new_present:Object.hasOwn(y,k),old_value:x[k],new_value:y[k]}))});
  if(old!==next)ops.push({kind:"replace",label:a.kind+":"+a.index,old,new:next});
 }
 const lastPost=post.rows[pre.rows.length-1],tail=postRaw.slice(lastPost.start,lastPost.end),addition=postRaw.slice(lastPost.end);
 if(addition)ops.push({kind:"replace",label:"append-independent-actual-boundaries-and-conjuncts",old:tail,new:tail+addition});
 let current=preRaw;
 for(const [i,op] of ops.entries()){
  assert(op.old&&count(current,op.old)===1,"Unique forward "+op.label);
  op.ordinal=i;op.forward_offset=current.indexOf(op.old);op.old_bytes=api.utf8(op.old).length;op.new_bytes=api.utf8(op.new).length;
  op.old_sha256=api.sha256(api.utf8(op.old));op.new_sha256=api.sha256(api.utf8(op.new));
  current=current.replace(op.old,op.new);
 }
 assert(current===postRaw,"Exact complete forward");
 for(const op of [...ops].reverse()){
  assert(count(current,op.new)===1,"Unique reverse "+op.label);
  op.reverse_offset=current.indexOf(op.new);current=current.replace(op.new,op.old);
 }
 assert(current===preRaw,"Exact complete reverse");
 return {schema_version:1,kind:"derived_exact_metadata_bridge",pre:{pin:api.gitBlob(preRaw),bytes:api.utf8(preRaw).length,sha256:api.sha256(api.utf8(preRaw))},post:{pin:api.gitBlob(postRaw),bytes:api.utf8(postRaw).length,sha256:api.sha256(api.utf8(postRaw))},counts:{pre_boundaries:pre.value.boundary.length,pre_protected:pre.value.protected_file.length,post_boundaries:post.value.boundary.length,post_protected:post.value.protected_file.length,ops:ops.length,original_rows:originalRows.length,original_raw_preserved:originalRows.filter(r=>r.raw_preserved).length,original_raw_changed:originalRows.filter(r=>!r.raw_preserved).length,semantic_rows_changed:fieldChanges.length},ops,original_rows:originalRows,field_changes:fieldChanges,full_forward:true,full_reverse:true,original_forbidden_preserved:true,required_ids_append_only:true};
};