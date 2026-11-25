"""Run both real identity readers on retained engineering inputs and file controls.

Temporary distribution metadata is deliberately synthetic. No dependency code,
model, training, native owner, paid service or frozen experiment is executed.
"""

import argparse
import copy
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import zipfile


ARCHIVE_SHA256 = "db8549ee2f08810072571f2aa3892ff518277fa371f1029566d78a11b7e89360"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def run(hepta_root, chain_root):
    sys.path[:0] = [str(hepta_root / "scripts"), str(chain_root / "scripts")]
    from cell_experiments import data, paired_loop, runtime_artifacts
    import dev_circuit_evaluation as evaluation
    import dev_loop_identity as chain
    import dev_runtime_artifacts as chain_artifacts

    controls = []

    def rejected(name, action):
        try:
            action()
        except (ValueError, OSError):
            controls.append(name)
        else:
            raise ValueError("control unexpectedly accepted: " + name)

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        archive_path = hepta_root / "qualification/paired-consumer-use-20261123/CONSUMER_ENGINEERING_ORIGINALS.zip"
        archive_bytes = archive_path.read_bytes()
        require(hashlib.sha256(archive_bytes).hexdigest() == ARCHIVE_SHA256,
                "the retained engineering archive commitment changed")
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            database = root / "original.sqlite"
            database.write_bytes(archive.read("original/intake/intake.sqlite"))
            with sqlite3.connect(database) as connection:
                admissions = connection.execute("SELECT id,binding,state,request_sha FROM admissions").fetchall()
                settings = connection.execute("SELECT value FROM settings").fetchall()
            require(len(admissions) == len(settings) == 1, "ambiguous original engineering intake")
            admission_id, binding_json, state, request_sha = admissions[0]
            binding = json.loads(binding_json)
            config = json.loads(settings[0][0])
            require(state == "released" and admission_id == data.digest(binding),
                    "the original engineering admission differs")
            require(config["scope"] == binding["release"]["scope"] == "engineering_fixture",
                    "this qualification only accepts the original engineering fixture")
            request = json.loads(archive.read("original/intake/" + data.digest(binding) + "/paired.json"))
            require(request_sha == data.digest(request), "the original request commitment differs")
        materials = root / "synthetic-distributions"
        materials.mkdir()
        roots = []
        for package in paired_loop.PACKAGES:
            module = materials / package
            module.mkdir()
            (module / "__init__.py").write_bytes(b"# synthetic fixture; never imported\n")
            metadata = materials / (package + "-0.0.dist-info")
            metadata.mkdir()
            (metadata / "METADATA").write_text("Name: " + package + "\nVersion: 0.0\n")
            listed = [package + "/__init__.py", metadata.name + "/METADATA", metadata.name + "/RECORD"]
            (metadata / "RECORD").write_text("".join(path + ",,\n" for path in listed))
            roots += [module.name, metadata.name]
        manifest = runtime_artifacts.snapshot(materials, sorted(roots))
        require(manifest == chain_artifacts.snapshot(materials, sorted(roots)), "independent inventories differ")
        sys.path.insert(0, str(materials))
        try:
            runtime = paired_loop.implementation(runtime_artifacts_manifest=manifest, runtime_artifacts_root=materials)
            observed = chain.runtime_identity(evaluation.source_files(hepta_root / "scripts/cell_experiments"),
                                              runtime_artifacts=manifest, artifact_root=materials)
            require(runtime == observed, "independent implementation identities differ")
            identity = paired_loop.identity(config, binding, request, runtime)
            pin = data.digest(identity)
            frozen = {key: request[key] for key in ("parent", "candidate", "retention", "timeout_seconds")}
            frozen["schema"] = "hepta.paired-cold.freeze.v1"
            release = identity["release"]
            require(chain.validate(identity, pin, release, request, frozen, runtime=observed) == pin,
                    "the Chain reader refused the Hepta-produced identity")
            require(chain.schemas(identity) == (chain.ARTIFACT_ADMISSION, chain.ARTIFACT_DELIVERY),
                    "the new identity selected a legacy request namespace")
            controls += ["independent_inventory_equal", "independent_runtime_equal", "hepta_identity_consumed_by_chain", "v3_namespace_selected"]
            for field in ("parent_sha256", "candidate_sha256", "evaluation_sha256", "router_sha256", "source_exposure_sha256"):
                changed = copy.deepcopy(identity)
                changed[field] = "f" * 64
                rejected(field, lambda changed=changed: chain.validate(changed, data.digest(changed), release,
                                                                       request, frozen, runtime=observed))
            changed = copy.deepcopy(identity)
            changed["native_consent_sha256"] = "f" * 64
            rejected("independently_retained_consent_pin", lambda: chain.validate(changed, pin, release, request, frozen))
            changed = copy.deepcopy(identity)
            changed["implementation"]["runtime_closure_complete"] = True
            rejected("unearned_complete_closure", lambda: chain.validate(changed, data.digest(changed), release, request, frozen))
            target = materials / paired_loop.PACKAGES[0] / "__init__.py"
            target.write_bytes(b"# changed bytes; version remains 0.0\n")
            rejected("hepta_same_version_changed_bytes", lambda: runtime_artifacts.verify_installed(manifest, materials, paired_loop.PACKAGES))
            rejected("chain_same_version_changed_bytes", lambda: chain_artifacts.verify_installed(manifest, materials, chain.PACKAGES))
        finally:
            sys.path.remove(str(materials))
    return {"schema": "hepta-chain-identity-engineering-check-v1", "status": "PASS", "controls": controls,
            "controls_passed": len(controls), "synthetic_distribution_metadata": True,
            "original_engineering_archive_sha256": ARCHIVE_SHA256,
            "loop_sha256": pin, "implementation_sha256": data.digest(runtime),
            "real_user_adoptions": 0, "model_calls": 0, "training_runs": 0,
            "runtime_closure_complete": False, "production_authorization_available": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hepta-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--chain-root", type=Path, required=True)
    arguments = parser.parse_args()
    print(json.dumps(run(arguments.hepta_root.resolve(strict=True), arguments.chain_root.resolve(strict=True)), sort_keys=True))


if __name__ == "__main__":
    main()
