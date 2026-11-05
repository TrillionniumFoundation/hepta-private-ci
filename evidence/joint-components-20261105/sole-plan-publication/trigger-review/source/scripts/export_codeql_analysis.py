#!/usr/bin/env python3
"""Read existing CodeQL PR analyses; never scan, dismiss or change the gate.

The REST SARIF response is an API-provided subset of an analysis upload. This
exports all available exact-source analyses/categories observed after the
repository's CodeQL check completes, not all historical branch alerts. Check
annotations are retained separately and are not the complete PR gate alert set.
Checks without an API-reported PR association are exported as source-only
observations; neither their title nor another Actions suite supplies that link.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


class ExportError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise ExportError(message)


def sha(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value),
            "Expected an exact 40-character commit SHA")
    return value


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class API:
    def __init__(self, repo, token, out, deadline):
        self.base = "https://api.github.com/repos/" + repo
        self.token = token
        self.out = out
        self.deadline = deadline
        self.opener = urllib.request.build_opener(NoRedirect())

    def save(self, relative, raw):
        require(self.token.encode() not in raw, "Refusing to persist a token-bearing response")
        path = self.out / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()

    def save_json(self, relative, value):
        return self.save(relative, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())

    def get(self, path, relative, accept="application/vnd.github+json"):
        remaining = self.deadline - time.monotonic()
        require(remaining > 0, "Deadline reached before CodeQL export completed")
        request = urllib.request.Request(
            self.base + path, method="GET",
            headers={"Authorization": "Bearer " + self.token, "Accept": accept,
                     "X-GitHub-Api-Version": "2026-03-10",
                     "User-Agent": "Trillionnium-CodeQL-read-only-export"})
        try:
            with self.opener.open(request, timeout=min(30, remaining)) as response:
                chunks, size = [], 0
                while True:
                    require(time.monotonic() < self.deadline, "CodeQL export deadline reached")
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    require(size <= 256 * 1024 * 1024, "API response exceeds export size bound")
                    chunks.append(chunk)
                raw = b"".join(chunks)
        except urllib.error.HTTPError as error:
            raise ExportError(f"GitHub GET {path}: HTTP {error.code}; no fallback") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ExportError(f"GitHub GET {path}: transport failure; no fallback") from None
        self.save(relative, raw)
        try:
            return json.loads(raw)
        except (ValueError, UnicodeError):
            raise ExportError(f"GitHub GET {path}: invalid JSON") from None

    def pages(self, path, prefix, key=None, unique_ids=True):
        rows = []
        for page in range(1, 1001):
            query = "&" if "?" in path else "?"
            value = self.get(f"{path}{query}per_page=100&page={page}", f"{prefix}-{page}.json")
            batch = value.get(key) if key and isinstance(value, dict) else value
            require(isinstance(batch, list), "Expected a paginated GitHub array")
            rows.extend(batch)
            if len(batch) < 100:
                if unique_ids:
                    require(len({row["id"] for row in rows}) == len(rows),
                            "Duplicate IDs across API pages; snapshot was not stable")
                return rows
        raise ExportError("API pagination exceeded bound; refusing an incomplete export")


def target_from_event(api):
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    name = os.environ["GITHUB_EVENT_NAME"]
    repo = os.environ["GITHUB_REPOSITORY"]
    require(repo == "TrillionniumFoundation/Trillionnium-Chain", "Unexpected repository")
    require(name in {"pull_request", "workflow_dispatch"}, "Unsupported event")
    number = event.get("number") if name == "pull_request" else os.environ.get("EXPORT_PR_NUMBER")
    require(re.fullmatch(r"[1-9][0-9]*", str(number)), "Expected a positive PR number")
    number = int(number)
    pr = api.get(f"/pulls/{number}", "initial-pr.json")
    require(pr["state"] == "open" and pr["head"]["repo"]["full_name"] == repo,
            "An open same-repository PR is required")
    if name == "pull_request":
        event_pr = event["pull_request"]
        require(event_pr["head"]["repo"]["full_name"] == repo, "Fork PR is not authorized")
        head, base = sha(event_pr["head"]["sha"]), sha(event_pr["base"]["sha"])
        merge = sha(os.environ["GITHUB_SHA"])
        require(os.environ["GITHUB_REF"] == f"refs/pull/{number}/merge",
                "Event does not identify the expected PR merge ref")
    else:
        head, base = sha(pr["head"]["sha"]), sha(pr["base"]["sha"])
        merge = sha(pr["merge_commit_sha"])
    target = {"pr": number, "ref": f"refs/pull/{number}/merge",
              "head_ref": f"refs/pull/{number}/head",
              "head": head, "base": base, "merge": merge, "event": name}
    check_pr(pr, target)
    commit = api.get(f"/git/commits/{merge}", "prospective-merge.json")
    require(commit["sha"] == merge and [p["sha"] for p in commit["parents"]] == [base, head],
            "Prospective merge does not have the exact ordered base/head parents")
    api.save_json("target.json", target)
    return target


def check_pr(pr, target):
    require(pr["state"] == "open"
            and pr["head"]["repo"]["full_name"] == "TrillionniumFoundation/Trillionnium-Chain"
            and pr["head"]["sha"] == target["head"] and pr["base"]["sha"] == target["base"],
            "PR head/base moved or PR is no longer an open same-repository PR")


def configurations_missing(check):
    output = check.get("output") or {}
    text = " ".join(output.get(field) or "" for field in ("title", "summary", "text"))
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    # GitHub's aggregate check reports, for example, "1 configuration not found"
    # while /language:rust is still pending, even with status=completed.
    return bool(re.search(r"\b[1-9][0-9]*\s+configurations?\s+not\s+found\b", text, re.I))


def analysis_binding(row, target):
    require(row["tool"]["name"] == "CodeQL"
            and row["ref"] in {target["head_ref"], target["ref"]},
            "Analysis response does not match an allowed PR ref/tool")
    if row["commit_sha"] not in {target["head"], target["merge"]}:
        return None  # Preserve historical entries in the raw pages, never export them.
    require(row["ref"] != target["head_ref"] or row["commit_sha"] == target["head"],
            "PR head-ref analysis is not bound to the frozen head SHA")
    # A head commit uploaded under the merge ref still proves only head source.
    return {"ref_kind": "head" if row["ref"] == target["head_ref"] else "merge",
            "source_kind": "head" if row["commit_sha"] == target["head"] else "prospective-merge"}


def snapshot(api, target, directory):
    pr = api.get(f'/pulls/{target["pr"]}', f"{directory}/pr.json")
    check_pr(pr, target)
    checks = []
    for commit in dict.fromkeys([target["head"], target["merge"]]):
        rows = api.pages(f"/commits/{commit}/check-runs?check_name=CodeQL&filter=latest",
                         f"{directory}/checks-{commit}", "check_runs")
        for row in rows:
            if row["name"] == "CodeQL" and row.get("app", {}).get("slug") == "github-advanced-security":
                require(row["app"].get("id") == 57789, "CodeQL check app identity mismatch")
                require(row["head_sha"] == commit, "CodeQL check source mismatch")
                checks.append(row)
    # Default setup uploads to refs/pull/N/head; other setups use the merge ref.
    # The PR filter retrieves both, then analysis_binding enforces the exact pair.
    query = urllib.parse.urlencode({"pr": target["pr"], "tool_name": "CodeQL"})
    rows = api.pages("/code-scanning/analyses?" + query, f"{directory}/analyses")
    exact = []
    for row in rows:
        if analysis_binding(row, target) is not None:
            require(not row.get("error"), f'CodeQL analysis {row["id"]} reports a processing error')
            exact.append(row)
    # The aggregate check can be completed/neutral while a language is pending,
    # then update in place. Keep every intermediate observation and wait.
    # A failing vulnerability gate is still an exportable completed analysis.
    ready = bool(checks) and bool(exact) and all(
        row["status"] == "completed" and row["conclusion"] in {"success", "failure"}
        and not configurations_missing(row)
        for row in checks)
    state = {"checks": sorted(checks, key=lambda row: row["id"]),
             "analyses": sorted(exact, key=lambda row: row["id"])}
    api.save_json(f"{directory}/selection.json", {"ready": ready, **state})
    return ready, state


def export_analyses(api, target, state):
    exported = []
    fields = ("id", "ref", "commit_sha", "analysis_key", "environment", "category", "tool",
              "error", "created_at", "results_count", "rules_count", "sarif_id", "warning")
    for row in state["analyses"]:
        analysis_id = row["id"]
        require(type(analysis_id) is int and analysis_id > 0, "Invalid analysis ID")
        path = f"/code-scanning/analyses/{analysis_id}"
        prefix = f"analyses/{analysis_id}"
        metadata = api.get(path, prefix + ".json")
        require(all(metadata.get(field) == row.get(field) for field in fields),
                f"Analysis {analysis_id} changed between listing and download")
        binding = analysis_binding(metadata, target)
        require(binding is not None, f"Analysis {analysis_id} no longer has an exact source")
        sarif = api.get(path, prefix + ".sarif", "application/sarif+json")
        require(isinstance(sarif, dict) and sarif.get("version") == "2.1.0"
                and isinstance(sarif.get("runs"), list), f"Analysis {analysis_id}: invalid SARIF")
        exported.append({**{field: metadata.get(field) for field in fields},
                         **binding,
                         "metadata": prefix + ".json", "sarif_subset": prefix + ".sarif"})
    return exported


def annotation_check_binding(api, target, row):
    ident = row.get("id")
    require(type(ident) is int and ident > 0, "Invalid annotation check ID")
    require(row.get("name") == "CodeQL"
            and row.get("app", {}).get("slug") == "github-advanced-security"
            and row.get("app", {}).get("id") == 57789
            and row.get("head_sha") in {target["head"], target["merge"]},
            "Annotation check source/app mismatch")
    require(row.get("status") == "completed" and row.get("conclusion") in {"success", "failure"}
            and not configurations_missing(row), "Annotation check is not complete")
    associations = row.get("pull_requests")
    require(isinstance(associations, list), "Annotation check PR associations are not an array")
    associated = any(pr.get("number") == target["pr"]
                and all(pr.get(kind, {}).get("sha") == target[kind]
                        and pr.get(kind, {}).get("repo", {}).get("url") == api.base
                        for kind in ("head", "base"))
                for pr in associations)
    require(not associations or associated,
            "Annotation check does not identify the frozen same-repository PR head/base")
    output = row.get("output") or {}
    count = output.get("annotations_count")
    require(type(count) is int and count >= 0, "Invalid reported annotation count")
    require(output.get("annotations_url") == f"{api.base}/check-runs/{ident}/annotations",
            "Annotation URL does not identify the same repository/check")
    return {"id": ident, "head_sha": row["head_sha"],
            "requested_pr": target["pr"], "pr": target["pr"] if associated else None,
            "pr_association": "exact-head-and-base" if associated else "unavailable-source-only",
            "source_kind": "head" if row["head_sha"] == target["head"] else "prospective-merge",
            "status": row["status"], "conclusion": row["conclusion"], "output": output}


def export_check_annotations(api, target, state, directory):
    exported = []
    for row in state["checks"]:
        expected = annotation_check_binding(api, target, row)
        ident = expected["id"]
        path, prefix = f"/check-runs/{ident}", f"{directory}/{ident}"
        before = api.get(path, prefix + "/before.json")
        require(annotation_check_binding(api, target, before) == expected,
                f"Annotation check {ident} changed before download")
        # Unlike analyses/checks, this API returns annotations without IDs.
        # Preserve duplicate locations/messages and the exact raw page bodies.
        annotations = api.pages(path + "/annotations", prefix + "/page", unique_ids=False)
        after = api.get(path, prefix + "/after.json")
        require(annotation_check_binding(api, target, after) == expected,
                f"Annotation check {ident} changed during download")
        count = expected["output"]["annotations_count"]
        require(len(annotations) == count and all(isinstance(item, dict) for item in annotations),
                f"Annotation check {ident}: returned annotations do not match the reported count")
        title_count = re.match(r"^([0-9]+) new alerts\b", expected["output"].get("title") or "")
        coverage = {key: value for key, value in expected.items() if key != "output"}
        coverage.update({
            "schema": "codeql-source-check-annotations-v2",
            "reported_annotations_count": count, "exported_annotations_count": len(annotations),
            "check_alert_count_from_title": int(title_count[1])
                if title_count and expected["pr"] is not None else None,
            "gate_alert_count_from_title": int(title_count[1])
                if title_count and expected["pr"] is not None else None,
            "all_reported_check_annotations_exported": True,
            "complete_pr_gate_alert_mapping": False,
            "annotation_analysis_association": "unproven",
            "scope": "Only API-exposed source/check annotations; their count is not the PR gate alert total. "
                     "An empty PR association is explicitly unknown, not derived from a summary or Actions suite. "
                     "No SARIF matches, security pass or fixed-alert judgments are inferred.",
            "metadata_before": prefix + "/before.json", "metadata_after": prefix + "/after.json",
            "raw_pages_prefix": prefix + "/page-",
        })
        api.save_json(prefix + "/coverage.json", coverage)
        exported.append(coverage)
    return exported


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--wait-seconds", type=int, default=1200)
    parser.add_argument("--poll-seconds", type=int, default=30)
    args = parser.parse_args()
    require(1 <= args.wait_seconds <= 1500 and 1 <= args.poll_seconds <= 60, "Invalid wait bounds")
    args.out.mkdir(parents=True, exist_ok=False)
    token = os.environ.get("GITHUB_TOKEN", "")
    require(bool(token), "GITHUB_TOKEN is required")
    api = API(os.environ.get("GITHUB_REPOSITORY", ""), token, args.out,
              time.monotonic() + args.wait_seconds)
    result = {
        "schema": "codeql-exact-source-analysis-export-v2",
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "complete": False, "security_gate_changed": False,
        "target_pr_gate_authenticated": False, "target_pr_gate_verdict": None,
        "scope": "All API-available exact PR source analyses/categories after the existing CodeQL check completes; SARIF is the API-provided subset. Source-only check annotations may lack a PR association; complete export does not qualify the PR security gate.",
        "full_original_sarif_upload": False, "all_branch_historical_alerts": False,
        "analyses": [], "check_annotations": [], "error": None,
    }
    try:
        target = target_from_event(api)
        result["target"] = target
        previous = None
        attempt = 0
        while True:
            attempt += 1
            ready, state = snapshot(api, target, f"poll-{attempt:03d}")
            result["last_checks"] = [{"id": row["id"], "head_sha": row["head_sha"],
                                      "status": row["status"], "conclusion": row["conclusion"]}
                                     for row in state["checks"]]
            if ready and state == previous:
                result["analyses"] = export_analyses(api, target, state)
                result["check_annotations"] = export_check_annotations(
                    api, target, state, f"poll-{attempt:03d}-annotations")
                final_ready, final_state = snapshot(api, target, f"poll-{attempt:03d}-after-export")
                if final_ready and final_state == state:
                    result["complete"] = True
                    break
            previous = state if ready else None
            remaining = api.deadline - time.monotonic()
            require(remaining > args.poll_seconds, "CodeQL analyses/checks did not complete and stabilize before the deadline")
            print(f"Waiting for exact-source CodeQL analyses/checks (poll {attempt})", flush=True)
            time.sleep(args.poll_seconds)
    except Exception as error:
        result["error"] = str(error).replace(token, "[REDACTED]")
        print("CodeQL analysis export failed: " + result["error"], file=sys.stderr)
    finally:
        result["finished_utc"] = datetime.now(timezone.utc).isoformat()
        api.save_json("result.json", result)
        hashes = {str(p.relative_to(args.out)): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in sorted(args.out.rglob("*")) if p.is_file() and p.name != "sha256.json"}
        api.save_json("sha256.json", hashes)
    return 0 if result["complete"] else 1


if __name__ == "__main__":
    sys.exit(main())
