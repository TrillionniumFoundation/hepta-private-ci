"""Copy and bind existing public research inputs without evaluating policies."""
import argparse
import copy
import gzip
import json
from pathlib import Path
import shutil
import time

from artifact_io import identity, json_bytes, read, save, sha


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--old-working", type=Path, required=True)
    parser.add_argument("--published", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    args = parser.parse_args()
    start = time.process_time()
    root, old, published = args.package, args.old_working, args.published
    inputs, vendor = root / "inputs", root / "vendor"
    inputs.mkdir(exist_ok=False)
    vendor.mkdir(exist_ok=False)
    (vendor / "frozen_joint").mkdir()
    provenance = {}
    def copied(source, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(source.read_bytes())
        if identity(source) != identity(target):
            raise ValueError("copy identity mismatch")
        provenance[str(target.relative_to(root))] = dict(source=str(source), **identity(source))
    for name in ("planning.py", "quadratic.py"):
        copied(published / "ndu_policy" / name, vendor / name)
    for name in ("run_head_edit.py", "checked_replay.py", "joint_task.py", "joint_deploy.py",
                 "joint_law.py", "legacy_task.py", "joint_protocol.json", "truth_transitions.npz",
                 "INPUT_ACQUISITION.json"):
        copied(old / "frozen_joint" / name, vendor / "frozen_joint" / name)
    copied(published / "ndu_policy/PROTOCOL_FROZEN.json", inputs / "OLD_PROTOCOL_FROZEN.json")
    old_protocol = read(inputs / "OLD_PROTOCOL_FROZEN.json")
    for name in ("planning.py", "quadratic.py"):
        if sha((vendor / name).read_bytes()) != old_protocol["source"]["new_code_sha256"][name]:
            raise ValueError("prior published source binding failed")
    refs = read(old / "frozen_joint/INPUT_ACQUISITION.json")
    expected = {x["archive_member"]: x["sha256"] for x in refs["files"]}
    old_heads = read(old / "history/OLD_CONTINUATION_HEADS.json.gz")
    old_by_fit = {row["fit"]: row for row in old_heads["fits"]}
    copied(old / "history/OLD_CONTINUATION_HEADS.json.gz", inputs / "OLD_CONTINUATION_HEADS.json.gz")
    model_records = {}
    for fit in (11, 23, 37, 53, 71):
        model_path = old / f"inputs/fit_{fit}/model_renewal/model.json"
        data_path = old / f"inputs/fit_{fit}/data/fit_{fit}_data.json"
        for path, member in ((model_path, f"fit_{fit}/model_renewal/model.json"),
                             (data_path, f"fit_{fit}/data/fit_{fit}_data.json")):
            if sha(path.read_bytes()) != expected[member]:
                raise ValueError("pinned original input identity mismatch")
        model, raw = read(model_path), read(data_path)
        worlds = {}
        for row in raw["train"]["rows"]:
            if row["world"] in worlds and worlds[row["world"]] != row["public"]:
                raise ValueError("conflicting original TRAIN public schedule")
            worlds[row["world"]] = row["public"]
        if len(worlds) != 64:
            raise ValueError("requires all original 64 TRAIN worlds")
        # No q, posterior, label, original VAL row, or sampled outcome is retained.
        save(inputs / f"fit_{fit}_TRAIN_PUBLICS.json.gz", list(worlds.values()))
        target = inputs / f"fit_{fit}_A.json.gz"
        with target.open("xb") as stream:
            stream.write(gzip.compress(model_path.read_bytes(), mtime=0))
        C = copy.deepcopy(model)
        C["network"]["w2"] = old_by_fit[fit]["network_w2"]
        C["network"]["b2"] = old_by_fit[fit]["network_b2"]
        if sha(json_bytes(C)) != old_by_fit[fit]["candidate_model_sha256"]:
            raise ValueError("exact C reconstruction failed")
        save(inputs / f"fit_{fit}_C.json.gz", C)
        previous_run = published / "ndu_policy/execution_r1/run"
        M = read(previous_run / f"models/fit_{fit}_DQ.json.gz")
        record = read(previous_run / f"fit_{fit}_CANDIDATES.json.gz")
        if sha(json_bytes(M)) != record["models"]["DQ"]["model_sha256"]:
            raise ValueError("old MSE DQ checkpoint identity failed")
        protected = copy.deepcopy(M)
        protected["network"]["w2"][:3] = copy.deepcopy(C["network"]["w2"][:3])
        protected["network"]["b2"][:3] = copy.deepcopy(C["network"]["b2"][:3])
        if protected != C:
            raise ValueError("old DQ modifies protected fields")
        copied(previous_run / f"models/fit_{fit}_DQ.json.gz", inputs / f"fit_{fit}_M.json.gz")
        model_records[str(fit)] = dict(original_model_file_sha256=sha(model_path.read_bytes()),
            original_train_data_file_sha256=sha(data_path.read_bytes()),
            C_canonical_model_sha256=sha(json_bytes(C)), M_canonical_model_sha256=sha(json_bytes(M)),
            old_candidate_record_sha256=sha((previous_run / f"fit_{fit}_CANDIDATES.json.gz").read_bytes()),
            TRAIN_public_worlds=64)
    history = inputs / "history"
    for name in ("HISTORY_REGISTRY.json.gz", *[p.name for p in sorted((old / "history").glob("fit_*_*_WORLDS.json.gz"))]):
        copied(old / "history" / name, history / name)
        if sha((history / name).read_bytes()) != old_protocol["source"]["history_inputs_sha256"][name]:
            raise ValueError("prior history binding failed")
    for source in sorted((published / "ndu_policy/execution_r1/run/worlds").glob("*.json.gz")):
        copied(source, history / "followup" / source.name)
    if len(list((history / "followup").glob("*.json.gz"))) != 20:
        raise ValueError("all 20 follow-up world files required")
    files = {str(path.relative_to(root)): identity(path) for base in (vendor, inputs)
             for path in sorted(base.rglob("*")) if path.is_file()}
    save(root / "INPUT_MANIFEST.json", dict(files=files, model_records=model_records,
        copied_sources=provenance, original_input_acquisition=refs,
        preparation_cpu_seconds=time.process_time() - start,
        original_train_labels_excluded_from_candidate_package=True,
        new_holdouts_generated=False, model_scoring_performed=False,
        source_research_package_commit="9f2d00f", reviewed_repository_head="85f507fb2e1c9e8ad9941451641bb4ec3f1dccb4"))
    print(json.dumps(dict(stage="inputs_prepared", files=len(files), scoring=False), sort_keys=True))


if __name__ == "__main__":
    main()
