"""Seal the independent main41e source review; immutable input reads only."""
import base64, collections, gzip, hashlib, json
from pathlib import Path
from lexical_primitives import ident, lex
from item_primitives import groups
from review_actual_semantics_v3 import macro_items

HERE=Path(__file__).resolve().parent
def write(name,value):
    raw=(json.dumps(value,sort_keys=True,indent=2)+"\n").encode()
    dest=HERE/name
    if dest.exists(): assert dest.read_bytes()==raw
    else:
        with dest.open("xb") as f:f.write(raw)
    return ident(raw)

def main():
    byte=json.loads((HERE/"ACTUAL_TRANSITION_BYTE_AND_TOKEN_REVIEW.json").read_bytes())
    scoped=json.loads((HERE/"SCOPED_SEMANTIC_BYTE_PROOF.v3.json").read_bytes())
    artifacts=json.loads((HERE/"inputs/ARTIFACTS.original.json").read_bytes())
    rows={r["name"]:r for r in artifacts["files"]}
    for stem,pin in byte["artifacts_exact"].items():
        record=rows[stem+".postimages.json.gz"]
        assert [record["raw_bytes"],record["raw_sha256"],record["raw_git_blob"]]==pin["raw"]
        assert [record["bytes"],record["sha256"],record["git_blob"]]==pin["gzip"]
        part=rows[stem+".postimages.json.gz.part-001.b64"]
        assert [part["bytes"],part["sha256"],part["git_blob"]]==pin["part"]
        assert record["parts"]==[part]
        assert part["decoded_bytes"]==record["bytes"] and part["decoded_offset"]==0
        assert part["decoded_sha256"]==record["sha256"]
    normal=json.loads(json.loads((HERE/"inputs/NORMAL.original.json").read_bytes())["content"][0]["text"])
    result=json.loads((HERE/"inputs/RESULT.original.json").read_bytes())
    assert normal["job_id"]=="1a1d47cebc8-392-41e" and normal["exit_code"]==0 and normal["output_complete"] is True
    assert result["qualification"] is False and result["test_commands_dispatched"]==0
    assert len(result["final_audits"])==2 and all(r["status"]=="verified" for r in result["final_audits"])
    attribute_counts=collections.Counter();macro_counts=collections.Counter();numbers=[]
    for row in byte["stage_lineage"]:
        path=row["path"]
        texts=[(HERE/"source-images/final"/side/path).read_text() for side in ("before","after")]
        token_sets=[lex(text)[0] for text in texts]
        assert [t[:2] for t in token_sets[0] if t[0]=="number"]==[t[:2] for t in token_sets[1] if t[0]=="number"],path
        numbers.append({"path":path,"numeric_literals_exact_equal":True,"count":sum(t[0]=="number" for t in token_sets[0])})
        tok=token_sets[1];pairs,_=groups(tok)
        for i,t in enumerate(tok):
            if t[1]=="#" and i+1<len(tok) and tok[i+1][1]=="[":
                content="".join(x[1] for x in tok[i+2:pairs[i+1]])
                attribute_counts[content.split("(")[0].split("=")[0]]+=1
        macro_counts.update(x["name"] for x in macro_items(texts[1]))
    helper=json.loads((HERE/"inputs/recovered_peer.source.identity.json").read_bytes())
    assert ident((HERE/"inputs/recovered_peer.source.rs").read_bytes())=={k:helper[k] for k in ("bytes","sha256","git_blob")}
    compact={
      "format":"hepta-main41e-independent-frozen-byte-review-v1",
      "status":"EXACT_ACTUAL_BYTES_AND_SCOPED_SOURCE_TRANSITIONS_VERIFIED",
      "job":normal["job_id"],
      "source_commit":result["source_commit"],"initial_tree":result["source_tree"],
      "actual_final_tree_from_RESULT":result["actual_final_source"]["postimages"]["all_actual_physical_tree"],
      "actual_final_inventory_from_RESULT":result["actual_final_source"]["inventory"],
      "independent_scope":"All encoded postimage bytes, all 17 source identities and actual stage composition, lexical and manual semantic analysis. Full directory/index/runtime observations remain original native evidence, not new observations by this reviewer.",
      "primary_inputs":[{"name":name,**ident((HERE/"inputs"/name).read_bytes())} for name in
        ("RESULT.original.json","NORMAL.original.json","ARTIFACTS.original.json","STDOUT.complete.original.log","POSTIMAGES_AND_RAW_LOG_READBACK_REVIEW.json")],
      "three_original_raw_gzip_part_identities_equal_ARTIFACTS":True,
      "three_encoded_parts_full_Git_GET_and_exact_decoding":byte["artifacts_exact"],
      "raw_packet_Git_ids_are_content_identities_not_claimed_standalone_uploads":True,
      "counts":byte["actual_stage_counts"],"stage_lineage":byte["stage_lineage"],
      "source_graph":byte["source_graph"],"fix_splice_count":scoped["fix_splice_total"],
      "fix_splices_complete_forward_and_inverse_equal":True,
      "formatting_files":len(scoped["fmt"]),
      "formatting_full_token_equal_files":sum(x["full_tokens_equal"] for x in scoped["fmt"]),
      "formatting_exact_import_inventory_all":True,"formatting_exact_macro_token_trees_all":True,
      "all_literal_and_comment_sequences_equal":True,
      "function_declarations":sum(x["function_count"] for x in scoped["final_function_and_macro_inventory"]),
      "function_names_and_body_presence_sequence_equal":True,
      "three_function_header_differences_are_parameter_list_trailing_commas":["prepare_original","take_task_inputs","install"],
      "attribute_total":sum(attribute_counts.values()),"attribute_kinds":dict(attribute_counts),
      "attribute_sequence_exact_equal":True,
      "macro_invocation_total":sum(macro_counts.values()),"macro_counts":dict(macro_counts),
      "changed_macro_count":1,
      "changed_macro":"anyhow::ensure in deadline_case: observed.load(Ordering::Acquire) == !already_expired -> != already_expired",
      "boolean_truth_table":scoped["boolean_truth_table"],"all_numeric_literal_sequences":numbers,
      "identity_error_conversion_type_source":helper,
      "reviewer_execution":{"H":0,"Rust":0,"QA":0,"formatter":0,"source_mutation":0,"ref_mutation":0},
      "qualification":False
    }
    compact_pin=write("FROZEN_BYTE_REVIEW.json",compact)
    source_proof=ident((HERE/"SCOPED_SEMANTIC_BYTE_PROOF.v3.json").read_bytes())
    comma_classes={
      "neuron_generation_initial_root_cold.rs":["call_argument_trailing_removed","call_argument_trailing_added"],
      "neuron_generation_initial_root_cold_tests.rs":["struct_literal_trailing_added"],
      "neuron_generation_initial_root_custody.rs":["call_argument_trailing_removed","call_argument_trailing_added","call_argument_trailing_added"],
      "neuron_generation_initial_root_custody_support_tests.rs":[
       "struct_literal_trailing_added","function_parameter_trailing_added","struct_literal_trailing_added",
       "call_argument_trailing_added","call_argument_trailing_added","array_element_trailing_added",
       "function_parameter_trailing_added","struct_pattern_trailing_added","struct_literal_trailing_added",
       "struct_literal_trailing_added","call_argument_trailing_added","call_argument_trailing_added",
       "function_parameter_trailing_added","struct_literal_trailing_added","struct_literal_trailing_added","call_argument_trailing_added"],
      "neuron_generation_initial_root_custody_tests.rs":["call_argument_trailing_added"]
    }
    for row in scoped["fmt"]:
        actual=[c for c in row["remaining_token_changes"] if c["classification"]=="comma_requires_context"]
        assert len(actual)==len(comma_classes.get(Path(row["path"]).name,[])),row["path"]
    assert sum(map(len,comma_classes.values()))==23
    findings=[
     {"id":"S01","result":"Closed actual evidence lineage",
      "detail":"Independently full-GET all three original Base64 parts, strict-decode the one terminal-LF envelope, match compressed and raw byte count/SHA256/Git content identity against original ARTIFACTS, and compare every embedded source image to its metadata. Every final preimage matches the frozen a489 complete graph. The 12 fix and 14 fmt transitions compose exactly to the 17 final images. No predicted bytes substitute for an actual source image.",
      "evidence":["FROZEN_BYTE_REVIEW.json","ACTUAL_TRANSITION_BYTE_AND_TOKEN_REVIEW.json","inputs/ARTIFACTS.original.json"]},
     {"id":"S02","result":"All 19 automatic-fix splices accounted for",
      "detail":"Twelve complete files are reconstructed in both directions using 19 explicitly enumerated replacements. Categories are nine cleanup/join short-circuit let chains, one cfg(test) pause let chain, three same-standard-method references, one identity anyhow::Error conversion, four last-use moves of owned mutation data, and one Boolean identity. No other fix bytes differ.",
      "evidence":["SCOPED_SEMANTIC_BYTE_PROOF.v3.json","review_actual_semantics_v3.py"]},
     {"id":"S03","result":"Original cleanup sequencing and refusal behavior preserved",
      "detail":"Nested if-let cleanup blocks became short-circuit let chains. Option::take is still first, the stop/finish/join operation still executes only for Some, and an Err still enters the same accumulation body once. None/Ok paths remain no-ops for the accumulator. The local read cancellation case still tests consumed_join before abort/await, releases the real probe, and waits for submitted blocking work's original terminal marker. This does not upgrade old Drop/cancel or five-second cleanup-timeout behavior into proof of joined termination.",
      "evidence":["diffs/fix.after","SCOPED_SEMANTIC_BYTE_PROOF.v3.json"]},
     {"id":"S04","result":"Direct-method and identity-conversion fixes preserve actual types",
      "detail":"The latch is a std::sync::Mutex<bool>, so PoisonError::into_inner names the same recovery method. Trainer/evaluator peer fields remain real std::thread::JoinHandle values and are joined, not detached. The original recovered_peer signature is anyhow::Result<(OriginalCellQ24TrainingCommandConnectionV1, HostAuthorityPeerChannel)>; removing anyhow::Error::from(error) therefore removes the identity conversion only. The surrounding dataset drop, actual peer finish, context text and return remain unchanged.",
      "type_source":helper,"evidence":["inputs/recovered_peer.source.rs","diffs/fix.after"]},
     {"id":"S05","result":"Mutation-data moves do not replace owner evidence",
      "detail":"The two JSON base values and two encoded report byte vectors are moved at their last use instead of cloned. These are owned serde_json::Value / Vec<u8> attack payloads. Every prior full-signature/context/budget test, the extra host_trust/freeze-payload/trailing-byte mutations, rejection checks, original_bytes comparisons and cleanup calls remain. No SourcePublication, owner, signature, FD, grant or trust object is fabricated or copied by these four edits.",
      "evidence":["diffs/fix.after/circuit_resident_candidate_first_material_tests.rs.diff","diffs/fix.after/circuit_resident_candidate_provider_material_control_tests.rs.diff"]},
     {"id":"S06","result":"Changed assertion is exactly Boolean-equivalent",
      "detail":"The only changed assertion macro replaces AtomicBool.load(Acquire) == !already_expired with != already_expired. Both operands are actual bool values. All four input combinations give the same truth value. The two deadline cases still require the original refusal, consumed channel, server error, unchanged source bytes and zero C revision.",
      "evidence":["FROZEN_BYTE_REVIEW.json","SCOPED_SEMANTIC_BYTE_PROOF.v3.json"]},
     {"id":"S07","result":"Production fix is confined to cfg(test) scheduling",
      "detail":"In circuit_learning_local_read.rs the sole fix combines response.is_ok() and let Some(terminal) under the same existing #[cfg(test)]. The terminal pause remains after the real OriginalVersionLocalReadBindingV1::respond result and before the same response is returned. Removing that single exact test-only replacement restores the entire original fix preimage. Non-test same-Arc capability, try_lock/take terminal slot, original 1..=128 counter, absolute end/request deadline, full binding checks, retained-read equality and post-check restore sequence were not edited.",
      "evidence":["source-images/final/after/codex-rs/hepta-agentd/src/circuit_learning_local_read.rs","review_actual_semantics_v3.py"]},
     {"id":"S08","result":"Formatter differences individually classified",
      "detail":"Nine files have identical complete non-whitespace token streams. The other five preserve import leaves/visibility/attributes, literals, comments and every macro token tree. Residual differences are exactly 23 optional trailing commas, import ordering in two test files (three use items moved), and three explicit blocks around the same single closure-tail expressions in a test helper. The file-open and witness constructors return the same Result with no new statement/semicolon; the third block returns the same anyhow error. No tuple-arity change or blanket comma erasure is used.",
      "comma_classes_in_actual_order":comma_classes,
      "closure_tails":["let file = |name| OpenOptions...open(...)","let witness = |name, label: &str| FileAnchorWitnessStore::open(...)","ok_or_else(|| anyhow::anyhow!(...))"],
      "evidence":["SCOPED_SEMANTIC_BYTE_PROOF.v3.json","item_primitives.py"]},
     {"id":"S09","result":"Concrete Root custody boundaries unchanged",
      "detail":"Both production Root files are formatter-only. The original UID and effective-UID check, operation ID/intent/binding/target authentication, same concrete Current/authority Arcs, consume-Prepared-before-publish state transition, ReadbackRequired on uncertainty, original recovery call and before/after protected readback comparison remain the same tokens except call trailing commas. No Current/Live/owner getter, cloneable custody, new grant, new preparation fallback, or operation redispatch was added.",
      "evidence":["source-images/final/after/codex-rs/hepta-agentd/src/neuron_generation_initial_root_cold.rs","source-images/final/after/codex-rs/hepta-agentd/src/neuron_generation_initial_root_custody.rs","SCOPED_SEMANTIC_BYTE_PROOF.v3.json"]},
     {"id":"S10","result":"Declarations, attributes and attacks retained within the actual 17-path scope",
      "detail":"All 185 named function declarations retain their names/order/body presence. Only three headers gain a parameter-list trailing comma; parameters and types are unchanged. All 69 attribute token trees remain exact, including all nine ignored Root cases in this scope. All 438 macro invocations retain names/order; 437 retain every token, with the one Boolean-equivalent ensure as above. All numeric, string/char/raw literal and comment sequences remain exact. This is a scoped comparison, not a new whole-repository source-closure run.",
      "evidence":["FROZEN_BYTE_REVIEW.json","SCOPED_SEMANTIC_BYTE_PROOF.v3.json"]},
     {"id":"S11","result":"Maintenance remains separate from qualification",
      "detail":"Original job 1a1d47cebc8-392-41e records fix rc0 and fmt rc0, no timeout/output limit, and zero test commands. Its two final audits record complete source/Git and 24 unchanged original inputs. The actual physical tree is c026a8d7e93c958b39a36c666debecb3dba4be14 while HEAD/index remain d256/a489. This peer neither aligns them nor converts maintenance success into source gates, native tests, hosted CI, useful independent B, or real utility.",
      "evidence":["inputs/RESULT.original.json","inputs/NORMAL.original.json"]},
     {"id":"S12","result":"Final nonRust refresh remains a distinct review",
      "detail":"This review finds no new static semantic/authority blocker in the actual 17 Rust transitions. Hash-sensitive protected bodies and contract markers must still be refreshed against these actual bytes and independently reviewed without deleting guards, attacks, old methods or required inventories. Ordinary is the sole author of that next proposal. No executable approval configuration or gate result is created here.",
      "evidence":["FROZEN_BYTE_REVIEW.json"]}
    ]
    report={
      "format":"hepta-main41e-independent-actual-fix-fmt-semantic-review-v1",
      "status":"NO_NEW_STATIC_SEMANTIC_OR_AUTHORITY_BLOCKER_IN_ACTUAL_17_RUST_TRANSITIONS",
      "reviewer":"evaluation_audit","job":normal["job_id"],
      "input_source_commit":result["source_commit"],"input_tree":result["source_tree"],
      "actual_final_physical_tree":compact["actual_final_tree_from_RESULT"],
      "actual_final_inventory":compact["actual_final_inventory_from_RESULT"],
      "source_ref_or_index_alignment_performed_by_reviewer":False,
      "qualification":False,"new_H_or_Rust_or_QA_executions":0,
      "exact_byte_proof":compact_pin,"scoped_semantic_proof":source_proof,
      "findings":findings,
      "limitations":[
        "Pure lexical/manual analysis is not a Rust parser or compiler proof and does not prove runtime behavior.",
        "The actual maintenance commands succeeded; no behavioral tests were dispatched in that original job.",
        "Whole-tree/runtime/index observations are attributed to the retained native RESULT; this reviewer independently checked all 17 changed source byte chains, not a new physical source observation.",
        "Existing cleanup timeout and Drop/cancel limitations remain: failure/timeout can be Unknown and does not prove worker termination.",
        "No completed normal-host orchestration, cross-process cold restart, independent useful B, permission grant, or utility result is inferred.",
        "Final nonRust protected-body refresh and complete source/native qualification remain separate pending work."
      ]
    }
    review_pin=write("REVIEW.json",report)
    large=(HERE/"ACTUAL_TRANSITION_BYTE_AND_TOKEN_REVIEW.json").read_bytes()
    zipped=gzip.compress(large,mtime=0);encoded=base64.b64encode(zipped)+b"\n"
    assert len(encoded)<=512000
    dest=HERE/"LEXICAL_DIAGNOSTIC.json.gz.b64"
    if dest.exists():assert dest.read_bytes()==encoded
    else:
        with dest.open("xb") as f:f.write(encoded)
    encoding=write("LEXICAL_ENCODING.json",{
      "format":"hepta-lossless-full-lexical-review-encoding-v1",
      "raw_filename":"ACTUAL_TRANSITION_BYTE_AND_TOKEN_REVIEW.json","raw":ident(large),"gzip":ident(zipped),
      "parts":[{"name":dest.name,**ident(encoded)}],
      "decode":"Strip one terminal LF; strict Base64-decode; gunzip; match all raw identities. Large raw diagnostic is not placed as a >512000-byte leaf."})
    print(json.dumps({"review":review_pin,"byte":compact_pin,"scoped":source_proof,
                     "encoding":encoding,"encoded_full_lexical":ident(encoded),
                     "attribute_kinds":dict(attribute_counts),"macro_counts":dict(macro_counts)},indent=2))

if __name__=="__main__":
    main()

