"""Exercise qualification boundaries against actual completed development files."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import shutil
import tempfile

import torch

from .actor import LatentSnapshot
from .evaluation import qualification_corpus
from .grid_guard import verify_development_run
from .protocol import checksum, write_json
from .qualification_guard import label_pin, verify_density, verify_source_grid
from .run import base_model


def preflight(assets, prior, development, allocation, output):
    results = []

    def rejects(name, call, message):
        try:
            call()
        except ValueError as error:
            if message not in str(error):
                raise AssertionError(f"Unexpected failure for {name}: {error}") from error
            results.append({"check": name, "status": "rejected_before_prediction", "error": str(error)})
        else:
            raise AssertionError(f"{name} was accepted")

    pins = verify_development_run(development)
    corpus = qualification_corpus(assets, allocation)
    base, _ = base_model(prior, 17)
    snapshot = LatentSnapshot.load(development / "seed-17-direct_risk-step-600.pt", base)
    density = verify_density(snapshot, development, 17)
    snapshot.sigma *= 2
    rejects("changed_deployment_sigma", lambda: verify_density(snapshot, development, 17), "density differs")
    snapshot.sigma /= 2
    snapshot.basis[0, 0] += .01
    rejects("changed_deployment_basis", lambda: verify_density(snapshot, development, 17), "basis differs")
    manifest = json.loads(allocation.read_text())
    changed = deepcopy(manifest)
    changed["splits"]["control_test"]["source_ids"][0] = corpus.splits["test"].ids[0]
    rejects("source_overlap_between_studies", lambda: verify_source_grid(changed, corpus.splits), "sources overlap")
    changed = deepcopy(manifest)
    changed["splits"]["joint_test"]["source_ids"][1] = changed["splits"]["joint_test"]["source_ids"][0]
    import hashlib
    changed["splits"]["joint_test"]["identity_sha256"] = hashlib.sha256(
        "\n".join(changed["splits"]["joint_test"]["source_ids"]).encode()).hexdigest()
    with tempfile.TemporaryDirectory() as temporary:
        temporary = Path(temporary)
        duplicate = temporary / "duplicate-sources.json"
        write_json(duplicate, changed)
        rejects("duplicate_source_even_with_updated_manifest_digest",
                lambda: qualification_corpus(assets, duplicate), "Repeated source")
        labels = temporary / "labels"
        (labels / "ndu-data").mkdir(parents=True)
        shutil.copyfile(assets / "RESTORATION.json", labels / "RESTORATION.json")
        label_path = "ndu-data/t10k-labels-idx1-ubyte.gz"
        data = bytearray((assets / label_path).read_bytes())
        data[-1] ^= 1
        (labels / label_path).write_bytes(data)
        rejects("changed_official_labels", lambda: label_pin(labels), "labels changed")
        # Symlinks keep immutable fixtures shared; every mutation unlinks first.
        copy = temporary / "development"
        copy.mkdir()
        for path in development.iterdir():
            (copy / path.name).symlink_to(path.resolve(), target_is_directory=path.is_dir())
        report = copy / "SELECTION-17-direct_risk.json"
        changed = json.loads(report.read_text())
        changed["candidates"][1]["metrics"]["quality"]["ce"] += .1
        report.unlink()
        write_json(report, changed)
        rejects("unsealed_validation_report", lambda: verify_development_run(copy), "sealed aggregate")
        report.unlink()
        report.symlink_to(development / report.name)
        checkpoint = copy / "seed-17-direct_risk-step-200.pt"
        data = bytearray(checkpoint.read_bytes())
        data[-1] ^= 1
        checkpoint.unlink()
        checkpoint.write_bytes(data)
        rejects("changed_scored_checkpoint", lambda: verify_development_run(copy), "checkpoint changed")
    if verify_development_run(development) != pins:
        raise AssertionError("The negative checks changed original development files")
    write_json(output, {"status": "passed", "checks": results,
        "valid_actual_density": density, "development_pins": pins,
        "allocation_sha256": checksum(allocation),
        "new_test_predictions_computed": False,
        "source_boundary_check_only": True,
        "original_development_unchanged": True})
    print(json.dumps({"status": "passed", "rejected_mutations": len(results), "new_test_predictions_computed": False}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("assets", "prior", "development", "allocation", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    preflight(args.assets.resolve(), args.prior.resolve(), args.development.resolve(),
              args.allocation.resolve(), args.output.resolve())
