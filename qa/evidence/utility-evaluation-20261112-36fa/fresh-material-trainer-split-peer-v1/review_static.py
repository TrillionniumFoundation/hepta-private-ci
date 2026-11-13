"""Read and compare frozen source text only; no Rust, QA or candidate execution."""
from pathlib import Path
import hashlib
import json
import difflib

BASE = Path("/tmp/hepta-36fa-fresh-material-trainer-split-v1")
OUT = Path("/tmp/hepta-36fa-fresh-material-trainer-split-peer-v1")
PREFIX = "codex-rs/hepta-agentd/src/"
PARENT = "circuit_resident_candidate_provider_material_support_tests.rs"
CHILD = "circuit_resident_candidate_provider_unstarted_material_tests.rs"

def pin(raw):
    return {"bytes":len(raw), "git_blob":hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest(), "sha256":hashlib.sha256(raw).hexdigest()}

packet_raw = (BASE/"SOURCE_PACKET.json").read_bytes()
assert pin(packet_raw)["git_blob"] == "a72dc791ed6026ae49b0500a52dc295f9b3622ad"
packet = json.loads(packet_raw)
assert len(packet["changes"]) == 2
rows = []
for row in packet["changes"]:
    for side in ("before","after"):
        text = row[side+"_text"]
        if text is None:
            assert row[side] is None
            continue
        raw = (BASE/side/row["path"]).read_bytes()
        assert text.encode("utf-8") == raw
        assert pin(raw) == row[side]
    rows.append({k:v for k,v in row.items() if k not in ("before_text","after_text")})
before = (BASE/"before"/PREFIX/PARENT).read_text()
after = (BASE/"after"/PREFIX/PARENT).read_text()
child = (BASE/"after"/PREFIX/CHILD).read_text()
assert pin(before.encode())["git_blob"] == "e54fe13095d93a559de5c2816a15f5171774f7cf"
assert pin(after.encode())["git_blob"] == "e2e108a17021f10e18ccd4c873beec6f5fc35e4e"
assert pin(child.encode())["git_blob"] == "4eb88297be6a9707aa8e8d5fce8eda077f45ef71"
start = "    pub(super) async fn new_with_original_work_deadline("
end = "    pub(super) fn original_bytes("
old_method = before[before.index(start):before.index(end)]
new_method = after[after.index(start):after.index(end)]
mount = '#[path = "'+CHILD+'"]\nmod unstarted_material;\npub(super) use unstarted_material::UnstartedMaterialProvider;\n\n'
assert after.count(mount) == 1 and after.count(new_method) == 1
assert after.replace(mount,"").replace(new_method,old_method) == before
assert before[before.index(end):] == after[after.index(end):]
pre_start = "        let ProviderAdmission {"
pre_end = "        let mut a = support::start(a, published, Arc::clone(&baseline), bundle.clone()).await?;\n"
def between(s,a,b,include_end=False):
    pos=s.index(a); finish=s.index(b,pos)+(len(b) if include_end else 0);return s[pos:finish]
prelude=between(before,pre_start,pre_end,True)
assert prelude == between(child,pre_start,pre_end,True)
a_start = "            let previous = execute(&a, 1).await?;"
t_start = "            // Open the real custody files"
material_body=between(before,a_start,t_start)
child_material=between(child,a_start,"            Ok::<_, anyhow::Error>((material, material_owner, optimizer, ledger, previous,")
assert material_body == child_material
old_trainer=between(before,t_start,"            Ok::<_, anyhow::Error>((material, material_owner, trainer, ledger, previous,")
actual_trainer=between(after,t_start,"            Ok(trainer)")
adjustments=[
 ("opened(&root,","opened(root,"),
 ('&root, "positive-native-witness"','root, "positive-native-witness"'),
 ('&root, "positive-training-receipt-witness"','root, "positive-training-receipt-witness"'),
 ("Arc::clone(&material_owner)","Arc::clone(material_owner)"),
 ("material.clone()","(*material).clone()"),
 ("&material,","material,"),
 ("into_original_dataset_readback(&material)","into_original_dataset_readback(material)"),
 ("Arc::clone(&baseline)","Arc::clone(baseline)"),
]
normalized=old_trainer
for a,b in adjustments:normalized=normalized.replace(a,b)
assert normalized == actual_trainer
assert "material_ports::" not in child
assert "Trainer::" not in child and "BootstrapCustodyV1 {" not in child
assert child.count(a_start)==1
assert child.count("decision_with_original_evidence(")==1
assert child.count("terminal_outcome_with_original_evidence(")==1
assert child.count("VersionFixture::new_initial(")==1
ports={s:after.count(s) for s in ("commands_for_original(","source_for_original(","evidence_for_original(")}
assert ports=={"commands_for_original(":1,"source_for_original(":1,"evidence_for_original(":2}
assert after.index('opened(root, "positive-native-training", true)?') < after.index("material_ports::commands_for_original(")
assert after.count("UnstartedMaterialProvider::new_with_original_work_deadline(")==1
expected_patch=""
for row in packet["changes"]:
    expected_patch += "".join(difflib.unified_diff((row["before_text"] or "").splitlines(True),row["after_text"].splitlines(True),fromfile="a/"+row["path"] if row["before_text"] is not None else "/dev/null",tofile="b/"+row["path"]))
assert expected_patch.encode()==(BASE/"SOURCE_DELTA.patch").read_bytes()
out={
 "format":"hepta-material-trainer-split-independent-byte-review-v1",
 "status":"STATIC_TEXT_CHECKS_MATCH_NO_EXECUTION",
 "packet":pin(packet_raw),"sources":rows,
 "parent_inverse_after_only_constructor_and_single_mount":True,
 "old_original_bytes_and_finish_entire_suffix_exact":True,
 "provider_admission_material_peers_and_original_struct_exact":True,
 "original_A_prelude_exact":pin(prelude.encode()),
 "original_actual_A_decision_outcome_material_body_exact":pin(material_body.encode()),
 "trainer_subrange_equivalent_after_only_explicit_borrow_spelling":True,
 "borrow_spelling_changes":adjustments,
 "original_peer_calls_once":ports,
 "material_only_trainer_or_test_port_construction":False,
 "custody_files_before_first_old_transport":True,
 "single_call_to_material_only_constructor":True,
 "source_patch_complete_equal":True,
 "rust_QA_gate_H_executed":False,
}
OUT.mkdir(exist_ok=True)
with (OUT/"BYTE_REVIEW.json").open("x") as f:
    json.dump(out,f,indent=2);f.write("\n")
print(json.dumps({"review":pin((OUT/"BYTE_REVIEW.json").read_bytes()),"old_A_prelude_bytes":len(prelude.encode()),"old_material_body_bytes":len(material_body.encode()),"old_suffix_bytes":len(before[before.index(end):].encode())}))
