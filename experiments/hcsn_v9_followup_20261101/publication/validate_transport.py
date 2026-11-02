"""Exercise exact recovery, idempotence, corruption and path containment."""

import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from .restore import checked_path, restore


def main():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "publication/TRANSPORT.json").read_text())
    checks = []
    with tempfile.TemporaryDirectory() as temporary:
        trial = Path(temporary)
        (trial / "publication").mkdir()
        shutil.copyfile(root / "publication/TRANSPORT.json", trial / "publication/TRANSPORT.json")
        for part in manifest["parts"]:
            shutil.copyfile(root / part["path"], trial / part["path"])
        first = restore(trial)
        checks.append({"name": "exact_compressed_byte_recovery", "passed": first["sha256"] == manifest["original"]["sha256"]})
        checks.append({"name": "existing_identical_bytes_idempotent", "passed": restore(trial) == first})
        original = trial / manifest["original"]["path"]
        original.write_bytes(b"corrupt")
        try:
            restore(trial)
        except ValueError:
            checks.append({"name": "refuse_overwrite_divergent_evidence", "passed": True})
        else:
            raise AssertionError("Divergent output accepted")
        original.unlink()
        part = trial / manifest["parts"][-1]["path"]
        data = part.read_bytes()
        part.write_bytes(bytes([data[0] ^ 1]) + data[1:])
        try:
            restore(trial)
        except ValueError:
            checks.append({"name": "corrupt_part_rejected", "passed": True})
        else:
            raise AssertionError("Corrupt part accepted")
        assert not original.exists()
        checks.append({"name": "corruption_creates_no_output", "passed": True})
        try:
            checked_path(trial, "../escape")
        except ValueError:
            checks.append({"name": "path_escape_rejected", "passed": True})
        else:
            raise AssertionError("Escaping path accepted")
    assert all(x["passed"] for x in checks)
    report = {"checks": checks, "passed": len(checks), "source_sha256": {
        name: hashlib.sha256((root / "publication" / name).read_bytes()).hexdigest()
        for name in ("restore.py", "validate_transport.py", "TRANSPORT.json")}}
    (root / "publication/VALIDATION.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": len(checks)}))


if __name__ == "__main__":
    main()
