#!/usr/bin/env python3
"""Stage a pinned native research evidence package in /tmp; never edit a repo.

The spec supplies the run directory, report/source/binary pins, two independent
checkers and observations, original logs with their captured source commits,
and an optional GitHub commit object for a same-tree publication mapping.
No model, benchmark, tests, build, network request or publication is executed.
"""
import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess

MAX_BLOB = 511999
MAX_LOG = 16 * 1024 * 1024
MODES = ("gated", "linear")
CASES = ("paired", "missing_text", "missing_image", "shuffled_image", "mixed_presence")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode() + b"\n"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_pinned(path, digest, limit=MAX_BLOB):
    path = Path(path)
    require(not path.is_symlink() and path.is_file(), "regular source required: " + str(path))
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    require(len(raw) <= limit and sha(raw) == digest, "source pin/budget differs: " + str(path))
    return raw


def package(spec_path, output):
    with Path(spec_path).open("rb") as stream:
        spec_raw = stream.read(65537)
    require(len(spec_raw) <= 65536, "package spec byte budget")
    spec = json.loads(spec_raw)
    require(spec["schema"] == "hepta.native-evidence-package-inputs.v1", "spec schema differs")
    require(all(type(spec[key]) is str and re.fullmatch(r"[0-9a-f]{40}", spec[key])
                for key in ("source_sha", "source_tree")), "exact source and tree SHA required")
    repository = Path(spec["repository_path"]).resolve(strict=True)
    source = Path(spec["source_directory"]).resolve(strict=True) / "native-results"
    destination = Path(output).resolve()
    require(destination.is_relative_to(Path("/tmp")) and not destination.is_relative_to(repository)
            and not destination.exists() and destination.parent.is_dir(),
            "a new /tmp staging directory is required; repository writes are forbidden")
    report_raw = read_pinned(source / "report.json", spec["expected_report_sha256"])
    report = json.loads(report_raw)
    identity = report["source_identity"]
    require(report["schema"] == "hepta.native-task-head-replay.v1" and report["status"] == "PASS"
            and report["head_cost_measured"] is True, "complete native parity/cost report required")
    require(identity["git_head_sha"] == spec["source_sha"] and identity["git_tree_sha"] == spec["source_tree"]
            and identity["working_tree_clean"] is True, "report source differs from package spec")
    tree = subprocess.check_output(["git", "-C", str(repository), "rev-parse", spec["source_sha"] + "^{tree}"], text=True).strip()
    require(tree == spec["source_tree"], "local committed source tree differs")
    binary = spec["release_binary"]
    read_pinned(binary["path"], binary["sha256"], 512 * 1024 * 1024)
    require(binary["sha256"] == report["binary_sha256"], "release binary report binding differs")
    require(report["mode"] == "SHADOW_ONLY" and report["authority"] == "DENY_ALL"
            and report["production_activation_allowed"] is False
            and report["target_device_qualified"] is False and report["energy_joules"] is None
            and report["new_training_or_calibration"] is False and report["new_independent_quality_trial"] is False,
            "native report scope exceeds research execution")
    expected_files = {f"{mode}-{case}.jsonl" for mode in MODES for case in CASES}
    expected_files |= {f"{mode}-head/{name}" for mode in MODES for name in ("manifest.json", "weights.f32le")}
    expected_files |= {f"{mode}-cost.json" for mode in MODES}
    require(set(report["retained_file_sha256"]) == expected_files, "final retained inventory differs")
    payloads, origins = {}, {}
    def retain(name, raw, origin):
        require(name not in payloads and len(raw) <= MAX_BLOB, "duplicate or oversized repository blob")
        payloads[name], origins[name] = raw, origin
    retain("native-results/report.json", report_raw, {"kind": "unchanged_original", "path": str(source / "report.json")})
    for name in sorted(expected_files):
        raw = read_pinned(source / name, report["retained_file_sha256"][name])
        retain("native-results/" + name, raw, {"kind": "unchanged_original", "path": str(source / name)})
    artifacts = spec["independent"]
    require(set(artifacts) == {"native_checker", "cost_checker", "native_observation", "cost_observation"},
            "two independent checkers and observations required")
    names = {"native_checker": "checks/independent_native_check.py",
             "cost_checker": "checks/independent_cost_check.py",
             "native_observation": "checks/native-observation.json",
             "cost_observation": "checks/cost-observation.json"}
    loaded = {}
    for key, value in artifacts.items():
        raw = read_pinned(value["path"], value["sha256"])
        retain(names[key], raw, {"kind": "unchanged_independent_observation", "path": value["path"]})
        if key.endswith("observation"):
            loaded[key] = json.loads(raw)
    observation, cost_observation = loaded["native_observation"], loaded["cost_observation"]
    for key, value in loaded.items():
        require(value["status"] == "PASS" and value["native_report_sha256"] == spec["expected_report_sha256"],
                "independent observation belongs to another report")
        checker_key = key.replace("observation", "checker")
        require(value["checker_source_sha256"] == artifacts[checker_key]["sha256"], "checker source pin differs")
    require(observation["retained_file_count"] == 16 and observation["response_rows_verified"] == 2560
            and observation["source_record_digests_independently_rebuilt"] == 2560
            and observation["native_binary_independently_hashed"]["sha256"] == binary["sha256"],
            "independent parity scope/inventory differs")
    require(cost_observation["native_binary_sha256"] == binary["sha256"]
            and cost_observation["source_commit"] == spec["source_sha"]
            and cost_observation["source_tree"] == spec["source_tree"]
            and cost_observation["parity_observation_sha256"] == artifacts["native_observation"]["sha256"],
            "independent cost source or parity binding differs")
    require(set(observation["retained_files_actual_digest"]) == expected_files, "independent observed inventory differs")
    for name, entry in observation["retained_files_actual_digest"].items():
        require(entry["observed_sha256"] == report["retained_file_sha256"][name], "observed file digest differs")
    costs = {}
    for mode in MODES:
        cost = json.loads(payloads[f"native-results/{mode}-cost.json"])
        require(cost["source_identity"] == identity and cost["native_binary_sha256"] == binary["sha256"],
                "cost source/binary differs")
        samples = cost["latency"]["raw_nanoseconds"]
        require(cost["warmup_rows"] == 20 and cost["measured_rows"] == len(samples) == 1000
                and all(type(x) is int and x > 0 for x in samples), "cost sample inventory differs")
        ordered = sorted(samples)
        recomputed = {f"p{p}_ms": ordered[math.ceil(len(samples) * p / 100) - 1] / 1e6 for p in (50, 95, 99)}
        require(all(cost["latency"][key] == value for key, value in recomputed.items()), "cost quantile differs")
        require(cost["wait4_peak_may_include_pre_exec_parent_memory"] is True
                and cost["wait4_peak_is_native_resident_memory"] is False
                and cost["target_device_qualified"] is False and cost["energy_joules"] is None,
                "cost memory/device/energy scope differs")
        costs[mode] = cost_observation["costs"][mode]
    logs = {}
    required_logs = {"stem_tests", "release_build"}
    require(required_logs <= set(spec["logs"]) <= required_logs | {"native_replay"},
            "original test/build logs and optional replay log required")
    for key, value in spec["logs"].items():
        raw = read_pinned(value["path"], value["sha256"], MAX_LOG)
        compressed = gzip.compress(raw, compresslevel=9, mtime=0)
        require(gzip.decompress(compressed) == raw, "raw log gzip round-trip differs")
        filename = f"logs/{key}.raw.log.gz"
        retain(filename, compressed, {"kind": "lossless_gzip", "path": value["path"], "raw_sha256": sha(raw)})
        logs[key] = {"file": filename, "gzip_sha256": sha(compressed), "gzip_bytes": len(compressed),
            "raw_sha256": sha(raw), "raw_bytes": len(raw), "captured_for_source_sha": value["source_sha"],
            "source_matches_final_report": value["source_sha"] == spec["source_sha"],
            "capture_scope": value["capture_scope"], "capture_association": "provided by execution owner; original log preserved"}
        if value.get("execution_command_reported") is not None:
            logs[key]["execution_command_reported"] = value["execution_command_reported"]
        text = raw.decode("utf-8", errors="replace")
        if key == "stem_tests":
            matches = re.findall(r"^Ran (\d+) tests? in ([0-9.]+)s$", text, re.MULTILINE)
            require(len(matches) == 1 and int(matches[0][0]) == 273
                    and re.search(r"^OK$", text, re.MULTILINE) is not None, "original 273-test log summary differs")
            logs[key].update({"observed_tests": 273, "observed_seconds": float(matches[0][1]), "observed_result": "OK"})
        elif key == "release_build":
            require(value["source_sha"] == spec["source_sha"], "release build log source must match final report")
            require("Finished `release` profile [optimized]" in text, "optimized release build completion missing")
        else:
            require(value["source_sha"] == spec["source_sha"] and json.loads(raw) == report,
                    "replay log must reproduce the final report JSON and source")
            logs[key]["parsed_report_equals_preserved_report"] = True
    archive_relative = "qa/stem-bakeoff/evidence/20261022-real-multimodal/archive-manifest.json"
    read_pinned(repository / archive_relative, report["archive_manifest_sha256"])
    publication = None
    if spec.get("publication") is not None:
        item = spec["publication"]
        raw = read_pinned(item["commit_object_path"], item["commit_object_sha256"])
        remote = json.loads(raw)
        require(remote["sha"] == item["remote_source_sha"] and remote["tree"]["sha"] == spec["source_tree"],
                "remote publication commit does not share the tested source tree")
        require(remote["url"] == "https://api.github.com/repos/TrillionniumFoundation/hepta-private-ci/git/commits/" + remote["sha"],
                "publication commit is not from the intended repository")
        retain("publication/github-source-commit.json", raw,
               {"kind": "unchanged_github_commit_object", "path": item["commit_object_path"]})
        publication = {"tested_local_source_sha": spec["source_sha"], "remote_source_sha": remote["sha"],
            "equal_tree_sha": remote["tree"]["sha"], "api_url": remote["url"],
            "commit_object_file": "publication/github-source-commit.json", "commit_object_sha256": sha(raw),
            "report_commit_bytes_rewritten": False}
    script_raw = Path(__file__).read_bytes()
    retain("checks/package_evidence.py", script_raw, {"kind": "packager_source", "path": str(Path(__file__).resolve())})
    retain("package-inputs.json", spec_raw, {"kind": "unchanged_package_spec", "path": str(Path(spec_path).resolve())})
    validation = {"schema": "hepta.native-task-evidence-validation.v1", "status": "VERIFIED_RESEARCH_EVIDENCE",
        "native_report_sha256": spec["expected_report_sha256"], "release_binary_sha256": binary["sha256"],
        "tested_source_sha": spec["source_sha"], "tested_tree_sha": spec["source_tree"],
        "publication_source_mapping": publication, "package_inputs_sha256": sha(spec_raw),
        "packager_source_sha256": sha(script_raw), "logs": logs,
        "independent_observations": {key: {"file": names[key], "sha256": artifacts[key]["sha256"]}
                                     for key in ("native_observation", "cost_observation")},
        "upstream_reconstruction_dependency": {"repository_path": archive_relative,
            "manifest_sha256": report["archive_manifest_sha256"], "original_report_sha256": report["original_report_sha256"]},
        "original_report_and_10_response_jsonl_bytes_unchanged": True,
        "native_report_indexed_artifacts": 16, "native_response_rows": 2560,
        "source_record_digests_independently_rebuilt": 2560,
        "present_class_and_acceptance_matches_original_ledger": observation["present_classes_and_acceptance_match_original_ledgers"],
        "max_logit_error": observation["max_logit_error_vs_original_ledgers"],
        "max_probability_error": observation["max_probability_error_vs_original_ledgers"],
        "fixed_absolute_tolerance": observation["fixed_absolute_tolerance"],
        "head_contracts": observation["native_head_contracts"], "cases": observation["cases"], "costs": costs,
        "scope": "one resident native task Head; cached real features; zero state; JSONL round trip on a shared Linux host",
        "benchmark_rerun_during_packaging": False, "new_training_or_calibration": False,
        "new_independent_quality_trial": False, "native_encoder_executed": False,
        "full_policy_learning_qualified": False, "target_device_qualified": False,
        "energy_joules": None, "architecture_cost_ranking_established": False,
        "compiler_attestation_independently_verified": False,
        "mode": "SHADOW_ONLY", "authority": "DENY_ALL", "production_activation_allowed": False,
        "task_admission_allowed": False, "action_execution_allowed": False,
        "preserved_receipts_contain_original_absolute_paths": True}
    retain("validation.json", encode(validation), {"kind": "generated_validation"})
    cost_lines = []
    for mode, cost in costs.items():
        q = cost["recomputed_latency"]
        cost_lines.append(f"| {mode} | {q['p50_ms']:.6f} | {q['p95_ms']:.6f} | {q['p99_ms']:.6f} | "
                          f"{cost['native_rss_after_measurement']['rss_bytes']:,} | "
                          f"{cost['wait4_lifetime_peak_not_native_resident_bytes']:,} |")
    mapped = ("The published source commit is `" + publication["remote_source_sha"] + "`; its Git tree equals the tested local tree."
              if publication else "No remote publication mapping was supplied for this staged package.")
    replay_log_note = ("The final replay's raw stdout is retained losslessly in `logs/native_replay.raw.log.gz`; "
                       "its parsed JSON equals the preserved final report.\n" if "native_replay" in logs else "")
    readme = f"""# P40 native task Head evidence

This package retains the actual Rust task-Head replay and descriptive cost
observations from a shared Linux host. It is **head-only research evidence**.
It does not qualify a target device, measure energy, train a policy, or constitute
a new independent multimodal quality trial. All task/action admission remains
false, with `SHADOW_ONLY` / `DENY_ALL` posture.

## Exact bindings

- Runtime report: `native-results/report.json`, SHA256 `{spec['expected_report_sha256']}`.
- Tested local source: `{spec['source_sha']}`.
- Tested source tree: `{spec['source_tree']}`.
- Actual release binary SHA256: `{binary['sha256']}`. The compiled binary itself is not included.
- Original experiment report: `{report['original_report_sha256']}`.
- Original reconstruction archive manifest: `{report['archive_manifest_sha256']}`.

{mapped} The original runtime report retains its local source SHA verbatim;
publication mappings do not rewrite experimental evidence. Source and binary
hashes provide identity bindings, not independent compiler attestation.

## Preserved contents

`native-results/` contains the original report and all 16 files indexed by that
report: two bounded task artifacts, ten per-row response JSONL files and two
cost files. **The report and every JSONL file are copied byte for byte.**
`checks/` retains two independent checker scripts and their original observation
receipts, plus the packager. Historical absolute paths inside receipts are kept
unchanged. `validation.json` gives the package-relative locations and scope.
`manifest.json` lists SHA256/size/origin for every payload; `SHA256SUMS` also
indexes the manifest itself. Those two index files are not self-indexed.

## Numerical and presence results

The independent check verifies 2,560 rows and reconstructs each source-record
digest from the original cohort and feature-bank provenance. Present-row class
and confidence decisions match the original NPZ ledgers exactly. Temperature
remains 0.25, confidence threshold 0.7 and the fixed absolute tolerance 2e-5.
Maximum logit difference is {validation['max_logit_error']:.12g}; maximum probability
difference is {validation['max_probability_error']:.12g}.

For each Head, the 256 missing-text and 256 missing-image rows return null
predictions. Mixed-presence input scores 86 rows and rejects 170. Shuffled-image
rows remain present and are evaluated; this guard does not detect an incorrect
pair. The 14 invalid-CLI rejections are retained observations of the original
execution, not probes reexecuted by the independent checker or packager.

## Observed cost

Each Head used one persistent process, 20 warmup requests and 1,000 measured
requests cycling through 256 fixed paired inputs. Nearest-rank quantiles are
independently recomputed from the preserved integer-nanosecond samples.

| Head | p50 ms | p95 ms | p99 ms | Final native RSS B | wait4 lifetime peak B |
|---|---:|---:|---:|---:|---:|
{chr(10).join(cost_lines)}

Latency includes pipe IO, native JSON decoding/inference/encoding and Python
response decoding. Encoder execution, request construction, startup and
validation are excluded. RSS is recorded through the source-bound
PPid/NSpid/executable/starttime-checked proc path; closed processes cannot be
reobserved retrospectively. **The wait4 lifetime peaks may include inherited
pre-exec parent memory and are not native resident-memory estimates.**
These sequential shared-host observations do not establish an intrinsic cost
ranking between gated and linear architectures or target-device performance.

## Original logs and source scope

`logs/stem_tests.raw.log.gz` losslessly preserves the original log reporting
273 tests passed in {logs['stem_tests']['observed_seconds']:.3f}s, captured for
`{logs['stem_tests']['captured_for_source_sha']}`. Its source matches the runtime
report: **{str(logs['stem_tests']['source_matches_final_report']).lower()}**.
Scope: {logs['stem_tests']['capture_scope']}

`logs/release_build.raw.log.gz` losslessly preserves the optimized release
build log captured for `{logs['release_build']['captured_for_source_sha']}`.
Raw and compressed byte hashes are recorded separately in `validation.json`.
The packager does not transform an earlier test run into an exact-head rerun.
{replay_log_note}

## Reproduction boundary

Reconstruction uses the existing repository archive at
`qa/stem-bakeoff/evidence/20261022-real-multimodal/`, whose manifest pin is above.
The cached bank and trained Heads are reused; the native replay does not download
or run a foundation Encoder. At the pinned source, build the
`codex-hepta-neuron` example `native_task_head` in release mode, then run
`qa/stem-bakeoff/replay_native_task_head_v1.py` with `--archive-directory`, a new
`--output`, the compiled `--binary`, and `--measure-cost`. New runtime cost samples
will differ from these retained observations. The independent scripts expose
their complete command-line interfaces with `--help`.

Original request JSONL streams were ephemeral and are reconstructed by the
replay; their hashes and each response's request digest are retained. The
independent observation explicitly distinguishes source-digest reconstruction
from independent reconstruction of those deleted complete request streams.
"""
    retain("README.md", readme.encode(), {"kind": "generated_readme"})
    manifest = {"schema": "hepta.native-task-evidence-package.v1",
        "source_report_sha256": spec["expected_report_sha256"], "source_tree": spec["source_tree"],
        "payloads": {name: {"sha256": sha(raw), "bytes": len(raw), "origin": origins[name]}
                     for name, raw in sorted(payloads.items())},
        "index_files_excluded_from_payloads": ["manifest.json", "SHA256SUMS"],
        "repository_destination_hint": "qa/stem-bakeoff/evidence/20261022-native-task-head",
        "repository_modified_by_packager": False}
    manifest_raw = encode(manifest)
    sums = "".join(f"{sha(raw)}  {name}\n" for name, raw in sorted({**payloads, "manifest.json": manifest_raw}.items())).encode()
    require(len(manifest_raw) <= MAX_BLOB and len(sums) <= MAX_BLOB, "index blob budget")
    destination.mkdir(mode=0o700)
    for name, raw in {**payloads, "manifest.json": manifest_raw, "SHA256SUMS": sums}.items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(raw)
        require(path.read_bytes() == raw, "staged bytes differ")
    for name in ["report.json", *expected_files]:
        require((destination / "native-results" / name).read_bytes() == (source / name).read_bytes(),
                "original native evidence changed during staging")
    require(sha(Path(__file__).read_bytes()) == sha(script_raw), "packager source changed during staging")
    return {"status": "STAGED_FOR_REVIEW", "directory": str(destination),
        "files_including_indexes": len(payloads) + 2, "bytes_including_indexes": sum(map(len, payloads.values())) + len(manifest_raw) + len(sums),
        "manifest_sha256": sha(manifest_raw), "validation_sha256": sha(payloads["validation.json"]),
        "readme_sha256": sha(payloads["README.md"]), "original_native_files_byte_identical": 17,
        "source_report_sha256": spec["expected_report_sha256"], "repository_modified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True, help="reviewable paths and expected identities JSON")
    parser.add_argument("--output", required=True, help="new staging directory under /tmp")
    args = parser.parse_args()
    print(json.dumps(package(args.spec, args.output), sort_keys=True))


if __name__ == "__main__":
    main()
