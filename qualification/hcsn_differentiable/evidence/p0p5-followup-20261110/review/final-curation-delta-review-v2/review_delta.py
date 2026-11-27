"""Read-only pinned curation delta and explicit JSON receipt bindings.

Do not run until the owner supplies a stable exact top-manifest SHA. Historical
review records stay opaque; old failed assemblies are not current manifests.
This program performs no training, model execution or numerical oracle calls.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import time
import traceback
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "final-curation-independent-review-v1/review_final_curation_v1.py"
spec = importlib.util.spec_from_file_location("retained_final_review_helpers", HELPER)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def pointer(value, path):
    for key in path.strip("/").split("/") if path else ():
        key = key.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--bindings", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    began = time.monotonic()
    repo = args.repository.resolve()
    base = repo / "qualification/hcsn_differentiable/evidence/p0p5-20261110"
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    report = {"schema": "independent-final-curation-delta-v2",
              "created_utc": datetime.now(timezone.utc).isoformat(),
              "expected_manifest_sha256": args.expected_manifest_sha256,
              "training_performed": False, "numerical_oracle_rerun": False,
              "native_runtime_reobserved": False, "scientific_admission": "HOLD",
              "overall_repository_CI_claim": False,
              "whole_training_qualification_granted": False}
    identities = {}

    def read(path):
        path = Path(path).resolve()
        raw = path.read_bytes()
        value = {"bytes": len(raw), "sha256": sha(raw)}
        helper.require(str(path) not in identities or identities[str(path)] == value,
                       "input changed between reads: " + str(path))
        identities[str(path)] = value
        return raw

    def curated(name):
        parts = name.split("!")
        path = (base / parts[0]).resolve()
        helper.require(path.is_relative_to(base), "escaped curated input")
        raw = read(path)
        for member in parts[1:]:
            from io import BytesIO
            with ZipFile(BytesIO(raw)) as zipped:
                raw = zipped.read(member)
        return raw

    def value(reference):
        raw = curated(reference["artifact"])
        if reference.get("transform") == "sha256":
            return sha(raw)
        selected = pointer(json.loads(raw), reference.get("pointer", ""))
        if reference.get("encoding") == "native_terminal_json":
            envelope = json.loads(selected["content"][0]["text"])
            payload = bytes.fromhex(envelope["bytes_hex"])
            helper.require(envelope["output_complete"] is True,
                           "incomplete archive-builder terminal")
            helper.require(sha(payload) == envelope["chunk_sha256"],
                           "archive-builder terminal chunk hash differs")
            selected = pointer(json.loads(payload), reference.get("payload_pointer", ""))
        if reference.get("transform") == "len":
            selected = len(selected)
        return selected * reference["scale"] if "scale" in reference else selected

    try:
        manifest_raw = read(base / "MANIFEST.json")
        helper.require(sha(manifest_raw) == args.expected_manifest_sha256, "curation snapshot changed before review")
        manifest = json.loads(manifest_raw)
        files = manifest["files"]
        for name, expected in files.items():
            path = (base / name).resolve()
            helper.require(path.is_relative_to(base), "unsafe manifest member")
            raw = read(path)
            helper.require({"bytes": len(raw), "sha256": sha(raw)} == expected, "manifest mismatch: " + name)
        actual = {str(p.relative_to(base)) for p in base.rglob("*") if p.is_file()}
        helper.require(actual == set(files) | {"MANIFEST.json"}, "unindexed or missing curated files")
        previous_path = ROOT / "final-curation-independent-review-v1/RESULT.json"
        previous = json.loads(read(previous_path))["manifest_file_identities"]
        report["delta_from_prior_v1"] = {
            "prior_result": str(previous_path), "prior_result_sha256": identities[str(previous_path)]["sha256"],
            "unchanged": sorted(n for n in files if previous.get(n) == files[n]),
            "changed": sorted(n for n in files if n in previous and previous[n] != files[n]),
            "added": sorted(set(files) - set(previous)), "removed": sorted(set(previous) - set(files)),
        }
        report["zip_checks"] = []
        for name in files:
            if name.endswith(".zip"):
                helper.audit_zip(curated(name), name, report["zip_checks"])
        documents = [repo / "qualification/hcsn_differentiable/CURRENT.md",
                     repo / "proposals/localization-v3/README.md", base / "README.md",
                     base / "p1/width16-v6/INDEX.md"]
        for path in documents:
            read(path)
        links = [item for path in documents for item in helper.local_links(path, repo)]
        helper.require(all(item["exists"] for item in links), "broken relative document link")
        report["relative_markdown_links"] = links
        costs = json.loads(curated("COSTS.json"))
        rows = {row["id"]: row for row in costs["rows"]}
        helper.require(len(rows) == len(costs["rows"]), "duplicate cost id")
        refs = []
        for row in costs["rows"]:
            raw = curated(row["artifact"])
            refs.append({"row": row["id"], "artifact": row["artifact"], "artifact_sha256": sha(raw)})
        report["cost_artifact_references"] = refs
        checks = json.loads(read(args.bindings))
        report["explicit_receipt_checks"] = []
        for check in checks:
            left = value(check["target"])
            if "expected" in check:
                right = check["expected"]
            elif "sum_sources" in check:
                right = sum(value(item) for item in check["sum_sources"])
            else:
                right = value(check["source"])
            helper.require(left == right, "receipt binding differs: " + check["id"])
            report["explicit_receipt_checks"].append({**check, "verified_value": left, "passed": True})
        report["status_snapshot"] = json.loads(curated("STATUS.json"))
        report["assets_snapshot"] = json.loads(curated("assets.json"))
        report["cost_unknowns"] = {key: costs.get(key) for key in
            ("accounting_complete", "total_elapsed_seconds", "total_energy_joules", "total_currency_cost", "peak_vram_bytes", "unresolved_cost_items")}
        report["manifest_files_checked"] = len(files)
        helper.require(all(helper.identity(path) == expected for path, expected in identities.items()), "reviewed input changed during check")
        report.update(integrity_passed=True, reviewed_inputs_unchanged=True)
    except Exception:
        report.update(integrity_passed=False, error=traceback.format_exc())
    report.update(inputs=identities,
                  reviewer_source_sha256=helper.identity(__file__)["sha256"],
                  retained_helper_source_sha256=helper.identity(HELPER)["sha256"],
                  review_elapsed_sample_before_serialization_seconds=time.monotonic()-began,
                  review_process_cpu_sample_seconds=time.process_time(),
                  scope="Pinned local source chain, all curated identities, nested ZIP safety, four document file links and declared exact receipt bindings. Claim interpretation is a separate accompanying static review; external endpoints and live training are not reobserved.")
    with (out / "RESULT.json").open("x") as stream:
        stream.write(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)+"\n")
    summary = {key: report.get(key) for key in ("schema", "expected_manifest_sha256", "integrity_passed", "reviewed_inputs_unchanged", "manifest_files_checked", "error", "scientific_admission", "review_elapsed_sample_before_serialization_seconds")}
    summary.update(result_sha256=helper.identity(out / "RESULT.json")["sha256"],
                   nested_archives_checked=len(report.get("zip_checks", [])),
                   relative_links_checked=len(report.get("relative_markdown_links", [])),
                   cost_references_checked=len(report.get("cost_artifact_references", [])),
                   explicit_receipt_checks=len(report.get("explicit_receipt_checks", [])))
    with (out / "SUMMARY.json").open("x") as stream:
        stream.write(json.dumps(summary, indent=2, sort_keys=True)+"\n")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if report["integrity_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
