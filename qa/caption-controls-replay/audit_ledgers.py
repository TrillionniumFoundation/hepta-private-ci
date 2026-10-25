"""Full original derived ledger validation, isolated from the control runtime."""

import argparse
import importlib.util
import json
import math
from pathlib import Path
import platform
import sys

from replay import check_sources, digest, require


def equal(a, b):
    # Same comparison tolerances as the original 398-check independent audit.
    if isinstance(a, dict):
        return (
            isinstance(b, dict)
            and a.keys() == b.keys()
            and all(equal(a[k], b[k]) for k in a)
        )
    if isinstance(a, list):
        return (
            isinstance(b, list)
            and len(a) == len(b)
            and all(equal(x, y) for x, y in zip(a, b))
        )
    if isinstance(a, float):
        return isinstance(b, (int, float)) and math.isclose(
            a, b, rel_tol=1e-11, abs_tol=1e-12
        )
    return a == b


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    import numpy as np

    require(
        platform.python_version() == "3.12.14" and np.__version__ == "2.3.5",
        "audit runtime",
    )
    binding = json.loads((Path(__file__).parent / "bindings.json").read_bytes())
    check_sources(args.repo, binding)
    spec = importlib.util.spec_from_file_location(
        "prediction_ledger", args.repo / "qa/stem-bakeoff/prediction_ledger.py"
    )
    pl = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = pl
    spec.loader.exec_module(pl)
    report = json.loads((args.artifact / "results/report.json").read_bytes())
    require(
        report["authority"] == "DENY_ALL"
        and report["production_activation_allowed"] is False,
        "authority",
    )
    require(
        len(report["ledgers"]) == len(binding["original_ledgers"]) == 20, "ledger count"
    )
    validated = {}
    for key, pins in binding["original_ledgers"].items():
        record = report["ledgers"][key]
        require(all(record[k] == v for k, v in pins.items()), "ledger source binding")
        folder = args.artifact / "results" / record["directory"]
        m = json.loads((folder / "manifest.json").read_bytes())
        identity = pl.LedgerIdentityV1(**m["metadata"]["identity"])
        require(
            identity.data_sha256 == report["data_manifest_sha256"]
            and identity.plan_sha256 == report["plan_sha256"],
            "ledger identity",
        )
        # Unmodified original loader performs shape/dtype/budget validation,
        # recreates probabilities/predictions from logits, and requires exact
        # equality of every derived array plus the original canonical digest.
        ledger = pl.load_prediction_ledger(
            folder,
            expected_manifest_sha256=record["manifest_sha256"],
            expected_identity=identity,
        )
        require(ledger.ledger_sha256 == record["ledger_sha256"], "ledger digest")
        require(equal(ledger.metrics(), record["metrics"]), "derived metrics")
        require(
            equal(json.loads((folder / "rows.json").read_bytes()), ledger.rows()),
            "per-row derived values",
        )
        require(record["round_trip_verified"] is True, "original roundtrip receipt")
        validated[key] = ledger.ledger_sha256
    receipt = {
        "authority": "DENY_ALL",
        "production_activation_allowed": False,
        "status": "20_ORIGINAL_DERIVED_LEDGERS_VALIDATED_NOT_NEW_ACCEPTANCE",
        "numpy": np.__version__,
        "python": platform.python_version(),
        "python_executable": sys.executable,
        "python_prefix": sys.prefix,
        "original_hosted_numpy": report["environment"]["numpy"],
        "ledger_sha256": validated,
        "bindings_sha256": digest(
            (Path(__file__).parent / "bindings.json").read_bytes()
        ),
    }
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
