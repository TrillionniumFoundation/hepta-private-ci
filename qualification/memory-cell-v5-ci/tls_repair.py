#!/usr/bin/env python3
"""Produce a bounded, reviewable TLS lock update without committing it."""

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tarfile
import tempfile
import time
import tomllib


BASE = "90816a3d20bbba0d9d3acca451d30f328e5df7c5"
BRANCH = "refs/heads/research/memory-cell-v5-tls-20261027"
DATABASE = "3279c99911354c400e1d41e47c7d60e39258b147"
DATABASE_TREE = "5393c02acc63bc5cea86e641913509b67f4daeef"
DENY_URL = (
    "https://github.com/EmbarkStudios/cargo-deny/releases/download/0.19.0/"
    "cargo-deny-0.19.0-x86_64-unknown-linux-musl.tar.gz"
)
DENY_SHA256 = "0e8c2aa59128612c90d9e09c02204e912f29a5b8d9a64671b94608cbe09e064f"
TARGETS = {
    "rustls-webpki": ("0.103.15", "0.103.16", "4443b1b6d39d7c663139942cc4558262562d2c84123bb6282ef177009ca8b281"),
    "webpki-roots": ("1.0.9", "1.0.10", "1c1c8e20c8a38fc7d65abfe74eb7280e4aa667e8eec8bc84996d2874810748d9"),
    "webpki-root-certs": ("1.0.5", "1.0.10", "58ec80e73fd8baf57bf0d9615554c75348bda990d6d5bbeab964dd068319fecb"),
    "rustls": ("0.23.45", "0.23.46", "48e13bd8c0e9365c43cfa5c9e8f9ad49d3c8444926c9aac819e0e4dc503c8fdf"),
}
REMOVED_IDS = {
    "RUSTSEC-2026-0346", "RUSTSEC-2026-0347", "RUSTSEC-2026-0348",
    "RUSTSEC-2026-0349", "RUSTSEC-2026-0381", "RUSTSEC-2026-0382", "RUSTSEC-2026-0383",
}
LOCKS = ("codex-rs/Cargo.lock", "MODULE.bazel.lock")
PROTECTED = (
    "codex-rs/Cargo.toml", "codex-rs/deny.toml", "codex-rs/rust-toolchain.toml",
    "MODULE.bazel", ".bazelversion", ".github/workflows/cargo-deny.yml",
    "patches/rules_rs_build_script_deps_annotation.patch",
    "patches/zstd-sys_windows_msvc_include_dirs.patch",
    "qualification/memory-cell-v5-ci/cargo-deny-evidence/DIAGNOSIS.json",
)
CONSUMERS = ("codex-utils-rustls-provider", "codex-http-client", "codex-websocket-client")


def identity(raw):
    return {
        "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
        "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest(),
    }


def packages(lock):
    return {(p["name"], p["version"], p.get("source")): p for p in lock["package"]}


def package_by_name(lock, name):
    found = [p for p in lock["package"] if p["name"] == name]
    if len(found) != 1:
        raise ValueError(f"Expected one locked {name}, found {len(found)}")
    return found[0]


def compare_locks(before, after):
    """Require the original graph, with only declared versions/checksums changed."""
    expected = copy.deepcopy(before)
    for name, (old, target, checksum) in TARGETS.items():
        current = package_by_name(after, name)
        if current["version"] not in {old, target}:
            raise ValueError(f"Unexpected resolved version for {name}: {current['version']}")
        if current["version"] == target:
            wanted = package_by_name(expected, name)
            wanted.update(version=target, checksum=checksum)
            for row in expected["package"]:
                if "dependencies" in row:
                    row["dependencies"] = [
                        re.sub(rf"^{re.escape(name)} {re.escape(old)}(?= |$)", f"{name} {target}", dep)
                        for dep in row["dependencies"]
                    ]
    old_rows, new_rows = packages(before), packages(after)
    changed_names = sorted({key[0] for key in old_rows.keys() ^ new_rows.keys()})
    expected_other = {k: v for k, v in expected.items() if k != "package"}
    actual_other = {k: v for k, v in after.items() if k != "package"}
    return {
        "removed": [old_rows[k] for k in sorted(old_rows.keys() - new_rows.keys(), key=repr)],
        "added": [new_rows[k] for k in sorted(new_rows.keys() - old_rows.keys(), key=repr)],
        "changed_same_identity": [
            {"before": old_rows[k], "after": new_rows[k]}
            for k in sorted(old_rows.keys() & new_rows.keys(), key=repr) if old_rows[k] != new_rows[k]
        ],
        "package_names_with_version_or_source_changes": changed_names,
        "only_declared_graph_change": packages(expected) == new_rows and expected_other == actual_other,
        "all_four_targets_exact": all(package_by_name(after, n)["version"] == t[1] for n, t in TARGETS.items()),
    }


def summarize_advisories(messages):
    records, other_errors = [], []
    for message in messages:
        if not isinstance(message, dict) or message.get("type") != "diagnostic":
            continue
        fields = message.get("fields", {})
        if fields.get("severity") != "error":
            continue
        advisory = fields.get("advisory", {})
        identifier, package = advisory.get("id"), advisory.get("package")
        if not isinstance(identifier, str) or not re.fullmatch(r"RUSTSEC-\d{4}-\d{4}", identifier):
            other_errors.append({key: fields.get(key) for key in ("code", "message")})
            continue
        versions = {
            graph["Krate"]["version"] for graph in fields.get("graphs", [])
            if graph.get("Krate", {}).get("name") == package
        }
        if not versions:
            for label in fields.get("labels", []):
                match = re.match(rf"^{re.escape(package)}\s+(\S+)(?:\s|$)", label.get("span", ""))
                if match:
                    versions.add(match[1])
        records.append({"id": identifier, "category": fields.get("code"), "package": package,
                        "versions": sorted(versions), "aliases": advisory.get("aliases", [])})
    return {"error_advisories": records, "other_error_diagnostics": other_errors,
            "error_advisory_count": len(records), "unique_error_advisory_ids": sorted({r["id"] for r in records})}


def compare_advisories(before, after, expected):
    def observed(data):
        return {(r["id"], r["category"], r["package"], tuple(r["versions"])) for r in data["error_advisories"]}
    original = {(r["advisory_id"], r["category"], r["installed"]["name"], (r["installed"]["version"],)) for r in expected}
    wanted = {r for r in original if r[0] not in REMOVED_IDS}
    before_ids, after_ids = set(before["unique_error_advisory_ids"]), set(after["unique_error_advisory_ids"])
    checks = {
        "baseline_22_records_exact": len(original) == 22 and before["error_advisory_count"] == 22 and observed(before) == original,
        "remaining_15_records_exact": len(wanted) == 15 and after["error_advisory_count"] == 15 and observed(after) == wanted,
        "exact_seven_target_ids_removed": before_ids - after_ids == REMOVED_IDS and not after_ids - before_ids,
        "no_other_error_diagnostics": not before["other_error_diagnostics"] and not after["other_error_diagnostics"],
        "actual_advisory_failure_preserved": before["exit_code"] == after["exit_code"] == 1,
    }
    return {"checks": checks, "passed": all(checks.values()), "removed_ids": sorted(before_ids - after_ids),
            "added_ids": sorted(after_ids - before_ids), "remaining_ids": sorted(after_ids)}


class Experiment:
    def __init__(self, output):
        self.root = Path.cwd().resolve()
        self.output = output.resolve()
        if self.output == self.root or self.root in self.output.parents:
            raise ValueError("Output must be outside the checkout")
        self.output.mkdir(parents=True, exist_ok=False)
        self.deadline = time.monotonic() + 2400
        self.temporary = Path(tempfile.mkdtemp(prefix="memory-v5-tls-", dir=os.environ["RUNNER_TEMP"]))
        self.env = dict(os.environ, CARGO_TARGET_DIR=str(self.temporary / "target"), RUSTUP_TOOLCHAIN="1.95.0")
        self.report = {
            "schema": "hepta.memory.v5.tls-repair-experiment.v1", "source_commit": os.environ.get("GITHUB_SHA"),
            "expected_base": BASE, "branch": os.environ.get("GITHUB_REF"), "targets": TARGETS,
            "advisory_database_commit": DATABASE, "commands": [], "complete": False,
            "candidate_checks_passed": False, "advisory_gate_passed": False,
            "full_cargo_deny_gate_executed": False, "unit_tests_executed": False,
            "study_training_or_evaluation_executed": False, "commits_created": False,
            "scope": "Four TLS lock updates, native client library compilation and advisory-only comparison.",
            "coverage_limit": "No TLS handshake; native roots consumers may not compile either webpki root-store package.",
        }
        self.before = {}
        self.save()

    def save(self):
        (self.output / "SUMMARY.json").write_text(json.dumps(self.report, indent=2, sort_keys=True) + "\n")

    def run(self, label, command, timeout=60, *, cwd=None, allow_failure=False):
        seconds = min(timeout, self.deadline - time.monotonic())
        if seconds <= 0:
            raise TimeoutError("Experiment deadline reached before " + label)
        index = len(self.report["commands"]) + 1
        directory = self.output / f"command-{index:02d}-{label}"
        directory.mkdir()
        started = time.monotonic()
        timed_out = False
        with (directory / "stdout.txt").open("wb") as stdout, (directory / "stderr.txt").open("wb") as stderr:
            try:
                process = subprocess.Popen(command, cwd=cwd or self.root, env=self.env, stdout=stdout, stderr=stderr, start_new_session=True)
                try:
                    status = process.wait(timeout=seconds)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=10)
                    status = 124
            except OSError as error:
                stderr.write(str(error).encode())
                status = 127
        record = {"label": label, "argv": command, "cwd": str(cwd or self.root), "exit_code": status,
                  "timeout_seconds": seconds, "timed_out": timed_out, "wall_seconds": time.monotonic() - started}
        for stream in ("stdout", "stderr"):
            path = directory / f"{stream}.txt"
            record[stream] = {"path": str(path.relative_to(self.output)), **identity(path.read_bytes())}
        self.report["commands"].append(record)
        self.save()
        print(json.dumps({"step": label, "exit_code": status, "wall_seconds": record["wall_seconds"]}), flush=True)
        if status and not allow_failure:
            raise RuntimeError(f"{label} failed with exit {status}")
        return record

    def text(self, record, stream="stdout"):
        return (self.output / record[stream]["path"]).read_text(errors="replace")

    def require_tested_inputs(self, label):
        actual = {path: identity((self.root / path).read_bytes()) for path in LOCKS}
        matches = actual == self.report["tested_candidate_inputs"]
        self.report.setdefault("tested_input_checks", []).append({"stage": label, "actual": actual, "unchanged": matches})
        self.save()
        if not matches:
            raise ValueError("The two tested candidate locks changed: " + label)

    def run_tested(self, label, command, timeout, **options):
        self.require_tested_inputs(label + "-before")
        record = self.run(label, command, timeout, **options)
        self.require_tested_inputs(label + "-after")
        return record

    def lock(self):
        return tomllib.loads((self.root / LOCKS[0]).read_text())

    def snapshot(self, label):
        result = {}
        for relative in (*LOCKS, *PROTECTED):
            raw = (self.root / relative).read_bytes()
            result[relative] = identity(raw)
            destination = self.output / label / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(raw)
        self.report[label] = result
        self.save()
        return result

    def check_scope(self, label):
        changed = self.text(self.run(label, ["git", "diff", "HEAD", "--name-only", "-z"])).split("\0")
        changed = [p for p in changed if p]
        untracked = self.text(self.run(label + "-untracked", ["git", "ls-files", "--others", "--exclude-standard", "-z"])).split("\0")
        untracked = [p for p in untracked if p]
        result = {"changed": changed, "untracked": untracked, "allowed": set(changed) <= set(LOCKS) and not untracked}
        self.report[label] = result
        self.save()
        if not result["allowed"]:
            raise ValueError("Changes outside the two allowed lockfiles")

    def prepare(self):
        if os.environ.get("GITHUB_REF") != BRANCH:
            raise ValueError("Wrong workflow branch")
        self.run("base-ancestor", ["git", "merge-base", "--is-ancestor", BASE, "HEAD"])
        head = self.text(self.run("head", ["git", "rev-parse", "HEAD"])).strip()
        if head != self.report["source_commit"]:
            raise ValueError("Checkout does not match workflow source commit")
        status = self.text(self.run("initial-status", ["git", "status", "--porcelain"]))
        if status.strip():
            raise ValueError("Checkout is not initially clean")
        self.before = self.snapshot("before")
        for relative, expected in self.before.items():
            blob = self.text(self.run("baseline-blob", ["git", "rev-parse", f"{BASE}:{relative}"])).strip()
            if blob != expected["git_blob"]:
                raise ValueError("Baseline bytes differ: " + relative)
        for name, (old, _, _) in TARGETS.items():
            current = package_by_name(self.lock(), name)
            if current["version"] != old or current.get("source") != "registry+https://github.com/rust-lang/crates.io-index":
                raise ValueError("Unexpected initial target identity: " + name)
        self.report["input_target_versions"] = {n: package_by_name(self.lock(), n)["version"] for n in TARGETS}
        self.report["actual_versions"] = {}
        for label, command, prefix in (
            ("rustc-version", ["rustc", "+1.95.0", "-Vv"], "rustc 1.95.0 "),
            ("cargo-version", ["cargo", "+1.95.0", "-V"], "cargo 1.95.0 "),
            ("active-toolchain", ["rustup", "show", "active-toolchain"], "1.95.0"),
            ("bazel-version", ["bazel", "--version"], "bazel 9.0.0"),
            ("just-version", ["just", "--version"], "just 1.51.0"),
        ):
            actual = self.text(self.run(label, command)).strip()
            self.report["actual_versions"][label] = actual
            valid = actual == prefix if label in {"bazel-version", "just-version"} else actual.startswith(prefix)
            if not valid:
                raise ValueError(f"Unexpected {label}: {actual}")
        self.save()

    def install_deny(self):
        archive = self.temporary / "cargo-deny.tar.gz"
        self.run("download-deny", ["curl", "--fail", "--location", "--retry", "2", "--connect-timeout", "20", "--max-time", "180", "--output", str(archive), DENY_URL], 240)
        raw = archive.read_bytes()
        if len(raw) != 8265108 or identity(raw)["sha256"] != DENY_SHA256:
            raise ValueError("cargo-deny release archive identity mismatch")
        executable = self.temporary / "cargo-deny"
        with tarfile.open(archive, "r:gz") as source:
            members = [m for m in source.getmembers() if m.isfile() and Path(m.name).name == "cargo-deny"]
            if len(members) != 1:
                raise ValueError("Expected exactly one cargo-deny executable")
            executable.write_bytes(source.extractfile(members[0]).read())
        executable.chmod(0o700)
        version = self.text(self.run("deny-version", [str(executable), "--version"])).strip()
        if version != "cargo-deny 0.19.0":
            raise ValueError("Unexpected cargo-deny version: " + version)
        self.report["deny_tool"] = {"url": DENY_URL, "archive": identity(raw), "binary": identity(executable.read_bytes()), "version": version}
        return executable

    def pin_database(self, executable):
        policy = tomllib.loads((self.root / "codex-rs/deny.toml").read_text())
        configured = policy.get("advisories", {}).get("db-urls", ["https://github.com/RustSec/advisory-db"])
        if configured != ["https://github.com/RustSec/advisory-db"] or policy.get("advisories", {}).get("db-path"):
            raise ValueError("Unexpected advisory database configuration; no policy override is allowed")
        self.run("fetch-advisory-db", [str(executable), "--manifest-path", "codex-rs/Cargo.toml", "fetch", "--config", "codex-rs/deny.toml", "db"], 300)
        cargo_home_dir = Path(os.environ.get("CARGO_HOME", str(Path.home() / ".cargo")))
        candidates = []
        for marker in sorted((cargo_home_dir / "advisory-dbs").glob("*/.git")):
            repository = marker.parent
            origin = self.text(self.run("database-origin", ["git", "-C", str(repository), "config", "--get", "remote.origin.url"])).strip()
            if origin.lower().removesuffix(".git").rstrip("/") == "https://github.com/rustsec/advisory-db":
                candidates.append(repository)
        if len(candidates) != 1:
            raise ValueError("Expected one official advisory database checkout")
        repository = candidates[0]
        self.run("database-fetch-pin", ["git", "-C", str(repository), "fetch", "--no-tags", "--depth=1", "origin", DATABASE], 240)
        self.run("database-detach", ["git", "-C", str(repository), "checkout", "--detach", DATABASE])
        self.database_identity(repository, "database_before")
        return repository

    def database_identity(self, repository, label):
        head = self.text(self.run(label + "-head", ["git", "-C", str(repository), "rev-parse", "HEAD"])).strip()
        tree = self.text(self.run(label + "-tree", ["git", "-C", str(repository), "rev-parse", "HEAD^{tree}"])).strip()
        status = self.text(self.run(label + "-status", ["git", "-C", str(repository), "status", "--porcelain"]))
        if head != DATABASE or tree != DATABASE_TREE or status.strip():
            raise ValueError("Advisory database changed or is dirty")
        self.report[label] = {"head": head, "tree": tree, "clean": True}
        self.save()

    def audit(self, executable, label):
        runner = self.run_tested if "tested_candidate_inputs" in self.report else self.run
        record = runner(label, [str(executable), "--format", "json", "--log-level", "warn", "--manifest-path", "codex-rs/Cargo.toml", "--all-features", "--locked", "check", "advisories", "--disable-fetch", "--config", "codex-rs/deny.toml"], 420, allow_failure=True)
        # Retain raw JSONL even if this diagnostic parser does not recognize its schema.
        messages = []
        for stream in ("stdout", "stderr"):
            for line in self.text(record, stream).splitlines():
                try:
                    messages.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        result = {"command": record["label"], "exit_code": record["exit_code"], "json_messages": messages}
        (self.output / (label + ".json")).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        self.report[label] = {"exit_code": record["exit_code"], "parsed_message_count": len(messages),
                              "raw_json_messages": label + ".json", **summarize_advisories(messages)}
        self.save()
        return result

    def update_and_check(self, executable):
        original = tomllib.loads((self.output / "before" / LOCKS[0]).read_text())
        for index, (name, (_, target, _)) in enumerate(TARGETS.items(), 1):
            current = package_by_name(self.lock(), name)["version"]
            self.run("update-" + name, ["cargo", "+1.95.0", "update", "--manifest-path", "codex-rs/Cargo.toml", "-p", f"{name}@{current}", "--precise", target], 300)
            difference = compare_locks(original, self.lock())
            self.report[f"update_{index}"] = difference
            (self.output / f"Cargo.after-update-{index}.lock").write_bytes((self.root / LOCKS[0]).read_bytes())
            self.save()
            if not difference["only_declared_graph_change"]:
                raise ValueError("Resolver changed packages beyond the four declared targets")
            self.check_scope(f"scope-update-{index}")
        self.report["package_changes"] = compare_locks(original, self.lock())
        if not self.report["package_changes"]["all_four_targets_exact"]:
            raise ValueError("Not all four exact targets were resolved")
        self.run("bazel-lock-update", ["just", "bazel-lock-update"], 600)
        module_after_update = (self.root / LOCKS[1]).read_bytes()
        self.run("bazel-strict-lock", ["bazel", "mod", "deps", "--lockfile_mode=error"], 180)
        if (self.root / LOCKS[1]).read_bytes() != module_after_update:
            raise ValueError("Strict Bazel check changed the lock")
        self.report["bazel_lock_update_and_strict_check_passed"] = True
        self.report["tested_candidate_inputs"] = {path: identity((self.root / path).read_bytes()) for path in LOCKS}
        checked = compare_locks(original, self.lock())
        self.report["post_bazel_package_changes"] = checked
        self.save()
        if not checked["only_declared_graph_change"] or not checked["all_four_targets_exact"]:
            raise ValueError("Bazel step altered the declared Cargo graph")
        self.audit(executable, "advisories_after")
        original = json.loads((self.root / PROTECTED[-1]).read_text())["errors"]
        self.report["advisory_comparison"] = compare_advisories(self.report["advisories_before"], self.report["advisories_after"], original)
        self.save()
        selection = [part for name in CONSUMERS for part in ("-p", name)]
        graph = self.run_tested("consumer-tree", ["cargo", "+1.95.0", "tree", "--manifest-path", "codex-rs/Cargo.toml", "--locked", "--edges", "normal,build", "--prefix", "none", "--format", "{p}", *selection], 180)
        lines = self.text(graph).splitlines()
        self.report["consumer_dependency_coverage"] = {name: any(line.startswith(f"{name} v{target}") for line in lines) for name, (_, target, _) in TARGETS.items()}
        self.run_tested("consumer-check", ["cargo", "+1.95.0", "check", "--manifest-path", "codex-rs/Cargo.toml", "--locked", "--lib", *selection], 900)
        self.report["consumer_check_passed"] = True

    def finish(self):
        self.deadline = max(self.deadline, time.monotonic() + 120)
        if self.before:
            after = self.snapshot("after")
            original = tomllib.loads((self.output / "before" / LOCKS[0]).read_text())
            comparison = compare_locks(original, self.lock())
            self.report["final_package_changes"] = comparison
            self.report["final_locks_match_tested_inputs"] = {path: after[path] for path in LOCKS} == self.report.get("tested_candidate_inputs")
            final_valid = comparison["only_declared_graph_change"] and comparison["all_four_targets_exact"] and self.report["final_locks_match_tested_inputs"]
            self.report["candidate_checks_passed"] = self.report["candidate_checks_passed"] and final_valid
            self.report["protected_files_unchanged"] = all(after[p] == self.before[p] for p in PROTECTED)
            if not self.report["protected_files_unchanged"]:
                raise ValueError("Protected manifest, policy, source or toolchain bytes changed")
            self.check_scope("scope-final")
            self.run("lock-diff", ["git", "diff", "HEAD", "--binary", "--", *LOCKS], allow_failure=True)

    def seal(self):
        members = {
            str(p.relative_to(self.output)): identity(p.read_bytes())
            for p in sorted(self.output.rglob("*")) if p.is_file() and p.name not in {"MANIFEST.json", "SUMMARY.json"}
        }
        self.report["artifact_member_count_excluding_summary_manifest"] = len(members)
        self.save()
        members["SUMMARY.json"] = identity((self.output / "SUMMARY.json").read_bytes())
        (self.output / "MANIFEST.json").write_text(json.dumps({"files": members}, indent=2, sort_keys=True) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    experiment = Experiment(arguments.output)
    try:
        experiment.prepare()
        executable = experiment.install_deny()
        database = experiment.pin_database(executable)
        experiment.audit(executable, "advisories_before")
        experiment.update_and_check(executable)
        experiment.database_identity(database, "database_after")
        experiment.report["complete"] = True
        experiment.report["candidate_checks_passed"] = experiment.report["advisory_comparison"]["passed"]
        experiment.report["advisory_gate_passed"] = experiment.report["advisories_after"]["exit_code"] == 0
    except Exception as error:
        experiment.report["failure"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        try:
            experiment.finish()
        except Exception as error:
            experiment.report["finalization_failure"] = {"type": type(error).__name__, "message": str(error)}
            experiment.report["candidate_checks_passed"] = False
        experiment.seal()
    print(json.dumps({key: experiment.report[key] for key in ("complete", "candidate_checks_passed", "advisory_gate_passed")}), flush=True)
    return 0 if experiment.report["candidate_checks_passed"] and experiment.report["advisory_gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
