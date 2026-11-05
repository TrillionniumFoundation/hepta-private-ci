"""Original native commands, complete receipts and exact selected-case checks."""

import collections
import datetime
import json
from pathlib import Path
import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET

from b16_guard import identity, need, record, same_record
from b16_oracles import clean, early_notices, qualify

HELPERS = {
    "codex-arg0": ["test_arg0_preflight"],
    "codex-code-mode-host": ["codex-code-mode-host"],
    "codex-shell-escalation": ["codex-execve-wrapper"],
    "codex-rmcp-client": ["test_stdio_server", "test_streamable_http_server"],
    "codex-exec": ["codex-exec"],
}
DRIVER_FEATURES = ["bundled", "chrono", "json", "migrate", "offline", "serde", "time", "uuid"]


def graph(metadata):
    return {"workspace_members": sorted(metadata["workspace_members"]),
            "nodes": sorted(({"id": n["id"], "features": sorted(n["features"]),
                              "deps": sorted(n.get("deps", []), key=lambda d: (d["name"], d["pkg"]))}
                             for n in metadata["resolve"]["nodes"]), key=lambda n: n["id"])}


def exact_expression(scope):
    pkg = scope["package"]
    need(re.fullmatch(r"[A-Za-z0-9_-]+", pkg), "unsafe package selector")
    result = "package(=" + pkg + ") & kind(lib)"
    names = scope.get("exact_names")
    if names is not None:
        need(names and len(names) == len(set(names)), "empty or duplicate exact roster")
        need(all(re.fullmatch(r"[A-Za-z0-9_:]+", n) for n in names), "unreviewed test selector escaping")
        result += " & (" + " | ".join("test(=" + n + ")" for n in names) + ")"
    return result


class Native:
    def __init__(self, guard, baseline_metadata):
        self.g, self.b, self.out, self.env = guard, guard.b, guard.out, guard.env
        self.target = Path(self.b["target_directory"]).resolve()
        self.expected_graph = graph(baseline_metadata)
        self.metadata = baseline_metadata
        self.reviews, self.commands, self.run_ids = [], [], set()

    def command(self, name, argv, cwd=None, separate=False, generated=(), hygiene=False):
        need(shutil.disk_usage(self.g.tree).free >= self.b["min_free_bytes"], "disk prerequisite failed before " + name)
        self.g.guard(name + "-before")
        started, clock, before = datetime.datetime.now(datetime.timezone.utc).isoformat(), time.monotonic(), self.g.source
        cwd = cwd or self.g.tree / "codex-rs"
        stdout, stderr = self.out / (name + ".log"), self.out / (name + ".stderr")
        self.g.save(name + "-command", {"argv": argv, "cwd": str(cwd), "source": before,
                    "started_at": started, "attempt": 1, "cargo_profile": "dev-small", "nextest_profile": "local"})
        print(json.dumps({"phase_start": name, "source": before, "argv": argv}), flush=True)
        result = None
        try:
            with stdout.open("xb") as so:
                if separate:
                    with stderr.open("xb") as se:
                        result = subprocess.run(argv, cwd=cwd, env=self.env, stdout=so, stderr=se)
                else:
                    result = subprocess.run(argv, cwd=cwd, env=self.env, stdout=so, stderr=subprocess.STDOUT)
        finally:
            row = {"name": name, "argv": argv, "source_before": before,
                   "exit_code": result.returncode if result is not None else None,
                   "duration_seconds": time.monotonic() - clock, "started_at": started,
                   "completed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   "stdout": record(stdout) if stdout.exists() else None,
                   "stderr": record(stderr) if stderr.exists() else None,
                   "post_source_identity": "See the immediately following whole-source guard or permitted generator/hygiene delta receipt."}
            self.commands.append(row)
            self.g.save(name + "-command-terminal", row)
            if hygiene:
                actual = self.g.snapshot(name + "-hygiene-result")
                paths = self.g.git(["diff-tree", "--no-commit-id", "--name-only", "-r", before, actual]).decode().splitlines()
                need(not any(p in self.g.locks for p in paths), "hygiene changed a lock")
                self.g.save(name + "-review-required-diff", {"before_tree": before, "after_tree": actual,
                            "paths": paths, "diff": self.g.git(["diff", before, actual]).decode(),
                            "postimages": [{"path": p, **identity((self.g.tree / p).read_bytes()),
                                            "text": (self.g.tree / p).read_text()} for p in paths],
                            "author_review_complete": False, "tests_repeated_after_hygiene": False})
                self.g.source = actual
                self.g.guard(name + "-hygiene-owned-snapshot")
            elif generated:
                self.g.accept_generated_locks(name + "-generated", generated)
            else:
                self.g.guard(name + "-after")
        need(shutil.disk_usage(self.g.tree).free >= self.b["min_free_bytes"], "disk prerequisite failed after " + name)
        return row

    def normal_helpers(self, label):
        argv = ["cargo", "build", "--locked", "--profile", "dev-small", "--message-format=json-render-diagnostics"]
        for package, bins in HELPERS.items():
            argv += ["-p", package]
            for binary in bins:
                argv += ["--bin", binary]
        r = self.command(label + "-normal-helpers", argv, separate=True)
        need(r["exit_code"] == 0, "normal helper build failed")
        want = {x for bins in HELPERS.values() for x in bins}
        artifacts, finished = [], []
        for line in Path(r["stdout"]["path"]).read_text().splitlines():
            m = json.loads(line)
            if m.get("reason") == "build-finished":
                finished.append(m)
            if m.get("reason") == "compiler-artifact" and m.get("executable") and m["target"]["name"] in want:
                p = Path(m["executable"])
                need(p.resolve().is_relative_to(self.target), "helper outside approved target")
                artifacts.append({"target": m["target"]["name"], "package_id": m["package_id"],
                                  "fresh": m["fresh"], "features": m["features"], **record(p)})
        need(finished == [{"reason": "build-finished", "success": True}], "helper build did not finish exactly once")
        need(len(artifacts) == 6 and {r["target"] for r in artifacts} == want, "normal six-helper roster mismatch")
        self.g.save(label + "-normal-helper-receipt", {"source": self.g.source, "artifacts": artifacts,
                    "limit": "Normal build identities, before possible full-catalogue feature rebuild; fresh flags are actual."})
        return artifacts

    def read_metadata(self, label, locked=True):
        argv = ["cargo", "metadata", "--format-version=1"] + (["--locked"] if locked else [])
        r = self.command(label + "-metadata", argv, separate=True,
                         generated=() if locked else ("codex-rs/Cargo.lock",))
        need(r["exit_code"] == 0, "actual full metadata failed")
        m = json.loads(Path(r["stdout"]["path"]).read_bytes())
        need(sorted(m["workspace_default_members"]) == sorted(m["workspace_members"]), "no-p command no longer selects all members")
        if locked:
            need(graph(m) == self.expected_graph, "full workspace features/dependencies changed")
        self.g.save(label + "-metadata-binding", {"source": self.g.source, "raw": r["stdout"],
                    "workspace_members": len(m["workspace_members"]), "nodes": len(m["resolve"]["nodes"]),
                    "package_filter": None, "full_graph_equal": graph(m) == self.expected_graph})
        return m

    def helper_records(self, catalog, normal):
        paths = {}

        def visit(value):
            if isinstance(value, dict):
                if value.get("kind") == "bin-exe" and isinstance(value.get("path"), str):
                    p = Path(value["path"])
                    p = p if p.is_absolute() else Path(catalog["rust-build-meta"]["target-directory"]) / p
                    paths.setdefault(str(p), []).append({"origin": "catalog", "entry": value})
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)
        visit(catalog["rust-build-meta"]["non-test-binaries"])
        for a in normal:
            paths.setdefault(a["path"], []).append({"origin": "normal-helper", "target": a["target"]})
        need(all(Path(p).resolve().is_relative_to(self.target) for p in paths), "helper escaped actual target")
        return [{"origins": origins, **record(p)} for p, origins in sorted(paths.items())]

    def run_scope(self, scope):
        label, expression = scope["label"], exact_expression(scope)
        normal = self.normal_helpers(label)
        self.read_metadata(label)
        argv = ["cargo", "nextest", "list", "--locked", "--cargo-profile", "dev-small", "--message-format=json", "-E", expression]
        r = self.command(label + "-catalog", argv, separate=True)
        need(r["exit_code"] == 0, "catalogue failed")
        cat = json.loads(Path(r["stdout"]["path"]).read_bytes())
        selected, ignored, unmatched, programs = [], [], [], []
        for sid, suite in cat["rust-suites"].items():
            matched = False
            for name, item in suite["testcases"].items():
                row = {"classname": sid, "name": name, "package": suite["package-name"],
                       "ignored": item["ignored"], "filter_match": item["filter-match"]}
                if item["filter-match"]["status"] == "matches" and not item["ignored"]:
                    selected.append(row)
                    matched = True
                elif item["ignored"]:
                    ignored.append(row)
                else:
                    unmatched.append(row)
            if matched:
                p = Path(suite["binary-path"])
                need(p.resolve().is_relative_to(self.target), "test program outside approved target")
                programs.append({"binary_id": sid, **record(p)})
        need(selected and all(x["classname"] == scope["package"] for x in selected), "wrong or empty library identity")
        names = scope.get("exact_names")
        if names is not None:
            need(collections.Counter(x["name"] for x in selected) == collections.Counter(names), "exact selected names differ")
        for support in scope.get("supports", []):
            need(sum(x["name"] == support and x["classname"] == scope["package"] for x in ignored) == 1,
                 "ignored owned support missing; it must not be counted as a pass")
        helpers = self.helper_records(cat, normal)
        self.g.save(label + "-selection", {"source": self.g.source, "scope": scope, "expression": expression,
                    "selected": selected, "original_ignored": ignored, "filtered_unmatched": unmatched,
                    "programs": programs, "helpers_after_catalog": helpers, "normal_helpers_before_catalog": normal,
                    "normal_helpers_after_catalog": [{"target": x["target"], **record(x["path"])} for x in normal],
                    "raw_catalog": r["stdout"], "helper_count_is_observed_not_inherited": len(helpers)})
        junit = self.g.tree / self.b["junit_relative_path"]
        prior = record(junit) if junit.exists() else None
        started = time.time_ns()
        argv = ["just", "test", "--locked", "--cargo-profile", "dev-small", "--no-tests", "fail",
                "--retries", "0", "--no-fail-fast", "--success-output", "immediate", "-E", expression]
        tested = self.command(label, argv)
        need(junit.is_file() and junit.stat().st_mtime_ns >= started - 2000000000, "fresh JUnit missing")
        need(prior is None or record(junit)["sha256"] != prior["sha256"], "stale JUnit reused")
        copied = self.out / (label + ".junit.xml")
        with copied.open("xb") as f:
            f.write(junit.read_bytes())
        xml = ET.parse(copied).getroot()
        run_id = xml.attrib.get("uuid")
        need(run_id and run_id not in self.run_ids, "missing/reused nextest run identity")
        self.run_ids.add(run_id)
        cases = []
        for case in xml.iter("testcase"):
            result = "FAIL" if case.find("failure") is not None else "ERROR" if case.find("error") is not None else "SKIP" if case.find("skipped") is not None else "PASS"
            need(not any("rerun" in child.tag.lower() or "flaky" in child.tag.lower() for child in case), "unexpected retry entry")
            cases.append({"classname": case.attrib.get("classname"), "name": case.attrib.get("name"),
                          "result": result, "seconds": case.attrib.get("time"),
                          "captured": "\n".join(child.text or "" for child in case if child.tag in ("system-out", "system-err", "failure", "error"))})
        keys = lambda rows: collections.Counter((x["classname"], x["name"]) for x in rows)
        program_after = [{"binary_id": p["binary_id"], **record(p["path"])} for p in programs]
        helper_after = [{"origins": p["origins"], **record(p["path"])} for p in helpers]
        raw = Path(tested["stdout"]["path"]).read_text()
        early = early_notices(raw, cases)
        valid = keys(cases) == keys(selected) and programs == program_after and helpers == helper_after and not early and all(c["result"] not in ("SKIP", "ERROR") for c in cases)
        review = {"source": self.g.source, "scope": scope, "cases": cases, "counts": dict(collections.Counter(x["result"] for x in cases)),
                  "exit_code": tested["exit_code"], "run_id": run_id, "selection_valid": valid, "retries": 0,
                  "early_return_observations": early, "programs_before": programs, "programs_after": program_after,
                  "helpers_before": helpers, "helpers_after": helper_after, "raw": tested["stdout"],
                  "fresh_junit": record(copied), "ignored_count": len(ignored), "filtered_count": len(unmatched),
                  "source_unchanged": True, "full_graph_equal": True}
        self.g.save(label + "-review", review)
        self.reviews.append(review)
        need(valid, "scope prerequisites or exact evidence failed")
        if scope.get("oracle"):
            need(tested["exit_code"] == 100 and all(c["result"] == "FAIL" for c in cases), "counterfactual failure vector wrong")
            proof = [qualify(scope["oracle"], case, self.g.tree) for case in cases]
            self.g.save(label + "-physical-proof", {"source": self.g.source, "cases": proof, "actual_junit": record(copied)})
        else:
            need(tested["exit_code"] == 0 and all(c["result"] == "PASS" for c in cases), "positive scope failed")
            if label == "B01_R2c_V3":
                need(re.search(r"commit_gate_runtime: sqlite_version=\d+\.\d+\.\d+", clean(raw)), "actual SQLx SQLite version observation missing")
        return review
