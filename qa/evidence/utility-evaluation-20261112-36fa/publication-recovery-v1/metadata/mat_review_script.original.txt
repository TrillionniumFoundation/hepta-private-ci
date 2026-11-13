from pathlib import Path
import base64
import gzip
import hashlib
import json

p = Path("/tmp/hepta-36fa-native-ci-resumed-20261113T0255/materialization")
result = json.loads((p / "RESULT.json").read_text())
rows = json.loads((p / "ARTIFACTS.json").read_text())
artifacts = {r["name"]: r for r in rows}
assert len(artifacts) == len(rows)
def pin(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}
small = [
    "SOURCE_COORDINATION_EX.json", "before.old-git.json", "final.old-git.json",
    "final.new-index-check.json", "INPUT_IDENTITIES.final.json",
    "initial.git-metadata.json.gz.part-001.b64", "final.git-metadata.json.gz.part-001.b64",
]
verified = []
for name in small:
    data = (p / name).read_bytes()
    expected = artifacts[name]
    actual = pin(data)
    assert all(actual[k] == expected[k] for k in actual), name
    verified.append({"name": name, **actual})
initial = gzip.decompress(base64.b64decode((p / small[-2]).read_bytes()))
final = gzip.decompress(base64.b64decode((p / small[-1]).read_bytes()))
assert initial == final
assert pin(final) == result["current_git_metadata"]
assert (p / "before.old-git.json").read_bytes() == (p / "final.old-git.json").read_bytes()
before_inputs = json.loads((p / "INPUT_IDENTITIES.before.json").read_text())
final_inputs = json.loads((p / "INPUT_IDENTITIES.final.json").read_text())
assert isinstance(before_inputs, dict) and isinstance(final_inputs, list)
assert all(set(row) == {"path", "bytes", "sha256", "git_blob"} for row in final_inputs)
assert len(final_inputs) == len({row["path"] for row in final_inputs}) == len(before_inputs) == 8
projected_inputs = {row["path"]: {k: row[k] for k in ("bytes", "sha256", "git_blob")} for row in final_inputs}
assert projected_inputs == before_inputs
record = {
    "format": "hepta.root_actual_materialization_small_audit.v1",
    "small_complete_reads": verified,
    "current_git_metadata": json.loads(final),
    "current_git_metadata_pin": pin(final),
    "old_fixed_git_raw_before_after_equal": True,
    "input_identity_records_equal_after_explicit_path_projection": True,
    "input_serializations": {"before": "path-keyed map", "final": "list of path plus identity"},
    "final_index_check": json.loads((p / "final.new-index-check.json").read_text()),
    "coordination": json.loads((p / "SOURCE_COORDINATION_EX.json").read_text()),
    "source_gate_or_native_execution": False,
    "scope": "Actual returned artifact bodies, not another physical source or index read.",
}
print(json.dumps(record, sort_keys=True))
