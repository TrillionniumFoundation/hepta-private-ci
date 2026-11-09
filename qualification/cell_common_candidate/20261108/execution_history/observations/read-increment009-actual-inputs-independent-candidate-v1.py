"""Independent records-only typed review of frozen increment009 actual inputs."""
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tarfile
from datetime import datetime, timezone

R = Path("/home/qian-qi/work/hepta-cell-s0-records-20261108-898e")
P = R / "increment009-six-ready-packet-preparation-v2"
O = R / "increment009-actual-inputs-independent-candidate-review-v1"
SOURCE = "6ec5993fec3dcd6a3c569498a1d5b4c277f1c142"
TREE = "b0ddbe6b6f83dc42657260b266774f79c9d1ed90"
EXPECTED_PACKET_COUNTS = {
 "core-output-6ec5993-desktop-dependency-strict-history-v1": 198,
 "core-output-6ec5993-desktop-core-native-retention-history-v1": 64,
 "core-output-6ec5993-desktop-appserver-failed-native-retention-history-v1": 86,
 "core-output-6ec5993-desktop-agentd-root-native-retention-history-v1": 100,
 "core-output-6ec5993-desktop-posthoc-diagnostics-readback-history-v1": 117,
 "core-output-6ec5993-quiet-source-publication-history-v1": 439,
}
ALLOWED_METADATA = set([
  "observations/evidence-increment008-publication-v1/RESULT.json",
  "observations/evidence-increment008-publication-v1/commands.json",
  "observations/evidence-increment008-independent-readback-v1/RESULT.json",
  "observations/evidence-increment008-independent-readback-v1/commands.json",
  "observations/core-output-6ec5993-desktop-dependency-strict-independent-verification-v1/RESULT.json",
  "observations/core-output-6ec5993-desktop-core-history-independent-verification-v1/RESULT.json",
  "observations/core-output-6ec5993-desktop-appserver-failed-history-independent-verification-v1/RESULT.json",
  "observations/core-output-6ec5993-desktop-agentd-root-history-independent-verification-v2/RESULT.json",
  "observations/core-output-6ec5993-desktop-posthoc-history-independent-verification-v1/RESULT.json",
  "observations/core-output-6ec5993-source-publication-history-independent-verification-v2/RESULT.json",
  "observations/core-output-6ec5993-source-publication-history-independent-verification-v1/RESULT.json",
  "observations/core-output-6ec5993-source-publication-history-independent-verification-v1/H_PTY_READ_ORIGINAL.json",
  "observations/desktop-6ec-source-publication-history-seal-launch-v1/RESULT.json",
  "observations/pr5397-status009-v6-publication-observation-v1.json",
  "observations/core-output-6ec5993-source-publication-history-independent-verification-v1/v1-to-v2.patch",
  "observations/verify-desktop-6ec-source-publication-history-v1.py",
  "observations/verify-desktop-6ec-source-publication-history-v2.py",
  "observations/desktop-6ec-source-publication-history-seal-launch-v1/stdout",
  "observations/desktop-6ec-source-publication-history-seal-launch-v1/stderr"
])
PINS = {
 "DRAFT_INPUTS.json": (400760, "6cda57d0cd1dc1ec4c25248285c1c55549ab7c6511d8b0d7a8040e15ef782f77"),
 "PARENT_MANIFEST.json": (144909, "e2cf90360430c0db3dde19f3ef1e00466469b363f23b338e1f9db24a114edd7b"),
 "NEW_SOURCE_OBSERVATIONS.json": (7753, "2a7dac787ed50e6bb7d7bb6ec9de361e88d9186756df662f825e040fd200f13c"),
 "README-ADDITION.md": (9436, "8b785e0663066d6bdbf750901642a3479d290ee8c7391556e8109208955d5cb1"),
 "README-CANDIDATE.md": (97034, "41ef912065159150472efb809f2ca99a931d59e15a50f6d5b88c958594d4fdbf"),
 "METADATA-BUDGET.json": (14966, "8c3ddfd22bb5153784b571b8ada8ac501a7433ca50d9f98b812e6fe8703f3734"),
 "RESULT.json": (4643, "f5f4dbb16e3953c0f13cb2b9839d498e335a2ed0def6b6d77875771ff67a4da6"),
}
seen = {}

def require(value, message):
    if not value:
        raise ValueError(message)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def same_typed(a, b):
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(same_typed(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(same_typed(x, y) for x, y in zip(a, b))
    return a == b

def identify(s):
    return dict(device=s.st_dev, inode=s.st_ino, mode=stat.S_IMODE(s.st_mode),
                uid=s.st_uid, gid=s.st_gid, links=s.st_nlink,
                bytes=s.st_size, mtime_ns=s.st_mtime_ns, ctime_ns=s.st_ctime_ns)

def frozen(path, expected=None):
    path = Path(path)
    require(path.is_absolute() and path.is_relative_to(R) and ".." not in path.parts,
            "not an explicit records path")
    require(path.resolve(strict=True) == path, "symlink path")
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, "nonregular or linked input")
    with path.open("rb") as f:
        require(identify(os.fstat(f.fileno())) == identify(before), "open identity changed")
        data = f.read()
        require(identify(os.fstat(f.fileno())) == identify(before), "descriptor changed")
    require(identify(path.lstat()) == identify(before), "path changed")
    actual = {"path": str(path), **identify(before), "sha256": sha(data)}
    if expected is not None:
        require((len(data), actual["sha256"]) == tuple(expected), "size/SHA mismatch: " + str(path))
    if str(path) in seen:
        require(same_typed(seen[str(path)], actual), "input changed across reads")
    else:
        seen[str(path)] = actual
    return data

def safe_member(name):
    p = PurePosixPath(name)
    require(not p.is_absolute() and ".." not in p.parts, "unsafe archive member")
    return p

def big_int_count(value):
    if type(value) is int:
        return int(abs(value) > 2**53)
    if isinstance(value, dict):
        return sum(big_int_count(v) for v in value.values())
    if isinstance(value, list):
        return sum(big_int_count(v) for v in value)
    return 0

def main():
    O.mkdir(exist_ok=False)
    started = datetime.now(timezone.utc).isoformat()
    state = {"status": "READBACK_INCOMPLETE", "returncode": 1, "started_at": started,
             "appender_executed": False, "evidence_tree_read_or_written": False,
             "native_tests_executed": 0, "active_result_or_target_or_executable_read": False,
             "source_or_PR_or_publication_modified": False, "physical_cost": None,
             "full_history_cost": None, "stage_advancement_claimed": False}
    code = 1
    try:
        raw = {name: frozen(P / name, pin) for name, pin in PINS.items()}
        data = json.loads(raw["DRAFT_INPUTS.json"])
        parent = json.loads(raw["PARENT_MANIFEST.json"])
        observations = json.loads(raw["NEW_SOURCE_OBSERVATIONS.json"])
        budget = json.loads(raw["METADATA-BUDGET.json"])
        require(data["expected_evidence_head"] == "8ca3f19c69f2f14a42aa5fbe3ff72af807c65ff2", "parent commit")
        require(data["expected_index_sha256"] == PINS["PARENT_MANIFEST.json"][1], "parent index")
        require(data["expected_common_source_sha"] == "bf42d2a5c2c1ed5134f8e7584de306fb015c1a8d", "common head")
        require(data["formal_current_sha256"] == "c8b2bbb955272dde7679f86a7f0bf6113c46d7d4fbba3496446399c3615e10e4", "CURRENT")
        require(data["expected_prior_packet_count"] == len(parent["packets"]) == 87, "old packet count")
        require(data["expected_final_packet_count"] == 93, "new packet count")
        require(len(observations) == 6, "six new observations")
        retained = json.loads(raw["DRAFT_INPUTS.json"])["current_common_validation"]
        added = {key: retained["separate_source_observations"].pop(key) for key in observations}
        require(same_typed(added, observations), "input new observations differ")
        require(same_typed(retained, parent["current_common_validation"]), "old typed validation changed")
        require(same_typed(parent["packets"], json.loads(frozen(P / "PARENT_PACKET_ENTRIES.json"))), "old packet entries copy")
        require(same_typed(parent["current_common_validation"], json.loads(frozen(P / "PARENT_COMMON_VALIDATION.json"))), "old current copy")
        for value in observations.values():
            require(value["source_sha"] == SOURCE and value["source_tree"] == TREE, "new source")
            require(value["common_source_advanced"] is False and value["scientific_acceptance"] is False
                    and value["full_workspace_qualified"] is False, "new qualification claim")
            require(value["physical_cost"] is None and value["full_history_cost"] is None, "invented full cost")
        packets = data["packets"]
        require(len(packets) == 6 and {p["packet_id"]:p["file_member_count"] for p in packets} == EXPECTED_PACKET_COUNTS, "packet closed roster")
        require({v["packet_id"] for v in observations.values()} == set(EXPECTED_PACKET_COUNTS), "observation packet mapping")
        require(not ({p["packet_id"] for p in parent["packets"]} & set(EXPECTED_PACKET_COUNTS)), "old packet collision")
        required_checks, archive_summaries, all_nul = [], [], []
        for packet in packets:
            packet_id = packet["packet_id"]
            archive_path = Path(packet["archive_path"])
            require(archive_path.parent == R / packet_id and archive_path.name.endswith(".tar.xz"), "archive path boundary")
            archive_raw = frozen(archive_path, (packet["bytes"], packet["sha256"]))
            required = packet["required_json_members"]
            require(required and len({r["path"] for r in required}) == len(required), "required JSON duplicate/empty")
            nul_rows = packet.get("nul_delimited_git_stdout", [])
            require(len(nul_rows) == (13 if packet_id == "core-output-6ec5993-quiet-source-publication-history-v1" else 0), "NUL scope")
            with tarfile.open(fileobj=io.BytesIO(archive_raw)) as tar:
                members = tar.getmembers()
                require(len({m.name for m in members}) == len(members), "duplicate archive members")
                for member in members:
                    safe_member(member.name)
                    require(member.isfile() or member.isdir(), "archive link/special member")
                files = {m.name:m for m in members if m.isfile()}
                require(len(files) == packet["file_member_count"], "member count")
                for binding in required:
                    name = binding["path"]
                    safe_member(name)
                    require(name in files, "missing required member")
                    original = tar.extractfile(files[name]).read()
                    require((len(original), sha(original)) == (binding["bytes"], binding["sha256"]), "required member size/hash")
                    copied = frozen(P / "required-json" / packet_id / name, (binding["bytes"], binding["sha256"]))
                    require(copied == original, "required copy is not original bytes")
                    checks = binding["equals"]
                    require(len(checks) == 1 and checks[0]["path"] == [], "not a whole-object binding")
                    value = json.loads(original)
                    require(same_typed(value, checks[0]["value"]), "whole typed JSON differs")
                    required_checks.append({"packet_id":packet_id, "member":name, "bytes":len(original),
                                            "sha256":sha(original), "whole_typed_equal":True,
                                            "integers_above_JS_safe_range":big_int_count(value)})
                for binding in nul_rows:
                    name = binding["path"]
                    original = tar.extractfile(files[name]).read()
                    require(b"\0" in original and (len(original),sha(original)) == (binding["bytes"],binding["sha256"]), "NUL original bytes")
                    commands = json.loads(tar.extractfile(files[binding["commands_member"]]).read())
                    producer = binding["producer"]
                    matching = [row for row in commands if row["label"] == producer["command_label"]]
                    require(len(matching) == 1 and matching[0]["argv"] == producer["argv"]
                            and same_typed(matching[0]["stdout"], producer["stdout"]), "NUL original producer")
                    require(producer["argv"][0] == "git" and "-z" in producer["argv"]
                            and producer["stdout"] == {"bytes":len(original),"sha256":sha(original)}, "not original git -z")
                    all_nul.append({"packet_id":packet_id, "member":name, "bytes":len(original),"sha256":sha(original),
                                    "command_label":producer["command_label"]})
            archive_summaries.append({"packet_id":packet_id, "bytes":len(archive_raw),"sha256":sha(archive_raw),
                                      "file_members":packet["file_member_count"],"required_whole_JSON":len(required)})
        require(len(required_checks) == 26 and len(all_nul) == 13, "26 whole JSON/13 NUL")
        meta = data["supplementary_observations"]
        require(len(meta) == 19 and {x["relative_path"] for x in meta} == ALLOWED_METADATA, "19 metadata closed roster")
        metadata_rows = []
        for row in meta:
            relative = PurePosixPath(row["relative_path"])
            safe_member(str(relative))
            require(relative.parts[0] == "observations", "metadata scope")
            source = R.joinpath(*relative.parts[1:])
            require(str(source) == row["source_path"], "metadata source")
            original = frozen(source, (row["bytes"],row["sha256"]))
            require(len(original) <= 512000, "metadata publication cap")
            if row["kind"] == "original_json_observation":
                json.loads(original)
            else:
                require(row["kind"] == "original_text_observation", "metadata kind")
                original.decode("utf-8")
                require(b"\0" not in original, "NUL text metadata")
            metadata_rows.append({"relative_path":str(relative),"bytes":len(original),"sha256":sha(original)})
        require(len(raw["DRAFT_INPUTS.json"]) < 490000, "compact input chunk bound")
        require(raw["README-CANDIDATE.md"] == raw["README-ADDITION.md"] + raw["README-CANDIDATE.md"][-87598:], "README additive structure")
        require(sha(raw["README-CANDIDATE.md"][-87598:]) == "e0c3e6c5005974dc04a205b83061b2d2cae520f9966d5333b4bbf20deaf7113b", "old README suffix")
        require(sum(x["bytes"] for x in archive_summaries) == budget["archive_input_bytes"] == 8125656, "archive byte budget")
        require(sum(x["file_members"] for x in archive_summaries) == budget["archive_file_member_entries_with_overlap"] == 1004, "member budget")
        require(sum(row["file_member_count"] for row in parent["packets"]) + 1004 == 11108, "overlap total")
        require(sum(x["bytes"] for x in metadata_rows) == budget["proposed_supplementary_readback_bytes"], "metadata byte total")
        state.update(old_87_packet_entries_and_old_current_fulltyped_preserved=True,
            new_source_observations=observations, packet_count=93, member_entries_with_overlap=11108,
            whole_JSON_bindings=required_checks, archived_git_z_NUL_bindings=all_nul,
            archive_inputs=archive_summaries, supplementary_metadata=metadata_rows,
            old_README_suffix_exact=True, input_bytes=len(raw["DRAFT_INPUTS.json"]),
            input_sha256=sha(raw["DRAFT_INPUTS.json"]), input_below_490000=True,
            integers_above_JS_safe_range_preserved_in_required_objects=sum(x["integers_above_JS_safe_range"] for x in required_checks),
            all_1004_member_payloads_independently_rehashed=False,
            payload_scope="Whole archive hashes and complete names/counts checked; 26 required JSON and13 NUL member bytes independently read. Original packet readbacks retain broader per-member verification.",
            README_semantic_review="Complete 9436-byte addition statically reviewed before this reader; preserves original failures/source separation/HOLD/unknown cost and pending workspace.",
            publication_index_or_commit_verification_performed=False)
        for path, original_pin in list(seen.items()):
            frozen(Path(path), (original_pin["bytes"], original_pin["sha256"]))
        state["inputs_before_after_identical"] = True
        state["status"] = "ACTUAL_INPUTS_TYPED_AND_CLOSED_SCOPE_INDEPENDENTLY_READBACK_VERIFIED"
        code = 0
    except Exception as error:
        state["error"] = f"{type(error).__name__}: {error}"
    finally:
        state["returncode"] = code
        state["finished_at"] = datetime.now(timezone.utc).isoformat()
        state["input_pins"] = list(seen.values())
        state["input_count"] = len(seen)
        with (O / "RESULT.json").open("x", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(json.dumps({"status":state["status"],"returncode":code,"result":str(O/"RESULT.json"),
              "bytes":(O/"RESULT.json").stat().st_size,"sha256":sha((O/"RESULT.json").read_bytes()),
              "input_count":len(seen),"error":state.get("error")}), flush=True)
    return code

if __name__ == "__main__":
    raise SystemExit(main())
