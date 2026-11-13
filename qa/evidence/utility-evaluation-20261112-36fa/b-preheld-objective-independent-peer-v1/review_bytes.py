#!/usr/bin/env python3
"""Independent byte-only review; never imports or executes candidate Rust/tests."""
import argparse, difflib, hashlib, json, pathlib, re

BASE = pathlib.Path("/tmp/hepta-36fa-b-preheld-objective-increment-v1")
OUT = pathlib.Path("/tmp/hepta-36fa-b-preheld-objective-peer-v1")
MAPS = pathlib.Path("/tmp/hepta-36fa-current-workspace-reconstruction-v3")
PACKET_GIT = "9cb773cee4b42aba80d5836a9e4443f0be1f34fb"
PACKET_SHA256 = "d47814ac583402cccfc55e8d861fe66fc433cf8e9c555d52b3bb0ed195149231"
PREFIX = "codex-rs/hepta-agentd/src/"

def pin(raw):
    return {"bytes":len(raw), "sha256":hashlib.sha256(raw).hexdigest(),
            "git_blob":hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()}

def once(text, old, new):
    assert text.count(old) == 1, (old[:90], text.count(old))
    return text.replace(old,new,1)

def cut(text, start, end):
    assert text.count(start)==1 and text.count(end)==1
    a=text.index(start);b=text.index(end,a)
    return text[a:b]

def main():
    packet_raw=(BASE/"SOURCE_PACKET.json").read_bytes()
    assert pin(packet_raw)=={"bytes":87182,"sha256":PACKET_SHA256,"git_blob":PACKET_GIT}
    fetched=json.loads((OUT/"SOURCE_PACKET.GET.original.json").read_text())
    assert fetched["structuredContent"]["content"].encode()==packet_raw
    p=json.loads(packet_raw)
    assert len(p["changes"])==3
    maps={}
    for n in (86,89):
        q=(MAPS/f"EXACT_COMPOSED_OVERLAY_{n}.json").read_bytes()
        m=json.loads(q)
        maps[n]={"pin":pin(q),"rows":{x["path"]:x for x in m["rust_files"]}}
    assert maps[86]["pin"]["git_blob"]=="3f7d40d4933669da33d2aef3491efb431c5771ae"
    bodies={};checks=[];patch=[]
    for c in p["changes"]:
        path=c["path"]
        assert path.endswith("_tests.rs") and c["mode"]=="100644"
        for side in ("before","after"):
            raw=c[side+"_text"].encode()
            assert pin(raw)==c[side]
            assert (BASE/side/path).read_bytes()==raw
        for n in (86,89):
            assert c["before"]=={k:maps[n]["rows"][path][k] for k in ("bytes","sha256","git_blob")}
        bodies[path[len(PREFIX):]]=(c["before_text"],c["after_text"])
        patch.extend(difflib.unified_diff(c["before_text"].splitlines(True),
             c["after_text"].splitlines(True),fromfile="a/"+path,tofile="b/"+path))
        checks.append({"path":path,"before":c["before"],"after":c["after"],
                       "local_and_actual_packet_bodies_equal":True,
                       "root86_and_root89_preimages_equal":True})
    actual_patch=(BASE/"SOURCE_DELTA.patch").read_bytes()
    assert "".join(patch).encode()==actual_patch

    b,a=bodies["circuit_original_evaluation_source_support_tests.rs"]
    # Restore only the independently inspected field/signature substitutions.
    added=cut(a,"\n/// Complete borrowed comparison objective,","\npub(super) enum ObservationMode")
    z=once(a,added,"")
    legacy_start="    pub(super) async fn populate_from_original_training("
    new_start="    pub(super) async fn populate_from_preheld_objective("
    wrapper=cut(z,legacy_start,new_start)
    assert wrapper.count("self.populate_from_preheld_objective(")==1
    z=once(z,wrapper,"")
    z=once(z,new_start,legacy_start)
    assert z.count("objective: BorrowedOriginalObjective<'_>")==2
    z=z.replace("objective: BorrowedOriginalObjective<'_>","previous: &CircuitTaskSourcePublicationV1")
    z=once(z,".execute(objective, input, baseline, index, history_at)",
              ".execute(previous, input, baseline, index, history_at)")
    z=once(z,"                    objective,\n                    input.clone(),",
              "                    previous,\n                    input.clone(),")
    z=once(z,"                objective,\n                candidate_input,",
              "                previous,\n                candidate_input,")
    z=once(z,'        // and function bytes used by the preregistered comparison.\n',
              '        // and function bytes used by the preregistered comparison.\n        let objective = previous.original_record();\n')
    z=once(z,"            objective.objective_digest,","            objective.snapshot.objective_digest,")
    z=once(z,"record.objective_semantic_bytes = objective.objective_semantic_bytes.to_vec();",
              "record.objective_semantic_bytes = objective.objective_semantic_bytes.clone();")
    z=once(z,"record.objective_function_v1_bytes = objective.objective_function_v1_bytes.to_vec();",
              "record.objective_function_v1_bytes = objective.objective_function_v1_bytes.clone();")
    assert z==b,"source support full inverse mismatch"
    source_counts={}
    for needle in ("assert_eq!(","assert!(", "material::evaluation_provider::decision(",
                   "material::evaluation_provider::outcome(", "source_fixture::original_evaluation_source("):
        source_counts[needle]={"before":b.count(needle),"after":a.count(needle)}
        assert b.count(needle)==a.count(needle)

    b,a=bodies["circuit_original_evaluation_fresh_training_support_tests.rs"]
    z=once(a,"pub(in super::super) use super::source::BorrowedOriginalObjective;\n","")
    z=once(z,"\n    objective: BorrowedOriginalObjective<'a>,\n",
              "\n    previous: &'a CircuitTaskSourcePublicationV1,\n")
    block=cut(z,"\n    /// Receive a complete pre-held comparison objective separately from A's",
                  "/// Created before Material/T;")
    # The block ends with the original impl closing brace; preserve it.
    assert block.endswith("}\n\n")
    z=once(z,block,"}\n\n")
    z=once(z,"            objective: BorrowedOriginalObjective::from_original_record(previous.original_record()),",
              "            previous,")
    z=once(z,"    b.populate_from_preheld_objective(\n        input.objective,",
              "    b.populate_from_original_training(\n        input.previous,")
    assert z==b,"fresh input support full inverse mismatch"

    b,a=bodies["circuit_resident_candidate_provider_stage_tests.rs"]
    assert a.startswith(b)
    tail=a[len(b):]
    assert tail.count("#[tokio::test(")==1
    assert tail.count("async fn fresh_original_b_inputs_keep_actual_source_history_when_objective_is_borrowed(")==1
    assert tail.count(".is_err()")==5
    assert "finish_case(result, fixture).await" in tail
    assert tail.count("Box::pin(fixture.complete_training()).await?;")==1
    assert ".complete_b_and_evaluation()" not in tail
    assert all(word not in tail for word in ("tokio::spawn","spawn_blocking","abort(","cancel("))
    assert b.count("#[tokio::test(")==2 and a.count("#[tokio::test(")==3

    result={
      "format":"hepta-b-preheld-objective-independent-byte-review-v1",
      "status":"BYTE_ONLY_CHECKS_COMPLETE_NO_RUST_EXECUTION",
      "packet":pin(packet_raw),"patch":pin(actual_patch),
      "actual_packet_full_get_equal":True,
      "root86_map":maps[86]["pin"],"root89_map_local_identity":maps[89]["pin"],
      "sources":checks,
      "source_support_full_inverse_equal":True,
      "source_support_preserved_calls_and_assertions":source_counts,
      "fresh_input_support_full_inverse_equal":True,
      "old_stage_source_complete_prefix_equal":True,
      "old_test_methods":2,"added_test_methods":1,
      "new_negative_is_err_checks":5,
      "candidate_code_executed":False,"rust_formatter_compile_tests_h":False
    }
    target=OUT/"BYTE_REVIEW.json"
    with target.open("xb") as f:f.write((json.dumps(result,indent=2,sort_keys=True)+"\n").encode())
    print(json.dumps({"output":str(target),"pin":pin(target.read_bytes()),
                      "status":result["status"]},sort_keys=True))

if __name__=="__main__": main()
