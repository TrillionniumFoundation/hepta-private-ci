"""Use the unchanged caller verifier over exact cc22's complete Rust index.

Only the evidence directory is writable. The manifest repair is an in-memory
single-caller delta; attack sources are stored outside the checked-out tree.
This is a source mechanism check and grants no ordinary qualification.
"""

from pathlib import Path
from datetime import datetime, timezone
import copy
import gzip
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tomllib
import traceback

sys.dont_write_bytecode = True
REPO = Path("/home/qian-qi/hepta-learn-source-20261112-037c-cc22a699")
RECORDS = Path("/home/qian-qi/hepta-learn-037c-evidence/sourcebound-readback-caller-cc22-v1")
SOURCE = "cc22a69972d029d3ef28d49096f396eb5214c616"
TREE = "827fb70ed75d30c48d4693cbd0d23ea04f5744da"
BOUNDARY = "learning_source_bound_training_stage_readback"
CALLER = "codex-rs/hepta-agentd/src/cell_q24_training_command_readback_service.rs"
BASE_SHA = "7725f09680e6f63b9123f8c1ee51e19e8b9e54d169c8c34fc8c7c6165b8d5a22"
POST_SHA = "446216e0cc4c2a8738394e4c8b7b8aec81319aedd5b44dca6989cc5d50007b24"
OLD_LINE = 'product_callers = ["codex-rs/hepta-agentd/src/cell_q24_training_command_service.rs", "codex-rs/hepta-agentd/src/cell_q24_model_command_lane.rs"]'
NEW_LINE = OLD_LINE[:-1] + ', "' + CALLER + '"]'
VERIFIER_PINS = {
    "scripts/verify_hepta_callers.py": "16015483d2319a2dbf2f6ab13e4c3c5e5f3a5318ac85f70557004b7fcb450e3f",
    "scripts/hepta_typed_callers.py": "3740bc9c17796686f1d6b282675d275d1b07c70a4b22c67945072c7b61a40d38",
}


def now():
    return datetime.now(timezone.utc).isoformat()


def save(name, value):
    with (RECORDS / name).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write("\n")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git(*words):
    return subprocess.check_output(["git", "--no-optional-locks", *words], cwd=REPO)


def identity():
    return {
        "commit": git("rev-parse", "HEAD").decode().strip(),
        "tree": git("rev-parse", "HEAD^{tree}").decode().strip(),
        "dirty": git("status", "--porcelain=v1", "--untracked-files=all").decode(),
    }


def metadata():
    result = {}
    for name in ("HEAD", "index", "config", "config.worktree", "info/sparse-checkout"):
        path = Path(git("rev-parse", "--path-format=absolute", "--git-path", name).decode().strip())
        result[name] = {"path": str(path), "sha256": digest(path.read_bytes()) if path.exists() else None}
    locks = {}
    for name in ("index.lock", "HEAD.lock", "config.lock", "shallow.lock"):
        path = Path(git("rev-parse", "--path-format=absolute", "--git-path", name).decode().strip())
        locks[str(path)] = path.exists()
    if any(locks.values()):
        raise RuntimeError("active source Git lock")
    result["locks"] = locks
    result["cargo_lock_sha256"] = digest((REPO / "codex-rs/Cargo.lock").read_bytes())
    return result


def snapshot(label):
    names = git("ls-files", "-z") + git("ls-files", "--others", "--exclude-standard", "-z")
    rows = []
    for name in sorted(set(names.split(b"\0")) - {b""}):
        relative = os.fsdecode(name)
        path = REPO / relative
        if not path.exists() and not path.is_symlink():
            raise RuntimeError("missing inventory path: " + relative)
        body = os.fsencode(os.readlink(path)) if path.is_symlink() else path.read_bytes()
        rows.append({
            "path": relative,
            "mode": "120000" if path.is_symlink() else ("100755" if path.stat().st_mode & 0o111 else "100644"),
            "bytes": len(body),
            "sha256": digest(body),
            "blob": hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest(),
        })
    encoded = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    with gzip.open(RECORDS / (label + ".files.json.gz"), "xb") as stream:
        stream.write(encoded)
    value = {**identity(), "file_count": len(rows), "inventory_sha256": digest(encoded)}
    save(label + ".json", value)
    return value


result = {"source_sha": SOURCE, "tree": TREE, "qualification": False, "boundary": BOUNDARY, "started_at": now()}
before = None
metadata_before = None
status = 1
try:
    if identity() != {"commit": SOURCE, "tree": TREE, "dirty": ""}:
        raise RuntimeError("expected exact clean cc22 source")
    metadata_before = metadata()
    save("metadata-before.json", metadata_before)
    before = snapshot("source-before")
    if before["file_count"] != 14842:
        raise RuntimeError("expected complete 14842-file cc22 inventory")
    for relative, expected in VERIFIER_PINS.items():
        if digest((REPO / relative).read_bytes()) != expected:
            raise RuntimeError("unchanged verifier pin: " + relative)
    source = (REPO / "CALLERS.toml").read_text()
    if digest(source.encode()) != BASE_SHA or source.count(OLD_LINE) != 1:
        raise RuntimeError("exact original caller manifest")
    patched = source.replace(OLD_LINE, NEW_LINE)
    if digest(patched.encode()) != POST_SHA:
        raise RuntimeError("exact single-caller postimage")
    baseline = tomllib.loads(source)
    amended = tomllib.loads(patched)
    if len(baseline["boundary"]) != 534 or len(baseline["protected_file"]) != 386:
        raise RuntimeError("exact unchanged closed inventory counts")
    narrowed = copy.deepcopy(amended)
    changed = next(row for row in narrowed["boundary"] if row["id"] == BOUNDARY)
    if changed["product_callers"].pop() != CALLER or narrowed != baseline:
        raise RuntimeError("delta must only add the actual original readonly caller")
    save("manifest-delta.json", {"base_sha256": BASE_SHA, "post_sha256": POST_SHA, "boundaries": 534, "protected_files": 386, "only_caller_added": CALLER, "all_other_values_unchanged": True})

    sys.path.insert(0, str(REPO / "scripts"))
    spec = importlib.util.spec_from_file_location("exact_sourcebound_full_index_proof", REPO / "scripts/verify_hepta_callers.py")
    proof = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = proof
    spec.loader.exec_module(proof)
    originals = proof._boundary_rows(baseline)
    updated = proof._boundary_rows(amended)
    proof._verify_privileged_inventory(baseline, originals)
    proof._verify_privileged_inventory(amended, updated)
    old = next(row for row in originals if row.identifier == BOUNDARY)
    new = next(row for row in updated if row.identifier == BOUNDARY)
    ignored = proof._string_tuple(baseline, "ignored_path_fragments")
    files = proof._source_files(REPO, proof._string_tuple(baseline, "source_roots"))
    index = {}
    input_rows = []
    for path in files:
        raw = path.read_bytes()
        relative = path.relative_to(REPO).as_posix()
        input_rows.append({"path": relative, "bytes": len(raw), "sha256": digest(raw)})
        index[relative] = proof._strip_cfg_test_items(proof._strip_rust_non_code(raw.decode()))
    encoded = json.dumps(input_rows, sort_keys=True, separators=(",", ":")).encode()
    with gzip.open(RECORDS / "full-rust-index.files.json.gz", "xb") as stream:
        stream.write(encoded)
    result.update(rust_files_scanned=len(files), full_rust_index_sha256=digest(encoded))
    print(json.dumps({"phase": "full-index-built", "rust_files_scanned": len(files), "index_sha256": digest(encoded)}), flush=True)

    try:
        proof._verify_boundary(REPO, old, index, ignored)
    except proof.VerificationFailure as error:
        original_failure = str(error)
        expected = BOUNDARY + ": caller set mismatch; missing=[], unexpected=['" + CALLER + "']"
        if original_failure != expected:
            raise RuntimeError("unexpected baseline failure: " + original_failure) from error
    else:
        raise RuntimeError("baseline unexpectedly admitted omitted real caller")
    save("before-failure.json", {"expected_failure_observed": True, "error": original_failure})
    after = proof._verify_boundary(REPO, new, index, ignored)
    save("after-pass.json", after)

    attacks = {
        "unregistered_original_training_readback_service.rs": (REPO / CALLER).read_text(),
        "unregistered_sourcebound_readback_ufcs.rs": "async fn unexpected(owner: &SourceBoundCellQ24TrainingStageV1, dataset: &LearningIterationSnapshotV1) { SourceBoundCellQ24TrainingStageV1::readback(owner, dataset).await; }\n",
        "unregistered_sourcebound_readback_method.rs": "async fn unexpected(owner: &SourceBoundCellQ24TrainingStageV1, dataset: &LearningIterationSnapshotV1) { owner.readback(dataset).await; }\n",
    }
    negative = []
    attack_dir = RECORDS / "unregistered-callers"
    attack_dir.mkdir(mode=0o700)
    for name, body in attacks.items():
        (attack_dir / name).write_text(body)
        relative = "codex-rs/hepta-agentd/src/" + name
        if relative in index:
            raise RuntimeError("attack path already exists")
        altered = dict(index)
        altered[relative] = proof._strip_cfg_test_items(proof._strip_rust_non_code(body))
        try:
            proof._verify_boundary(REPO, new, altered, ignored)
        except proof.VerificationFailure as error:
            if str(error) != BOUNDARY + ": caller set mismatch; missing=[], unexpected=['" + relative + "']":
                raise RuntimeError("unrelated refusal does not prove caller closure") from error
            negative.append({"path": relative, "source_sha256": digest(body.encode()), "error": str(error), "rejected": True})
        else:
            raise RuntimeError("unregistered real Rust caller accepted: " + relative)
    save("unregistered-callers-rejected.json", negative)
    result.update(status="passed", before_failure=original_failure, after=after, unregistered_callers_rejected=len(negative), verifier_unchanged=True, authority_granted=False)
    status = 0
except Exception as error:
    result.update(status="failed", error=type(error).__name__ + ": " + str(error))
    traceback.print_exc()
finally:
    if before is not None:
        try:
            after_source = snapshot("source-after")
            result.update(before=before, after_source=after_source)
            if before != after_source:
                raise RuntimeError("checked source inventory changed")
        except Exception as error:
            result.update(status="failed", inventory_error=type(error).__name__ + ": " + str(error))
            status = 1
    if metadata_before is not None:
        try:
            metadata_after = metadata()
            save("metadata-after.json", metadata_after)
            if metadata_before != metadata_after:
                raise RuntimeError("source Git metadata changed")
            for relative, expected in VERIFIER_PINS.items():
                if digest((REPO / relative).read_bytes()) != expected:
                    raise RuntimeError("verifier changed during check")
        except Exception as error:
            result.update(status="failed", metadata_error=type(error).__name__ + ": " + str(error))
            status = 1
    result.update(exit_code=status, finished_at=now())
    save("result.json", result)
    print(json.dumps(result, sort_keys=True), flush=True)
sys.exit(status)
