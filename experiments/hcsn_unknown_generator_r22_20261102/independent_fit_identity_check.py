"""Read-only exact source/input/model identity check, separate from numeric auditing."""

import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).parent


def main():
    directory = ROOT / "development_fit_final"
    identity = json.loads((directory / "FIT_IDENTITY.json").read_text())
    checks = {}
    for name, expected in identity["source_files"].items():
        actual = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        assert actual == expected, name
        checks[name] = actual
    input_path = ROOT.parent / identity["input_path"]
    assert hashlib.sha256(input_path.read_bytes()).hexdigest() == identity["input_sha256"]
    checks[identity["input_path"]] = identity["input_sha256"]
    for name, expected in identity["files"].items():
        data = (directory / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == expected["sha256"]
        assert hashlib.sha256(gzip.decompress(data)).hexdigest() == expected["raw_sha256"]
        checks["development_fit_final/" + name] = expected["sha256"]
    audit = json.loads((ROOT / "INDEPENDENT_FITTED_MODEL_CHECK.json").read_text())
    assert audit["checker_sha256"] == hashlib.sha256((ROOT / "independent_model_check.py").read_bytes()).hexdigest()
    assert audit["model_gzip_sha256"] == identity["files"]["MODELS.json.gz"]["sha256"]
    assert audit["passed"] and not identity["new_calibration_worlds_opened"] and not identity["new_confirmation_worlds_opened"]
    print(json.dumps(dict(passed=True, checked_objects=checks, numeric_audit_checker_identity_matches=True,
        source_inputs_or_models_modified=False, new_world_generator_called=False), sort_keys=True))


if __name__ == "__main__":
    main()
