"""Standard-library replay of complete stored native financial verification."""
import gzip
import hashlib
import json
import math
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    summary = json.loads((root / "confirmation_01/SUMMARY.json").read_text())
    protocol = json.loads((root / "PROTOCOL.json").read_text())
    raw = gzip.decompress((root / "confirmation_01/RAW.json.gz").read_bytes())
    assert hashlib.sha256(raw).hexdigest() == summary["raw_sha256"]
    data = json.loads(raw)
    assert not data["failures"] and len(data["models"]) == 72
    assert len(data["cdf"]) == 129 and len(data["rejections"]) == 7
    checks, largest = 0, dict(boundary_vs_mp=0., model_vs_r12=0., row_mass=0., prior_mass=0., cdf_relative=0.)
    for row in data["models"]:
        value, reference = row["native"], row["reference"]
        assert len(value) == len(reference) == 2001
        for a, b in zip(value, reference, strict=True):
            assert math.isfinite(a) and math.isfinite(b)
            checks += 1
        difference = max(abs(a-b) for a, b in zip(value, reference, strict=True))
        assert difference == row["errors"]["model_vs_r12"]
        largest["model_vs_r12"] = max(largest["model_vs_r12"], difference)
        largest["boundary_vs_mp"] = max(largest["boundary_vs_mp"], abs(value[0]-row["mp_boundary"]))
        q = [value[1+i*40:1+(i+1)*40] for i in range(40)]
        for i, rates in enumerate(q):
            assert rates[i] <= 0 and all(x >= 0 for j, x in enumerate(rates) if j != i)
            assert abs(sum(rates)) <= protocol["mass_tolerance"]
            largest["row_mass"] = max(largest["row_mass"], abs(sum(rates)))
            checks += 1
        assert min(value[-40:]) >= 0
        assert abs(sum(value[-40:])-1) <= protocol["mass_tolerance"]
        largest["prior_mass"] = max(largest["prior_mass"], abs(sum(value[-40:])-1))
        for start, columns in ((1601, 5), (1801, 4)):
            for i in range(40):
                emission = value[start+i*columns:start+(i+1)*columns]
                assert min(emission) >= 0 and abs(sum(emission)-1) <= 2e-15
                checks += 1
    for row in data["cdf"]:
        assert 0 < row["native"] <= 1 and 0 < row["reference"] <= 1
        error = abs(row["native"]-row["reference"])/row["reference"]
        assert error == row["relative"] and error <= protocol["cdf_relative_tolerance"]
        largest["cdf_relative"] = max(largest["cdf_relative"], error)
        checks += 1
    for row in data["rejections"]:
        assert row["exit_code"] == 2 and row["stderr"] and row["passed"]
        checks += 1
    for name, digest in summary["source_sha256"].items():
        assert hashlib.sha256((root/name).read_bytes()).hexdigest() == digest
        checks += 1
    assert largest["model_vs_r12"] <= protocol["model_tolerance"]
    assert largest["boundary_vs_mp"] <= protocol["boundary_tolerance"]
    output = dict(passed=True, checks=checks, stored_models=72, stored_cdf=129,
        raw_sha256=summary["raw_sha256"], largest_replayed=largest,
        scope="Standard-library stored-record algebra/support/source audit. Independent 80-digit arithmetic is in the frozen original verifier, not recomputed by this checker.",
        production_activation=False, all_blockers_closed=False)
    (root/"RECORD_AUDIT.json").write_text(json.dumps(output, indent=2)+'\n')
    print(json.dumps(output))


if __name__ == "__main__":
    main()
