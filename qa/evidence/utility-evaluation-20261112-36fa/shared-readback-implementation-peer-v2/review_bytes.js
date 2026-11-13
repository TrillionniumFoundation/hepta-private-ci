function applyUnified(patch, beforeMap, afterMap) {
 const lines=patch.split("\n"), proofs=[]; let i=0;
 while(i<lines.length){
  if(lines[i]===""){i++;continue;}
  const d=/^diff --git a\/(.+) b\/(.+)$/.exec(lines[i]); if(!d||d[1]!==d[2])throw Error("diff header at "+i);
  const path=d[1];i++;
  while(i<lines.length&&!lines[i].startsWith("@@ ")&&!lines[i].startsWith("diff --git "))i++;
  const before=beforeMap[path]??"", old=before===""?[]:before.split("\n");
  if(before!==""&&old.pop()!=="")throw Error("nonLF before");
  const out=[];let cursor=0,hunks=0;
  while(i<lines.length&&lines[i].startsWith("@@ ")){
   const hh=/^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/.exec(lines[i++]);if(!hh)throw Error("hunk header");
   const os=+hh[1],oc=hh[2]===undefined?1:+hh[2],ns=+hh[3],nc=hh[4]===undefined?1:+hh[4];
   const from=os===0?0:os-1;
   if(from<cursor)throw Error("overlap");
   while(cursor<from)out.push(old[cursor++]);
   if(out.length!==(ns===0?0:ns-1))throw Error("newstart mismatch "+path);
   let seenOld=0,seenNew=0;
   while(i<lines.length&&!lines[i].startsWith("@@ ")&&!lines[i].startsWith("diff --git ")){
    const line=lines[i];if(line===""&&i===lines.length-1){i++;break;}
    const op=line[0],body=line.slice(1);if(![" ","+","-"].includes(op))throw Error("unrecognized patch line "+i);
    if(op===" "||op==="-"){if(old[cursor]!==body)throw Error("context mismatch "+path+":"+cursor);cursor++;seenOld++;}
    if(op===" "||op==="+"){out.push(body);seenNew++;}i++;
   }
   if(seenOld!==oc||seenNew!==nc)throw Error("count mismatch "+path);hunks++;
  }
  out.push(...old.slice(cursor));const actual=out.join("\n")+"\n";
  if(actual!==afterMap[path])throw Error("postimage mismatch "+path);proofs.push({path,hunks,exact_preimage_and_postimage:true});
 }
 if(proofs.length!==Object.keys(afterMap).length)throw Error("missing patch path");return proofs;
}

const checks=[];function require(v,msg){if(!v)throw Error(msg);checks.push(msg);}
function one(s,x){require(s.split(x).length===2,"unique removal: "+x.slice(0,90));return s.replace(x,"");}
function fnblock(s,name){const re=new RegExp("^    (?:(?:pub(?:\\([^)]*\\))? )?)(?:async )?fn "+name+"\\b","m");const hit=re.exec(s);if(!hit)throw Error("method not found "+name);const end=s.indexOf("\n    }\n",hit.index);if(end<0)throw Error("method end "+name);return s.slice(hit.index,end+7);}
const packet=input.packet,cfg=input.cfgPacket,before=input.before,after={};
for(const c of packet.changes){after[c.path]=c.after_text;}
const patchProof=applyUnified(input.patch,before,after);
const lp="codex-rs/hepta-agentd/src/lib.rs";
require(cfg.changes.length===1&&cfg.changes[0].path===lp,"one lib increment");
require(cfg.changes[0].after_text===input.cfgLib,"increment packet equals full Git postimage");
const cfgPatchProof=applyUnified(input.cfgPatch,{[lp]:after[lp]},{[lp]:input.cfgLib});
const initialLib=after[lp];after[lp]=input.cfgLib;
const rows=[];
function checkFile(name,transformation){const p="codex-rs/hepta-agentd/src/"+name;const transformed=transformation(after[p]);require(transformed===before[p],"all original bytes restored: "+name);rows.push({path:p,entire_original_file_restored_by_removing_only_named_additions:true});}
checkFile("cell_q24_training_command.rs",s=>one(s,'#[path = "cell_q24_training_shared_readback.rs"]\nmod shared_readback;\n\n'));
checkFile("neuron_cell_evaluation_host_command.rs",s=>one(s,'#[path = "neuron_cell_evaluation_shared_readback.rs"]\nmod shared_readback;\n\n'));
checkFile("circuit_retained_version.rs",s=>one(s,'pub use host::OriginalCircuitPublishedEvidenceReadbackV1;\n'));
checkFile("circuit_feature_current.rs",s=>one(s,'pub use retained_publication::version::OriginalCircuitPublishedEvidenceReadbackV1;\n'));
const exportBlock='#[cfg(target_os = "linux")]\npub use circuit_feature_current::OriginalCircuitPublishedEvidenceReadbackV1;\n';
const initialCfgPreservation=initialLib.replace(exportBlock,"")===before[lp];
require(initialCfgPreservation===false,"prior v2 lib cfg defect reproduced");
checkFile("lib.rs",s=>one(s,exportBlock));
checkFile("circuit_retained_version_host.rs",s=>{
 s=one(s,'#[path = "circuit_retained_version_shared_readback.rs"]\nmod shared_readback;\npub use shared_readback::OriginalCircuitPublishedEvidenceReadbackV1;\n');
 s=one(s,'    shared_evaluated: Option<OriginalCircuitPublishedEvidenceReadbackV1>,\n');
 const field='                shared_evaluated: None,\n';require(s.split(field).length===3,"two host None initializers");return s.split(field).join("");
});
checkFile("circuit_evaluated_retention_context.rs",s=>{
 const start=s.indexOf('    /// Consume the same retained clients only after the Version host has\n');
 const end=s.indexOf('    // Receipt owners retain the same opaque pins and origin.');
 require(start>=0&&end>start,"one context seal insertion window");
 return s.slice(0,start)+s.slice(end);
});
const oldFactoryProof=[];
for(const n of ["circuit_evaluated_selection_command_service.rs","circuit_evaluated_next_use_command_service.rs"]){
 const p="codex-rs/hepta-agentd/src/"+n;
 require(after[p].includes(fnblock(before[p],"from_original_evaluated_receipt_owner")),"old by-value factory exact: "+n);
 oldFactoryProof.push({path:p,method:"from_original_evaluated_receipt_owner",exact_bytes_preserved:true});
 checkFile(n,s=>{
  s=one(s,"    SharedEvaluated(crate::OriginalCircuitPublishedEvidenceReadbackV1),\n");
  s=one(s,fnblock(s,"from_original_evaluated_shared_receipt_owner")+"\n");
  const st=s.indexOf("            OriginalPredecessors::SharedEvaluated(shared) => {\n"),en=s.indexOf("            OriginalPredecessors::Evaluated { trainer, evaluator } => {",st);
  require(st>=0&&en>st,"one new shared match arm: "+n);
  return s.slice(0,st)+s.slice(en);
 });
}
for(const n of ["circuit_evaluated_selection_command_owner_adapter.rs","circuit_evaluated_next_use_remote.rs"]){
 const p="codex-rs/hepta-agentd/src/"+n;
 require(after[p].includes(fnblock(before[p],"into_evaluated_command_owner")),"old by-value adapter exact: "+n);
 oldFactoryProof.push({path:p,method:"into_evaluated_command_owner",exact_bytes_preserved:true});
 checkFile(n,s=>one(s,fnblock(s,"into_evaluated_shared_command_owner")+"\n"));
}
const sp="codex-rs/hepta-agentd/src/circuit_retained_version_state.rs";
const stateMutations=["original_trainer","original_evaluator"];
let restored=after[sp];
for(const name of stateMutations)restored=restored.replace(fnblock(restored,name),fnblock(before[sp],name));
require(restored===before[sp],"state only two getter fallback bodies changed");
const preservedMethods=["bind_original_predecessor","read_original","read_original_recovery","require_cut_current","observe_phase","build_original_selection_reader","install_original_selection_reader"];
const stateProof=preservedMethods.map(name=>{const b=fnblock(before[sp],name);require(after[sp].includes(b),"original state guard exact: "+name);return{name,bytes_preserved:true};});
const current="codex-rs/hepta-agentd/src/circuit_evaluated_retention_context.rs";
for(const name of ["require_current","require_original_receipt_owners","authenticate","clone_for_original_receipt"]){
 require(after[current].includes(fnblock(before[current],name)),"original context method exact: "+name);
}
const methods=[];
for(const [p,s] of Object.entries(after)){
 const bs=before[p]??"";
 for(const m of s.matchAll(/^\s*(pub(?:\([^)]*\))?)\s+(?:async\s+)?fn\s+([A-Za-z_][A-Za-z_0-9]*)/gm)){
  if(!new RegExp("\\bfn\\s+"+m[2]+"\\b").test(bs))methods.push({path:p,visibility:m[1],name:m[2]});
 }
}
return {format:"hepta-shared-readback-independent-byte-proof-v1",patchProof,cfgPatchProof,oldFilesRestored:rows,stateOriginalGuards:stateProof,oldByValueMethods:oldFactoryProof,initialCfgDefectObserved:initialCfgPreservation===false,correctedCfgPreserved:true,newExplicitFunctionDeclarations:methods,checks,rust_compilation:false,source_writes:false,h_requests:0};

