return function replayFinal204Callers(blobs) {
 const PINS = {
  actual:"cd24b18a3ade8ae0a400bb2d52a27ad67f928074",
  logical:"0f0cc13187dd3f9a09f78ef9ce33f52009c96678",
  semanticGenerator:"eca89aa4bfff94d81346a3345974ea6c7ffd07c3",
  parser:"14b43d87cc460df3b0a2d4b5c5d178c3bff44ddf",
  finalizer:"f1131dc120e8c0df210723a9fa228c4c42893534",
  firstBridge:"800c2f32753919f6356e822776b5b0ac18248fdd",
  secondBridge:"e1968353409e0cc9e2e45c5b4ce0a95eec1952d2",
  outcome:"74aa68fe1d20a6bfea82ab7ef9e1644af5cb22d7",
  successor:"2cb1164a8d3c5e89946ac273e5e10249ac3f300e",
  sourceManifest:"848a82a966e4cab54b5410c5e4d2fe0dd7fde616",
  preservation:"fde301027476a8c480275838f6c6b3f70ab6d8a4",
  final:"0f0b4c835de967f90263ae9041865f5ac431615e"
 };
 const stages = [{"pin":"18b8e0ca81e26c0a09fa623c19d0c5bc3232674f","shape":"boundary_updates"},{"pin":"85885737a60604b11fea9aa198473df424d7dfc8","shape":"guard_updates"},{"pin":"a13a9a437bcaebf95ab6cb3bda5d97ae49a4e91b","shape":"row_delta"},{"pin":"7583c283d2d861bb6c3ade0fea58a6f223c0e2cd","shape":"row_delta"},{"pin":"875d82d02dc1d1dec4d2f9737f4ddcd912cde20f","shape":"row_delta"},{"pin":"86eaf98f248cda36fa591edd5fc541f9a5a96309","shape":"row_delta"},{"pin":"780619c2a09dbd8978b438b5f7b4d8f23f08e389","shape":"row_delta"},{"pin":"16ad1ae4f00e964e1a8ae40ff656b6406f218818","shape":"row_delta"}];
 const get=pin=>{const value=blobs[pin];if(typeof value!=="string")throw Error("Missing exact UTF-8 artifact "+pin);return value;};
 // Bootstrap helpers are fixed reviewed data-generation helpers, not the repository checker.
 // The caller must fetch them by the exact Git blob ID; every loaded input is then rehashed.
 const G=Function(get(PINS.semanticGenerator))();
 const P=Function(get(PINS.parser))();
 const F=Function(get(PINS.finalizer))();
 const assert=(ok,message)=>{if(!ok)throw Error(message);};
 const read=pin=>{const raw=get(pin);assert(G.gitBlob(raw)===pin,"Input blob hash "+pin);return raw;};
 for(const pin of [PINS.semanticGenerator,PINS.parser,PINS.finalizer])read(pin);
 const parse=pin=>JSON.parse(read(pin));
 const count=(haystack,needle)=>{let n=0,at=0;while((at=haystack.indexOf(needle,at))>=0){n++;at+=needle.length;}return n;};
 function apply(packetPin,original,reverse=false){
  const packet=parse(packetPin),ops=reverse?[...packet.ops].reverse():packet.ops;
  const expectedBefore=reverse?packet.post.pin:packet.pre.pin;
  const expectedAfter=reverse?packet.pre.pin:packet.post.pin;
  assert(G.gitBlob(original)===expectedBefore,"Exact bridge preimage "+packetPin);
  let current=original;
  for(const op of ops){
   assert(op.kind==="replace","Only exact string replacement accepted");
   const from=reverse?op.new:op.old,to=reverse?op.old:op.new;
   assert(from&&count(current,from)===1,"Unique bridge "+op.label);
   current=current.replace(from,to);
  }
  assert(G.gitBlob(current)===expectedAfter,"Exact bridge postimage "+packetPin);
  return {raw:current,ops:ops.length};
 }
 const actual=read(PINS.actual),logical=read(PINS.logical);
 const a=apply(PINS.firstBridge,actual);
 assert(a.raw===logical,"Actual checkout to logical union bytes");
 const plan=G.prepare(blobs,{boundary_successor_pins:[PINS.successor],pending_inputs:[]});
 assert(plan.counts.boundaries===1010&&plan.counts.protected_conjuncts===598,"Prepared plan count");
 const input={initial_plan:plan,base_raw:logical,stages:stages.map(s=>({...s,raw:read(s.pin)})),outcome_annex:{pin:PINS.outcome,raw:read(PINS.outcome)},source_manifest:PINS.sourceManifest};
 const finalization=F(input,{fingerprint:G.fingerprint,gitBlob:G.gitBlob,parseToml:P.parseToml});
 const rendered=finalization.render(),result=finalization.result;
 assert(rendered.git_blob===PINS.final,"Final metadata Git identity");
 assert(rendered.raw===read(PINS.final),"Final published candidate bytes");
 const b=apply(PINS.secondBridge,logical);
 assert(b.raw===rendered.raw,"Independent final bridge equality");
 const backwards=apply(PINS.firstBridge,apply(PINS.secondBridge,rendered.raw,true).raw,true);
 assert(backwards.raw===actual,"Complete reverse to actual checkout");
 const preserved=parse(PINS.preservation);
 assert(preserved.forbidden.length===600&&preserved.conjunctions.length===447,"Complete preservation inventory");
 for(const row of preserved.forbidden){
  const actualRow=result.protected_file[row.row_index];
  assert(actualRow.path===row.path,"Forbidden origin path");
  assert(result.protected_origins[row.row_index].origin===row.origin,"Forbidden immutable origin");
  assert(G.fingerprint(actualRow.forbidden)===row.initial_fingerprint,"Exact forbidden from introduction");
  assert(G.fingerprint(actualRow.forbidden)===G.fingerprint(row.final_forbidden),"Final forbidden value");
 }
 const seen=new Set();
 for(const group of preserved.conjunctions)for(const entry of group.rows){
  assert(!seen.has(entry.row_index),"Conjunct duplicated by generator");seen.add(entry.row_index);
  assert(result.protected_file[entry.row_index].path===group.path,"Conjunct path mismatch");
  assert(result.protected_origins[entry.row_index].origin===entry.origin,"Conjunct immutable origin mismatch");
  assert(G.fingerprint(result.protected_file[entry.row_index])===entry.row_fingerprint,"Conjunct full row mismatch");
 }
 assert(seen.size===600,"Every conjunct retained independently");
 const source=parse(PINS.sourceManifest);
 assert(source.files.length===204,"Exact current source inventory");
 return {
  schema_version:1,status:"source_bound_metadata_candidate_not_original_checker_or_native_qualification",
  target_path:"CALLERS.toml",actual_checkout_pre:PINS.actual,logical_union:PINS.logical,
  source_manifest:PINS.sourceManifest,metadata:PINS.final,
  counts:{...result.counts,actual_to_logical_ops:a.ops,logical_to_final_ops:b.ops,full_ops:a.ops+b.ops,
   original_logical_rows:1301,original_logical_raw_preserved:rendered.kept_original_rows_exact,
   original_logical_raw_changed:rendered.changed_original_rows,all_forbidden_rows:600},
  rendered,result,semantic_preparation:plan,
  evidence_limits:[
   "The first bridge derives given bytes; historical positive-obligation authorization is reviewed using the separately pinned original source/annex receipts.",
   "Pure V8 generation and bounded source projections do not execute the repository checker, compiler, ordinary tests or original native qualification.",
   "All current source definitions are bound by the204 manifest; a future formatter or compiler mutation requires an exact successor and renewed literal guards."
  ]
 };
};