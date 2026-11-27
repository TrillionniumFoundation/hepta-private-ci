"""Supplementary post-audit file census; no optimizer or label access."""

import argparse
import hashlib
import json
from pathlib import Path


def file_hash(path):
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        raise ValueError("ordinary sealed member required")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def verify(run, audit, output):
    run, audit, output = map(Path, (run, audit, output))
    if output.exists():
        raise ValueError("new sidecar output required")
    reviewed = json.loads(audit.read_bytes())
    seal_path = run / "diagnostic_seal.json"
    seal = json.loads(seal_path.read_bytes())
    actual = {p.relative_to(run).as_posix(): p for p in run.rglob("*") if p.is_file() and p != seal_path}
    if (reviewed["status"] != "PASS" or file_hash(seal_path) != reviewed["run_seal_sha256_before"]
            or set(actual) != set(seal["files"])):
        raise ValueError("original audit/seal/census differs")
    for name, path in actual.items():
        pin = seal["files"][name]
        if file_hash(path) != pin["sha256"] or path.stat().st_size != pin["bytes"]:
            raise ValueError("post-audit member changed: " + name)
    result = {"schema": "hepta.common-terminal-post-audit-seal.v8", "status": "PASS",
        "audit_sha256": file_hash(audit), "run_seal_sha256": file_hash(seal_path),
        "members_verified": len(actual), "source_sha256": file_hash(__file__),
        "new_optimizer_steps": 0, "selection_labels_accessed": False,
        "cost_scope_note": "Producer clock is sampled before its final report/seal writes; those finalization costs are not in its recorded CPU/wall total."}
    output.write_text(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False)+"\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run", "audit", "output"):
        parser.add_argument("--" + name, required=True)
    print(json.dumps(verify(**vars(parser.parse_args())), sort_keys=True))
