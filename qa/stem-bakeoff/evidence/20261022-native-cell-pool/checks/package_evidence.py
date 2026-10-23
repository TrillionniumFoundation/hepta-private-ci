"""Copy frozen P41 observations byte-for-byte; never execute a benchmark."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

SOURCE = "f8855a7ac07af47b618199a3a9ccb87ff9552a5c"
TREE = "231ed14ea73a71c6d2ac3fe353b1779419154f53"
REPORT = "f4ed9cce8f33cb26764933cbc2b950239c9b7e2f8360410b051467a50ca8abe0"
P40_REPORT = "22e4560ca4ff2b1c604267c92aed71bbf1417e612018c6760930633ca52395e6"
ARCHIVE = "2a853d6c975b30d98a8c79348f01bb3f5b26f36793f2986826a5deed3ea4454e"
RUN = Path("/tmp/hepta-p41-native-pools-f8855a7")
REPO = Path("/tmp/hepta-p41-pool")
INDEX = Path("/tmp/hepta-p41-evidence-index.json")
OMIT = {"requests.jsonl", "native_task_head_pool.bin"}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"


def read(path, pin=None):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError(f"expected bounded regular original: {path}")
    raw = path.read_bytes()
    if pin is not None and sha(raw) != pin:
        raise ValueError(f"original digest differs: {path}")
    return raw


def git(*args):
    return subprocess.check_output(["git", "--no-optional-locks", "-C", str(REPO), *args])


def package(target):
    target = Path(target).absolute()
    if target.exists() or not target.parent.is_dir() or target.is_relative_to(REPO):
        raise ValueError("new external package directory required")
    index_raw = read(INDEX)
    index = json.loads(index_raw)
    originals = {}
    for name, expected in index["files"].items():
        raw = read(name, expected["sha256"])
        if len(raw) != expected["bytes"]:
            raise ValueError("original length differs: " + name)
        originals[name] = raw
    report = json.loads(read(RUN / "report.json", REPORT))
    plan_raw = read(RUN / "plan.json", report["plan_sha256"])
    plan = json.loads(plan_raw)
    identity = report["source_identity"]
    if identity != plan["source_identity"] or identity["git_head_sha"] != SOURCE:
        raise ValueError("source identity differs")
    if identity["git_tree_sha"] != TREE or git("rev-parse", SOURCE + "^{tree}").decode().strip() != TREE:
        raise ValueError("source tree differs")
    expected_names = [f"{mode}-{n}" for mode in ("gated", "linear") for n in (1, 32, 256, 4096)]
    if report["execution_order"] != expected_names or set(report["experiments"]) != set(expected_names):
        raise ValueError("eight-process inventory differs")
    dispatch = fanout = 0
    for name in expected_names:
        raw = read(RUN / (name + ".json"), report["retained_file_sha256"][name + ".json"])
        child = json.loads(raw)
        if len(child["dispatch_nanoseconds"]) != 4096 or len(child["fanout_nanoseconds"]) != 16:
            raise ValueError("raw sample count differs")
        dispatch += len(child["dispatch_nanoseconds"])
        fanout += len(child["fanout_nanoseconds"])

    target.mkdir(mode=0o700)
    entries = {}

    def put(name, raw, origin, kind):
        path = target / name
        if path.exists() or not path.is_relative_to(target):
            raise ValueError("duplicate package path")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        if read(path) != raw:
            raise ValueError("package copy differs")
        entries[name] = {"bytes": len(raw), "sha256": sha(raw), "original_source": origin, "kind": kind}

    omitted = []
    for name, raw in originals.items():
        path = Path(name)
        if path.parent == RUN and path.name in OMIT:
            omitted.append({"original_path": name, "logical_path": "native-results/" + path.name,
                            "bytes": len(raw), "sha256": sha(raw), "included": False,
                            "reason": "deliberately omitted large reconstructible input or executable"})
            continue
        if path.is_relative_to(RUN):
            dest = "native-results/" + path.relative_to(RUN).as_posix()
        elif path.suffix == ".log":
            dest = "logs/" + path.name
        elif path.suffix == ".py":
            dest = "checks/" + path.name
        elif path.name == "receipt.json":
            dest = "checks/native-fixture-probe/receipt.json"
        elif path.suffix == ".md":
            dest = "original-notes/" + path.name
        else:
            dest = "checks/" + path.name
        put(dest, raw, name, "unchanged-original")
    put("checks/original-evidence-index.json", index_raw, str(INDEX), "unchanged-original-index")
    for path in sorted(Path("/tmp").glob("hepta-p41-*.log")):
        dest = "logs/" + path.name
        if dest not in entries:
            put(dest, read(path), str(path), "unchanged-historical-log")
    probe = Path("/tmp/hepta-p41-driver-probe")
    for path in sorted(probe.iterdir()):
        dest = "checks/native-fixture-probe/" + path.name
        if dest not in entries:
            put(dest, read(path), str(path), "unchanged-synthetic-execution-fixture-not-quality")

    source_hashes = {}
    for name, expected in identity["source_file_sha256"].items():
        raw = git("show", SOURCE + ":" + name)
        if sha(raw) != expected:
            raise ValueError("source blob differs: " + name)
        put("source-snapshot/" + name, raw, SOURCE + ":" + name, "exact-git-source-blob")
        source_hashes[name] = sha(raw)
    for name in ("qa/stem-bakeoff/test_native_task_head_pool.py", "codex-rs/rust-toolchain.toml"):
        raw = git("show", SOURCE + ":" + name)
        put("source-snapshot/" + name, raw, SOURCE + ":" + name, "exact-git-source-blob")
        source_hashes[name] = sha(raw)

    p40 = REPO / "qa/stem-bakeoff/evidence/20261022-native-task-head/native-results"
    p40_raw = read(p40 / "report.json", P40_REPORT)
    p40_report = json.loads(p40_raw)
    put("references/p40/report.json", p40_raw, str(p40 / "report.json"), "unchanged-p40-reference")
    for mode in ("gated", "linear"):
        name = mode + "-paired.jsonl"
        put("references/p40/" + name, read(p40 / name, p40_report["retained_file_sha256"][name]),
            str(p40 / name), "unchanged-p40-reference")
    archive_path = REPO / "qa/stem-bakeoff/evidence/20261022-real-multimodal/archive-manifest.json"
    archive_raw = read(archive_path, ARCHIVE)
    put("references/research-archive-manifest.json", archive_raw, str(archive_path), "unchanged-input-reference")

    rebuild = r'''# Use a fresh checkout with the exact recorded Git tree. The original local
# commit may require the later separately published same-tree commit mapping.
cd /path/to/exact-p41-checkout
test "$(git rev-parse HEAD^{tree})" = 231ed14ea73a71c6d2ac3fe353b1779419154f53
P41_PYTHON=/path/to/p40-compatible-python
P41_INPUT_REBUILD=/tmp/p41-rebuilt-inputs
"$P41_PYTHON" - "$PWD" "$P41_INPUT_REBUILD" <<'PY'
import hashlib, pathlib, shutil, sys
repo, output = map(pathlib.Path, sys.argv[1:])
sys.path.insert(0, str(repo / "qa/stem-bakeoff"))
from multimodal_evidence import restore_evidence
from native_task_head_pool import prepare_inputs
output.mkdir(mode=0o700)
p40 = output / "p40"; p40.mkdir()
shutil.copytree(repo / "qa/stem-bakeoff/evidence/20261022-native-task-head/native-results",
                p40 / "native-results")
restore_evidence(repo / "qa/stem-bakeoff/evidence/20261022-real-multimodal",
    expected_manifest_sha256="2a853d6c975b30d98a8c79348f01bb3f5b26f36793f2986826a5deed3ea4454e",
    output=p40 / "restored")
prepared = output / "prepared"; prepared.mkdir()
prepare_inputs(p40, "22e4560ca4ff2b1c604267c92aed71bbf1417e612018c6760930633ca52395e6", prepared)
raw = (prepared / "requests.jsonl").read_bytes()
assert len(raw) == 16988720
assert hashlib.sha256(raw).hexdigest() == "3bb13eaae37d0d72b245ce65aa28c81b057a542fe555d367a0f7758b392cd214"
print("exact original input stream reconstructed; no prediction or training executed")
PY
# Release build from the same source; this does not execute the resource trial.
# Compiler, linker, paths and environment may change the executable bytes.
cd codex-rs
CARGO_TARGET_DIR=/tmp/p41-rebuilt-target CARGO_INCREMENTAL=0 CARGO_PROFILE_DEV_DEBUG=0 CARGO_PROFILE_TEST_DEBUG=0 CARGO_PROFILE_RELEASE_DEBUG=0 CARGO_BUILD_JOBS=2 cargo build --locked --release -p codex-hepta-neuron --example native_task_head_pool --offline
sha256sum /tmp/p41-rebuilt-target/release/examples/native_task_head_pool
# Original: 2673320 bytes, SHA256 42c69fcec3a2b5332893e6a417710df38fbc6cab3ca51ab1afe195db2fe4fc31.
# A different rebuilt digest identifies a NEW executable, not the retained original.
'''
    put("RECONSTRUCT.sh", rebuild.encode(), "generated packaging documentation", "commands-not-executed-during-packaging")
    refs = {"schema": "hepta.p41-package-input-references.v1", "omitted": omitted,
        "source_commit": SOURCE, "source_tree": TREE, "source_file_sha256": source_hashes,
        "cargo_lock_sha256": sha(git("show", SOURCE + ":codex-rs/Cargo.lock")),
        "p40_repository_path": "qa/stem-bakeoff/evidence/20261022-native-task-head/native-results",
        "p40_report_sha256": P40_REPORT, "p40_retained_file_sha256": p40_report["retained_file_sha256"],
        "research_archive_repository_path": "qa/stem-bakeoff/evidence/20261022-real-multimodal",
        "research_archive_manifest_sha256": ARCHIVE,
        "request_reconstruction": "RECONSTRUCT.sh, cached features only; no Encoder or training",
        "binary_reconstruction": "RECONSTRUCT.sh, same-source release build; exact binary identity must be checked separately",
        "remote_source_mapping": None, "mapping_note": "append a separate publication record; do not rewrite original report"}
    put("input-references.json", canonical(refs), "generated from pinned originals", "package-metadata")
    notes = f'''# P41 frozen native private-Head pool evidence

This package preserves the completed eight-process P41 run. The original report,
plan, all eight raw JSON outputs, eight stderr files, two Head artifacts,
crosscheck, validation, scripts and logs are copied without byte changes.
The original narratives and absolute `/tmp` paths remain as historical records;
`manifest.json` maps those paths to this portable package. Raw logs distinguish
initial/environment-blocked attempts from the final successful scoped checks.

- Original source: `{SOURCE}`; tree `{TREE}`.
- Original report SHA256: `{REPORT}`.
- Raw observations retained: **{dispatch} dispatch samples + {fanout} full-fanout samples**.
- Each mode used 1, 32, 256 and 4096 private owned Head allocations, exercised
  before timing. These replicate **two fixed trained artifacts**, not thousands
  of independently learned tasks.
- Native timers exclude JSON/pipe IO and reference validation. Fanout has only
  16 samples per process; its median and maximum are descriptive, not p99.
- All samples remain, including the variable gated-4096 run. The fixed serial
  order on a shared host cannot establish an intrinsic architecture cost ranking.
- Self `/proc` RSS/RssAnon includes inputs, source buffers, private weights,
  allocator and runtime. This is not physical-page attestation or Encoder memory.
- **Head-only; non-target-device; no energy measurement; no new independent
  quality trial; no training/calibration changes; no policy or production authority.**

The original `requests.jsonl` (16,988,720 bytes) and executable (2,673,320 bytes)
are deliberately omitted. Their complete original sizes and SHA256 digests are
in `input-references.json`; `RECONSTRUCT.sh` gives exact-source input and build
commands. The original bytes were rehashed during packaging. Cached inputs can
be reconstructed from the existing pinned P40/research evidence without an
Encoder. A rebuilt executable must be identified by its actual hash; source
identity is not compiler attestation or a promise of a byte-identical build.
Original measurement reports are never rewritten to describe a later rebuild.

## Integrity and publication

Run `sha256sum -c SHA256SUMS` inside this directory. The checksum list includes
`manifest.json`; the manifest indexes every payload file, excluding itself and
`SHA256SUMS` to avoid circular digests. A final external package receipt pins
both index files. The two omissions are explicit and do not remove any timing
sample. `references/p40/` retains the paired reference ledgers used by the
original crosscheck; other P40 dependencies retain their repository paths and
hashes rather than being silently treated as package contents.

The remote same-tree commit mapping may be appended as separate publication
metadata later. Keep source SHA/tree inside the original report and plan intact.
No benchmark, model inference, encoding or training was rerun while packaging.
The new shell reproduction recipe is documentation, not an additionally executed
test. Original local tests and native checks keep their own source/time scope;
this package makes no claim that remote CI has completed.
'''
    put("README.md", notes.encode(), "generated packaging scope and instructions", "package-documentation")
    put("checks/package_evidence.py", Path(__file__).read_bytes(), str(Path(__file__).absolute()), "packaging-script")
    manifest = {"schema": "hepta.p41-evidence-package.v1", "source_commit": SOURCE, "source_tree": TREE,
        "report_sha256": REPORT, "original_measurements_modified": False, "benchmark_rerun": False,
        "experiments": 8, "dispatch_samples": dispatch, "fanout_samples": fanout,
        "payload_file_count": len(entries), "payload_bytes": sum(e["bytes"] for e in entries.values()),
        "files": entries, "omitted": omitted,
        "index_exclusions": ["manifest.json", "SHA256SUMS"]}
    manifest_raw = canonical(manifest)
    (target / "manifest.json").write_bytes(manifest_raw)
    sums = {name: e["sha256"] for name, e in entries.items()}
    sums["manifest.json"] = sha(manifest_raw)
    checksum_raw = "".join(f"{sums[name]}  {name}\n" for name in sorted(sums)).encode()
    (target / "SHA256SUMS").write_bytes(checksum_raw)
    if set(p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file()) != set(sums) | {"SHA256SUMS"}:
        raise ValueError("package inventory differs")
    for name, expected in sums.items():
        read(target / name, expected)
    # Recheck the pinned originals after copying; no index or source is mutated.
    for name, expected in index["files"].items():
        read(name, expected["sha256"])
    return {"schema": "hepta.p41-package-copy-receipt.v1", "status": "PASS_BYTE_PRESERVING_PACKAGE",
        "package": str(target), "files": len(sums) + 1,
        "bytes": sum(p.stat().st_size for p in target.rglob("*") if p.is_file()),
        "manifest_sha256": sha(manifest_raw), "sha256sums_sha256": sha(checksum_raw),
        "report_sha256": REPORT, "source_commit": SOURCE, "source_tree": TREE,
        "original_index_entries_rehashed": len(index["files"]), "omitted_files": len(omitted),
        "dispatch_samples": dispatch, "fanout_samples": fanout, "benchmark_rerun": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--receipt", required=True)
    args = parser.parse_args()
    receipt_path = Path(args.receipt)
    if receipt_path.exists():
        raise ValueError("new receipt path required")
    receipt = package(args.output)
    receipt_path.write_bytes(canonical(receipt))
    print(json.dumps(receipt, sort_keys=True))
