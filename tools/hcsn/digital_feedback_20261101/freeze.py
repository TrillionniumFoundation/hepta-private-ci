"""Bind every registered fit/model and actual training provenance before worlds."""
import argparse
from datetime import datetime, timezone
from pathlib import Path

from .factors import candidates
from .study import digest, read, require_confirmation_qualification, required_training_files, sources, write
from .training import digest as object_digest


def manifest(training, protocol_path, source_commit):
    protocol = read(protocol_path)
    identity = sources(protocol_path)
    if len(source_commit) != 40 or set(source_commit) - set("0123456789abcdef"):
        raise ValueError("published source commit required")
    expected_fits = protocol["fits"]
    if len(expected_fits) < 2 or len(expected_fits) != len(set(expected_fits)):
        raise ValueError("unique registered independent fits required")
    if read(training / "LAUNCH.json")["source_sha256"] != identity:
        raise ValueError("training launch was not bound to current sources")
    files, processes, all_receipts = {}, {}, {}
    for fit in expected_fits:
        fitted = training / f"fit_{fit}"
        process = training / "process_receipts" / f"fit_{fit}.json"
        if read(process)["returncode"] != 0 or (fitted / "FAILED.json").exists():
            raise ValueError(f"incomplete registered fit {fit}; failure must remain visible")
        processes[str(fit)] = digest(process)
        for name in ("STARTED.json", "FINISHED.json"):
            if read(fitted / name)["source_sha256"] != identity:
                raise ValueError(f"fit {fit} source changed before/during fitting")
        if read(fitted / "STARTED.json")["protocol"] != protocol:
            raise ValueError("actual fitted protocol differs")
        files[str(fit)] = {path: digest(fitted / path) for path in required_training_files()}
        all_receipts[str(fit)] = {}
        for spec in candidates():
            name = spec["id"]
            receipt = read(fitted / "training" / (name + ".json.gz"))
            artifact = read(fitted / "models" / (name + ".json"))
            factors = {key: spec[key] for key in ("drift", "bank_driver", "event_sign_readout", "reset")}
            if (artifact["fit"] != fit or artifact["family"] != spec["family"]
                    or artifact["terminal_mode"] != spec["terminal_mode"] or artifact["factors"] != factors
                    or receipt["fit"] != fit or receipt["spec"] != spec
                    or receipt["returned_model_sha256"] != object_digest(artifact)):
                raise ValueError(f"fit/arm/model provenance mismatch: {fit}/{name}")
            all_receipts[str(fit)][name] = receipt
    from .quality import cost_audit
    cost = cost_audit(all_receipts, expected_fits=expected_fits,
                      expected_candidates=[c["id"] for c in candidates()],
                      between_arm_tolerance=protocol["between_arm_cpu_tolerance_seconds"],
                      budget_seconds=protocol["training_cpu_seconds"],
                      per_arm_tolerance=protocol["cpu_tolerance_seconds"])
    # A manifest retains noncompliance. Sealing and confirmation both reject it;
    # an arm cannot be deleted to manufacture matched CPU.
    return dict(schema="digital-feedback-all-model-manifest-v1", protocol=protocol,
                fits=expected_fits, source_sha256=identity, training_files_sha256=files,
                process_sha256=processes, published_source_commit=source_commit,
                created_utc=datetime.now(timezone.utc).isoformat(), cpu_matching=cost,
                confirmation_generated=False, every_attempt_retained=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("models", "seal"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--training", type=Path)
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--source-commit")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--models-commit")
    parser.add_argument("--remote-receipt", type=Path)
    args = parser.parse_args()
    if args.stage == "models":
        value = manifest(args.training, args.protocol, args.source_commit)
    else:
        value = read(args.manifest)
        require_confirmation_qualification(value)
        receipt = read(args.remote_receipt)
        if (receipt["commit"] != args.models_commit or not receipt["all_blob_hashes_verified"]
                or receipt["model_manifest_sha256"] != digest(args.manifest)):
            raise ValueError("model publication must be read back before confirmation")
        value.update(schema="digital-feedback-sealed-models-v1",
                     published_models_commit=args.models_commit,
                     remote_verification_file=str(args.remote_receipt.relative_to(args.output.parent)),
                     remote_verification_sha256=digest(args.remote_receipt),
                     model_manifest_sha256=digest(args.manifest),
                     sealed_utc=datetime.now(timezone.utc).isoformat())
    write(args.output, value)


if __name__ == "__main__":
    main()
