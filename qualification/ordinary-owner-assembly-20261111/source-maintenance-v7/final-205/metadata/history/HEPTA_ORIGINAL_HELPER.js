{
  "schema_version": 1,
  "kind": "reusable_owned_metadata_analysis_tools",
  "status": "Pure V8 analysis helper; not the original checker and not product code",
  "references": {
    "rust_and_typed_transcriptions": {
      "git_blob": "c82daa6cd3614f74a84097aeb003f45fbb8720fd",
      "bytes": 13481,
      "sha256": "7b122c8a3c91495efa1e148fcb7890c17a9938694bb3c6293bf635c1c90be187"
    },
    "toml_parser": "e53b3c7beb51d71cf7f5afe76701909444feebd3",
    "original_checker": "7a6709691c372504ca11b5d2a74e14ba819fca8f",
    "original_typed_helper": "e23bb8aa42241b429ef5dbce5a4660853b66eb2f"
  },
  "analysis_utility_js": "return (function makeOwnedAnnexTools(){\n  function canonical(x){if(Array.isArray(x))return x.map(canonical);if(x&&typeof x===\"object\")return Object.fromEntries(Object.keys(x).sort().map(k=>[k,canonical(x[k])]));return x;}\n  function equal(a,b){return JSON.stringify(canonical(a))===JSON.stringify(canonical(b));}\n  function tomlValue(x){if(typeof x===\"string\")return JSON.stringify(x);if(Array.isArray(x))return\"[\"+x.map(tomlValue).join(\", \")+\"]\";if(x&&typeof x===\"object\")return\"{ \"+Object.entries(x).map(([k,v])=>k+\" = \"+tomlValue(v)).join(\", \")+\" }\";if(typeof x===\"boolean\"||typeof x===\"number\")return String(x);throw Error(\"unsupported TOML value\");}\n  function table(kind,row){return\"\\n[[\"+kind+\"]]\\n\"+Object.entries(row).map(([k,v])=>k+\" = \"+tomlValue(v)).join(\"\\n\")+\"\\n\";}\n  function applyExact(source,ops){let value=source;for(const op of ops){if(typeof op.before!==\"string\"||!op.before||value.split(op.before).length!==2)throw Error(\"nonunique forward \"+op.purpose);value=value.replace(op.before,op.after);}let back=value;for(const op of [...ops].reverse()){if(typeof op.after!==\"string\"||!op.after||back.split(op.after).length!==2)throw Error(\"nonunique reverse \"+op.purpose);back=back.replace(op.after,op.before);}if(back!==source)throw Error(\"reverse mismatch\");return value;}\n  function makeRowOp(raw,parsed,kind,index,newRow,purpose){\n    const extent=parsed.rows.find(r=>r.kind===kind&&r.index===index);if(!extent)throw Error(\"missing row\");\n    const oldRow=parsed.value[kind][index],before=raw.slice(extent.start,extent.end);let after=before;\n    for(const field of [...extent.fields].reverse()){\n      if(!Object.hasOwn(newRow,field.key))throw Error(\"cannot delete old field \"+field.key);\n      if(equal(oldRow[field.key],newRow[field.key]))continue;\n      const start=field.value_start-extent.start,end=field.value_end-extent.start;\n      after=after.slice(0,start)+tomlValue(newRow[field.key])+after.slice(end);\n    }\n    for(const key of Object.keys(newRow))if(!Object.hasOwn(oldRow,key))throw Error(\"new field needs explicit writer \"+key);\n    if(before===after)return null;\n    return{kind:\"replace_exact_once\",before,after,purpose,row_kind:kind,row_index:index,id:oldRow.id??null,path:oldRow.path??oldRow.definition_path};\n  }\n  function generateGuards(sourceByPath,selection,Rust){\n    return selection.map(item=>{\n      const raw=sourceByPath[item.path];if(typeof raw!==\"string\")throw Error(\"source absent \"+item.path);\n      const code=Rust.code(raw);\n      const row={path:item.path,required:[],forbidden:[],required_order:[],required_function_order:[]};\n      for(const marker of item.functions){\n        const extent=Rust.fnExtent(code,marker);\n        const sequence=extent.body.split(\"\\n\").map(s=>s.trim()).filter(Boolean);\n        if(sequence.length<2)throw Error(\"order needs two actual fragments\");\n        row.required_function_order.push({function:marker,sequence});\n      }\n      for(const marker of item.structures){\n        const hits=Rust.positions(code,marker);if(hits.length!==1)throw Error(\"unique structure \"+marker);\n        const start=hits[0],end=Rust.itemEnd(code,start);if(end===null)throw Error(\"structure extent\");\n        const span=code.slice(start,end+1),newline=span.indexOf(\"\\n\");\n        if(newline<0)throw Error(\"single-line structure requires separate explicit treatment\");\n        row.required_order.push([span.slice(0,newline).trim(),span.slice(newline+1)]);\n      }\n      Rust.project(row,raw);\n      return row;\n    });\n  }\n  function semanticUnion(raw,annex,Toml){\n    const parsed=Toml.parseToml(raw),current=parsed.value,ops=[],audit={boundary_rows:[],protected_rows:[],already_present:[]};\n    const clone=x=>JSON.parse(JSON.stringify(x));\n    for(const edit of annex.old_row_changes){\n      if(edit.kind===\"boundary\"){\n        const hits=current.boundary.map((row,index)=>({row,index})).filter(x=>x.row.id===edit.old_row.id);\n        if(hits.length!==1)throw Error(\"unique boundary ID \"+edit.old_row.id);\n        const hit=hits[0],next=clone(hit.row);\n        for(const field of edit.changed_fields){\n          const before=edit.old_row[field],after=edit.new_row[field];\n          if(field===\"product_callers\"){\n            const additions=after.filter(path=>!before.includes(path)),removals=before.filter(path=>!after.includes(path));\n            if(removals.length)throw Error(\"owned annex permits no old caller removal\");\n            if(!before.every(path=>next.product_callers.includes(path)))throw Error(\"old caller already removed; manual review required\");\n            for(const path of additions)if(!next.product_callers.includes(path))next.product_callers.push(path);\n          }else{\n            if(equal(next[field],after))continue;\n            if(!equal(next[field],before))throw Error(\"concurrent boundary field conflict \"+edit.old_row.id+\".\"+field);\n            next[field]=clone(after);\n          }\n        }\n        for(const field of [\"symbol\",\"definition_path\",\"call_pattern\",\"receiver_type\",\"receiver_methods\"])\n          if(!edit.changed_fields.includes(field)&&!equal(hit.row[field],edit.old_row[field]))throw Error(\"boundary identity/receiver conflict \"+edit.old_row.id+\".\"+field);\n        const op=makeRowOp(raw,parsed,\"boundary\",hit.index,next,edit.purpose);if(op)ops.push(op);\n        audit.boundary_rows.push({id:hit.row.id,changed:!!op});\n      }else if(edit.kind===\"protected_file\"){\n        const oldHits=current.protected_file.map((row,index)=>({row,index})).filter(x=>equal(x.row,edit.old_row));\n        if(oldHits.length===1){const hit=oldHits[0],op=makeRowOp(raw,parsed,\"protected_file\",hit.index,edit.new_row,edit.purpose);if(op)ops.push(op);audit.protected_rows.push({index:hit.index,path:hit.row.path,changed:!!op});}\n        else{const newHits=current.protected_file.map((row,index)=>({row,index})).filter(x=>equal(x.row,edit.new_row));if(oldHits.length===0&&newHits.length===1)audit.already_present.push({kind:\"protected_file\",index:newHits[0].index,path:edit.new_row.path});else throw Error(\"protected row identity conflict; do not select solely by path \"+edit.old_row.path);}\n      }else throw Error(\"unsupported semantic edit kind\");\n    }\n    const addBoundaries=[];\n    for(const row of annex.new_boundaries){\n      const sameId=current.boundary.filter(x=>x.id===row.id),sameSymbol=current.boundary.filter(x=>x.symbol===row.symbol);\n      if(sameId.length){if(sameId.length!==1||!equal(sameId[0],row)||sameSymbol.length!==1)throw Error(\"new boundary conflict \"+row.id);audit.already_present.push({kind:\"boundary\",id:row.id});}\n      else{if(sameSymbol.length)throw Error(\"new symbol collision \"+row.symbol);addBoundaries.push(row);}\n    }\n    const addProtected=[];\n    for(const row of annex.new_protected){\n      const equalRows=current.protected_file.filter(x=>equal(x,row));\n      if(equalRows.length===0)addProtected.push(row);\n      else if(equalRows.length===1)audit.already_present.push({kind:\"new_protected_file\",path:row.path});\n      else throw Error(\"duplicate equal protected rows require explicit review\");\n    }\n    const originalIds=current.privileged_inventory.required_boundary_ids,declared=current.boundary.map(x=>x.id);\n    if(new Set(originalIds).size!==originalIds.length||!equal([...originalIds].sort(),[...declared].sort()))throw Error(\"input declared/required inventory mismatch\");\n    const newIds=addBoundaries.map(x=>x.id),inventory=originalIds.concat(newIds);\n    if(newIds.length){const f=parsed.fields.filter(x=>x.key===\"required_boundary_ids\");if(f.length!==1)throw Error(\"unique inventory field\");ops.push({kind:\"replace_exact_once\",before:raw.slice(f[0].value_start,f[0].value_end),after:tomlValue(inventory),purpose:\"Append exactly the declared new owned IDs.\",row_kind:\"privileged_inventory\"});}\n    let post=applyExact(raw,ops);\n    if(addBoundaries.length||addProtected.length){\n      const anchor=post.slice(-512),append=addBoundaries.map(x=>table(\"boundary\",x)).join(\"\")+addProtected.map(x=>table(\"protected_file\",x)).join(\"\");\n      const op={kind:\"replace_exact_once\",before:anchor,after:anchor+append,purpose:\"Append actual owned boundary and separate conjunctive protected rows.\",row_kind:\"append\"};\n      post=applyExact(post,[op]);ops.push(op);\n    }\n    const verified=Toml.parseToml(post).value;\n    if(!equal(verified.boundary.map(x=>x.id).sort(),[...verified.privileged_inventory.required_boundary_ids].sort()))throw Error(\"output inventory mismatch\");\n    audit.added_boundary_ids=newIds;audit.added_protected_rows=addProtected.map(x=>x.path);\n    audit.final_counts={boundary:verified.boundary.length,required:verified.privileged_inventory.required_boundary_ids.length,protected:verified.protected_file.length};\n    if(applyExact(raw,ops)!==post)throw Error(\"final exact replay\");\n    return{post,ops,audit};\n  }\n  return{canonical,equal,tomlValue,table,applyExact,makeRowOp,generateGuards,semanticUnion};\n})();",
  "owned_guard_selection": [
    {
      "path": "codex-rs/hepta-agentd/src/circuit_q24_successor_execution.rs",
      "functions": [
        "fn require_original_installed_custody("
      ],
      "structures": []
    },
    {
      "path": "codex-rs/hepta-agentd/src/circuit_q24_successor_retirement.rs",
      "functions": [
        "fn require_original_c_installation(",
        "fn require_original_retirement_snapshot(",
        "fn request_original_retirement(",
        "fn finish_original_retirement_join(",
        "fn require_original_retired_slot(",
        "fn consume_original_retirement("
      ],
      "structures": []
    },
    {
      "path": "codex-rs/hepta-agentd/src/circuit_q24_successor_state.rs",
      "functions": [
        "fn new_pending_slot("
      ],
      "structures": []
    },
    {
      "path": "codex-rs/hepta-agentd/src/circuit_q24_successor_worker.rs",
      "functions": [
        "fn run_original_retirable("
      ],
      "structures": []
    },
    {
      "path": "codex-rs/hepta-agentd/src/circuit_task_runtime.rs",
      "functions": [
        "fn run("
      ],
      "structures": []
    },
    {
      "path": "codex-rs/hepta-agentd/src/circuit_task_runtime_lifecycle.rs",
      "functions": [
        "fn require_original_phase(",
        "fn from_original_phase(",
        "fn require_original_origin(",
        "fn reserve_original_start(",
        "fn retain_original_normal_terminal(",
        "fn wait_original_normal_shutdown(",
        "fn wait_original_runtime_shutdown(",
        "fn take_original_natural_join(",
        "fn request_stop(",
        "fn stop_and_join_original_owner(",
        "fn original_natural_job(",
        "fn take_abandoned_original_result(",
        "fn retain_original_circuit_owner_handle(",
        "fn delivery(",
        "fn join_locked(",
        "fn join_original_returned_ok(",
        "fn receive_original_result("
      ],
      "structures": [
        "struct OriginalCircuitOwnerCustody {",
        "struct OriginalCircuitJobState {",
        "impl Drop for OriginalCircuitOwnerCustody {",
        "impl Drop for OriginalCircuitStartAdmission<'_> {",
        "impl Drop for OriginalCircuitRuntimeReceiver {"
      ]
    },
    {
      "path": "codex-rs/hepta-agentd/src/circuit_task_same_actor_admission.rs",
      "functions": [
        "fn observe_original_task_learning(",
        "fn observe_original_c_learning(",
        "fn finish_original_task("
      ],
      "structures": []
    },
    {
      "path": "codex-rs/hepta-agentd/src/circuit_task_same_actor_joined.rs",
      "functions": [
        "fn require_original_phase(",
        "fn original_completion(",
        "fn original_status(",
        "fn require_retained_original_owners("
      ],
      "structures": []
    },
    {
      "path": "codex-rs/hepta-agentd/src/circuit_task_same_actor_learning.rs",
      "functions": [
        "fn original_learning_work(",
        "fn attach_original_learning_work("
      ],
      "structures": []
    },
    {
      "path": "codex-rs/hepta-agentd/src/circuit_task_same_actor_phase.rs",
      "functions": [
        "fn admit_original_task(",
        "fn require_ticket_locked(",
        "fn pending_count(",
        "fn close(",
        "fn original_same_actor_owner_custody(",
        "fn from_original_same_actor_worker("
      ],
      "structures": []
    },
    {
      "path": "codex-rs/hepta-agentd/src/circuit_task_same_actor_purposes.rs",
      "functions": [
        "fn require_original_phase("
      ],
      "structures": []
    },
    {
      "path": "codex-rs/hepta-agentd/src/circuit_task_same_actor_retirement.rs",
      "functions": [
        "fn require_original_slot(",
        "fn require_original_binding(",
        "fn original_route(",
        "fn require_original_phase(",
        "fn require_original_learning_work(",
        "fn require_original_learning_snapshot(",
        "fn request_original_successor_retirement(",
        "fn finish_original_successor_join(",
        "fn retire_original_root_purposes(",
        "fn begin_closing_original_c(",
        "fn require_closing_original_c(",
        "fn wait_original_c_tickets(",
        "fn quiesce_original_c("
      ],
      "structures": [
        "struct OriginalSameActorCQuiescence {",
        "struct OriginalSameActorCJoined {",
        "struct OriginalSameActorCPurposesRetired {"
      ]
    },
    {
      "path": "codex-rs/hepta-agentd/src/circuit_task_source_readback.rs",
      "functions": [
        "fn require_original_source_custody("
      ],
      "structures": []
    },
    {
      "path": "codex-rs/hepta-agentd/src/circuit_task_successor_runtime.rs",
      "functions": [
        "fn from_original_successor_worker("
      ],
      "structures": []
    },
    {
      "path": "codex-rs/hepta-agentd/src/root_authority_session.rs",
      "functions": [
        "fn connect_owned_stream(",
        "fn connect_same_actor_phase_until(",
        "fn connect_original_phase_stream(",
        "fn activate_final_use_owners(",
        "fn refresh(",
        "fn synchronize_consumers("
      ],
      "structures": [
        "struct AgentdRootAuthoritySession {",
        "struct RootWorker<F> {",
        "struct ConsumerSyncJob {",
        "impl Drop for AgentdRootAuthoritySession {",
        "impl Drop for FenceOnDrop {",
        "impl Drop for ActivationAttempt<'_> {"
      ]
    },
    {
      "path": "codex-rs/hepta-agentd/src/root_authority_session_consumer_jobs.rs",
      "functions": [
        "fn new(",
        "fn reserve_original_consumer(",
        "fn stop_original_normal_admission(",
        "fn join_original_paused_consumers(",
        "fn require_original_joined_summary(",
        "fn close(",
        "fn record_worker_failure(",
        "fn worker_failure(",
        "fn receive_original_consumer(",
        "fn record_joined(",
        "fn join_stopped_consumers(",
        "fn retain_original_session_consumer_handle(",
        "fn join_original_handle("
      ],
      "structures": [
        "impl Drop for OriginalConsumerAdmission<'_> {",
        "struct OriginalConsumerJob {"
      ]
    },
    {
      "path": "codex-rs/hepta-agentd/src/root_authority_session_final_retirement.rs",
      "functions": [
        "fn finish_original_retired_session_after_root_exit(",
        "fn finish_original_retired_fields(",
        "fn require_original_cleanup_origin("
      ],
      "structures": []
    },
    {
      "path": "codex-rs/hepta-agentd/src/root_authority_session_lifecycle.rs",
      "functions": [
        "fn new(",
        "fn reserve_original_session(",
        "fn require_original(",
        "fn stop_and_join_retired_session_tasks(",
        "fn retain_original(",
        "fn from_original_worker(",
        "fn consumers(",
        "fn retirement_notice(",
        "fn request_stop(",
        "fn join_original_retired_session_custody(",
        "fn abort(",
        "fn phase_custody(",
        "fn require_original_phase_task_custody("
      ],
      "structures": [
        "struct OriginalRootSessionCustodySlot {",
        "impl Drop for OriginalRootSessionCustodySlot {",
        "impl Drop for OriginalSessionAdmission<'_> {",
        "struct OriginalRootSessionCustody {",
        "impl Drop for OriginalRootSessionCustody {",
        "impl Drop for OriginalSessionRetirement {"
      ]
    },
    {
      "path": "codex-rs/hepta-agentd/src/root_authority_session_normal.rs",
      "functions": [
        "fn new(",
        "fn request_original(",
        "fn requested(",
        "fn changed(",
        "fn park_original_worker(",
        "fn take_original_parked(",
        "fn discard_after_actual_worker_join(",
        "fn from_original_worker(",
        "fn request_original_normal_pause(",
        "fn request_original_pause_waiter(",
        "fn require_original_pause_origin(",
        "fn join_original_paused(",
        "fn require_original_origin(",
        "fn require_original_joined_custody(",
        "fn consumer_join_observation(",
        "fn retire_original_observation_purpose(",
        "fn release_original_observation_resources("
      ],
      "structures": [
        "struct OriginalPausedObservationResources {",
        "struct OriginalRootSessionPaused {",
        "struct OriginalRootSessionObservationRetired {"
      ]
    },
    {
      "path": "codex-rs/hepta-agentd/src/root_authority_session_observation_retired.rs",
      "functions": [
        "fn require_original_origin("
      ],
      "structures": []
    },
    {
      "path": "codex-rs/hepta-agentd/src/same_actor_q24_phase_c.rs",
      "functions": [
        "fn run_original_scoped(",
        "fn run_original_activated("
      ],
      "structures": []
    },
    {
      "path": "codex-rs/hepta-agentd/src/same_actor_q24_phase_publish.rs",
      "functions": [
        "fn publish_and_observe_original_c("
      ],
      "structures": []
    },
    {
      "path": "codex-rs/hepta-agentd/src/same_actor_q24_phase_worker.rs",
      "functions": [
        "fn new(",
        "fn with_original_outer_custody(",
        "fn run("
      ],
      "structures": []
    }
  ],
  "actual_verification": {
    "guard_rows_equal": true,
    "guard_functions": 117,
    "base_union_full_post_equal": true,
    "idempotent_exact_post_no_ops": true,
    "output_meta": {
      "git_blob": "ba1e8deba033031bd396268b557bfecdd01465b6",
      "bytes": 1062217,
      "sha256": "77717bb46413fa623056f013c563ba4c6b826ebc66e320296633864110551650"
    }
  },
  "usage": [
    "Evaluate analysis_utility_js to obtain generateGuards, makeRowOp, applyExact and semanticUnion; supply the frozen TOML parser and Rust projection objects from the cited artifacts.",
    "generateGuards reads only supplied source strings and the explicit ordered selection. Each unique function uses the original exact fn-name extent with nested functions masked, then all nonempty masked code lines in original order. No generic/repeated fn is mislabelled as a unique function.",
    "Structural/Drop guards use two markers: their actual header followed by the complete remaining masked source span. This is full-span file protection, not a new function-scope checker capability.",
    "semanticUnion matches boundary ID; protected rows must match their entire original/new parsed value, never only path. Caller additions retain every old caller; concurrent definition/receiver/guard conflicts refuse. New protected rows remain conjunctive.",
    "The owned semantic data are a separate immutable object linked by the annex. On the original cd24 baseline the helper reproduces the exact 15-op postimage; applying the same semantics to that post produces zero operations.",
    "Projection and source-byte equality are bounded static evidence only. Actual formatter output, original checker, compiler, component tests and native qualification remain to be executed by Root on a fixed candidate."
  ]
}
