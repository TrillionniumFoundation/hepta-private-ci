#!/usr/bin/env python3
"""Fail-closed convergence controller for the exact PR #480 candidate.

The controller never manufactures checks or reviews. It proceeds only after a
successful r5 qualification attempt, an exact single-parent candidate, and the
expected on-repository portability repairs. It may re-request failed Actions
runs, dispatch missing required workflows that explicitly opt into
workflow_dispatch, mark the PR ready, request prior independent reviewers, and
enable ordinary auto-merge without an admin override.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterable

REPOSITORY = os.environ["GITHUB_REPOSITORY"]
TOKEN = os.environ["GH_TOKEN"]
PR_NUMBER = int(os.environ.get("TARGET_PR", "480"))
R5_RUN_ID = int(os.environ.get("R5_RUN_ID", "34310417060"))
EXPECTED_PARENT = os.environ.get(
    "EXPECTED_PARENT", "04f60466394a024c218ce66b1b32d1c42c462985"
)
OLD_CANDIDATE_HEAD = os.environ.get(
    "OLD_CANDIDATE_HEAD", "05981ed1adfb931a87a47b0606f1cedaa69f123b"
)
EXPECTED_HEAD_REF = os.environ.get(
    "EXPECTED_HEAD_REF", "codex/hepta-all-gap-closure-20260908"
)
POLL_SECONDS = int(os.environ.get("POLL_SECONDS", "30"))
MAX_WAIT_SECONDS = int(os.environ.get("MAX_WAIT_SECONDS", "7200"))
COMMENT_MARKER = "<!-- hepta-gap-convergence-controller-r6 -->"
API_ROOT = "https://api.github.com"
GRAPHQL_URL = "https://api.github.com/graphql"


class ControllerError(RuntimeError):
    pass


@dataclass(frozen=True)
class RequiredContext:
    name: str
    app_id: int | None = None


def _request(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    *,
    accepted: Iterable[int] = (200,),
) -> tuple[Any, dict[str, str]]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, method=method)
    request.add_header("Authorization", f"Bearer {TOKEN}")
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    request.add_header("User-Agent", "hepta-gap-convergence-controller-r6")
    if body is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            status = response.status
            raw = response.read()
            headers = {k.lower(): v for k, v in response.headers.items()}
    except urllib.error.HTTPError as error:
        status = error.code
        raw = error.read()
        headers = {k.lower(): v for k, v in error.headers.items()}
    if status not in set(accepted):
        detail = raw.decode("utf-8", errors="replace")[:4000]
        raise ControllerError(f"{method} {url} returned HTTP {status}: {detail}")
    if not raw:
        return None, headers
    return json.loads(raw.decode("utf-8")), headers


def api(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    accepted: Iterable[int] = (200,),
) -> Any:
    result, _ = _request(method, f"{API_ROOT}/repos/{REPOSITORY}{path}", payload, accepted=accepted)
    return result


def graphql(query: str, variables: dict[str, Any]) -> Any:
    result, _ = _request(
        "POST",
        GRAPHQL_URL,
        {"query": query, "variables": variables},
        accepted=(200,),
    )
    errors = result.get("errors") if isinstance(result, dict) else None
    if errors:
        raise ControllerError(f"GraphQL errors: {json.dumps(errors, sort_keys=True)}")
    return result["data"]


def paged(path: str, key: str | None = None) -> list[Any]:
    items: list[Any] = []
    page = 1
    separator = "&" if "?" in path else "?"
    while True:
        result = api("GET", f"{path}{separator}per_page=100&page={page}")
        batch = result[key] if key else result
        if not isinstance(batch, list):
            raise ControllerError(f"expected list from {path}, got {type(batch).__name__}")
        items.extend(batch)
        if len(batch) < 100:
            return items
        page += 1


def upsert_comment(body: str) -> None:
    comments = paged(f"/issues/{PR_NUMBER}/comments")
    full = f"{COMMENT_MARKER}\n{body}"
    for comment in reversed(comments):
        if COMMENT_MARKER in str(comment.get("body", "")):
            api("PATCH", f"/issues/comments/{comment['id']}", {"body": full})
            return
    api("POST", f"/issues/{PR_NUMBER}/comments", {"body": full}, accepted=(201,))


def successful_r5_attempt() -> tuple[bool, str]:
    deadline = time.monotonic() + MAX_WAIT_SECONDS
    while True:
        current = api("GET", f"/actions/runs/{R5_RUN_ID}")
        max_attempt = int(current.get("run_attempt", 1))
        states: list[str] = []
        for attempt in range(1, max_attempt + 1):
            try:
                data = api("GET", f"/actions/runs/{R5_RUN_ID}/attempts/{attempt}")
            except ControllerError:
                if attempt == max_attempt:
                    data = current
                else:
                    continue
            status = str(data.get("status", "unknown"))
            conclusion = str(data.get("conclusion") or "")
            states.append(f"attempt {attempt}: {status}/{conclusion or '-'}")
            if status == "completed" and conclusion == "success":
                return True, "; ".join(states)
        status = str(current.get("status", "unknown"))
        if status == "completed":
            return False, "; ".join(states)
        if time.monotonic() >= deadline:
            return False, "; ".join(states) + "; timed out"
        time.sleep(POLL_SECONDS)


def decode_content(path: str, ref: str) -> str:
    encoded_path = urllib.parse.quote(path, safe="/")
    encoded_ref = urllib.parse.quote(ref, safe="")
    item = api("GET", f"/contents/{encoded_path}?ref={encoded_ref}")
    if item.get("encoding") != "base64":
        raise ControllerError(f"unexpected encoding for {path}: {item.get('encoding')}")
    return base64.b64decode(item["content"]).decode("utf-8")


def verify_candidate(pr: dict[str, Any]) -> str:
    head_ref = pr["head"]["ref"]
    head_sha = pr["head"]["sha"]
    if head_ref != EXPECTED_HEAD_REF:
        raise ControllerError(f"unexpected PR head ref: {head_ref}")
    branch = api("GET", f"/branches/{urllib.parse.quote(head_ref, safe='')}")
    branch_sha = branch["commit"]["sha"]
    if branch_sha != head_sha:
        raise ControllerError(f"PR/branch head race: PR={head_sha}, branch={branch_sha}")
    if head_sha == OLD_CANDIDATE_HEAD:
        raise ControllerError("candidate head did not move from the pre-r5 SHA")
    commit = api("GET", f"/commits/{head_sha}")
    parents = commit.get("parents", [])
    if len(parents) != 1:
        raise ControllerError(f"candidate must have exactly one parent, observed {len(parents)}")
    parent_sha = parents[0]["sha"]
    if parent_sha != EXPECTED_PARENT:
        raise ControllerError(f"candidate parent mismatch: expected {EXPECTED_PARENT}, observed {parent_sha}")

    cognitive = decode_content("codex-rs/hepta-memory/src/cognitive_store.rs", head_sha)
    cognitive_markers = (
        "fn canonicalize_schema_sql(sql: String) -> Result<String, CognitiveStoreError>",
        'let canonical = sql.replace("\\r\\n", "\\n");',
        "let canonical_sql = canonicalize_schema_sql(sql)?;",
        "mod schema_oracle_canonicalization_tests",
    )
    missing = [marker for marker in cognitive_markers if marker not in cognitive]
    if missing:
        raise ControllerError(f"candidate is missing cognitive schema markers: {missing}")

    patch = decode_content("patches/rules_rust_windows_msvc_user_link_flags.patch", head_sha)
    patch_markers = (
        "if flavor_msvc and use_direct_driver:",
        'normalized_flag = "/LIBPATH:" + flag[len("-Lnative="):]',
        "_add_user_link_flags(ret, linker_input)",
    )
    missing_patch = [marker for marker in patch_markers if marker not in patch]
    if missing_patch:
        raise ControllerError(f"candidate is missing rules_rust repair markers: {missing_patch}")

    module = decode_content("MODULE.bazel", head_sha)
    if "rules_rust_windows_msvc_user_link_flags.patch" not in module:
        raise ControllerError("MODULE.bazel is not bound to the qualified rules_rust patch")
    return head_sha


def required_contexts(base_ref: str) -> list[RequiredContext]:
    encoded = urllib.parse.quote(base_ref, safe="")
    try:
        data = api("GET", f"/branches/{encoded}/protection/required_status_checks")
    except ControllerError as error:
        raise ControllerError(
            "required status-check policy could not be read; refusing to infer or bypass it: "
            f"{error}"
        ) from error
    result: dict[tuple[str, int | None], RequiredContext] = {}
    for name in data.get("contexts", []):
        result[(str(name), None)] = RequiredContext(str(name), None)
    for check in data.get("checks", []):
        name = str(check["context"])
        app_id = check.get("app_id")
        result[(name, app_id)] = RequiredContext(name, app_id)
    if not result:
        raise ControllerError("base branch exposes no required status checks; refusing automatic readiness")
    return sorted(result.values(), key=lambda item: (item.name, item.app_id or -1))


def check_runs(sha: str) -> list[dict[str, Any]]:
    return paged(f"/commits/{sha}/check-runs?filter=latest", key="check_runs")


def commit_statuses(sha: str) -> list[dict[str, Any]]:
    return paged(f"/commits/{sha}/statuses")


def context_state(
    context: RequiredContext,
    runs: list[dict[str, Any]],
    statuses: list[dict[str, Any]],
) -> tuple[str, dict[str, Any] | None]:
    matching_runs = [run for run in runs if run.get("name") == context.name]
    if context.app_id is not None:
        matching_runs = [
            run for run in matching_runs if (run.get("app") or {}).get("id") == context.app_id
        ]
    if matching_runs:
        run = max(matching_runs, key=lambda item: str(item.get("started_at") or item.get("created_at") or ""))
        if run.get("status") != "completed":
            return "pending", run
        conclusion = str(run.get("conclusion") or "")
        if conclusion in {"success", "neutral", "skipped"}:
            return "success", run
        return "failure", run
    matching_statuses = [status for status in statuses if status.get("context") == context.name]
    if matching_statuses:
        status = max(matching_statuses, key=lambda item: str(item.get("created_at") or ""))
        state = str(status.get("state") or "")
        if state == "success":
            return "success", status
        if state in {"pending", "expected"}:
            return "pending", status
        return "failure", status
    return "missing", None


def actions_run_id(details_url: str | None) -> int | None:
    if not details_url:
        return None
    match = re.search(r"/actions/runs/(\d+)(?:/|$)", details_url)
    return int(match.group(1)) if match else None


def rerun_current_failures(
    required: list[RequiredContext],
    runs: list[dict[str, Any]],
    statuses: list[dict[str, Any]],
) -> set[int]:
    rerun_ids: set[int] = set()
    for context in required:
        state, record = context_state(context, runs, statuses)
        if state != "failure" or not record:
            continue
        run_id = actions_run_id(record.get("details_url"))
        if run_id is None or run_id in rerun_ids:
            continue
        api("POST", f"/actions/runs/{run_id}/rerun-failed-jobs", accepted=(201,))
        rerun_ids.add(run_id)
    return rerun_ids


def dispatch_missing_workflows(
    required: list[RequiredContext],
    current_runs: list[dict[str, Any]],
    current_statuses: list[dict[str, Any]],
    old_runs: list[dict[str, Any]],
    head_ref: str,
) -> tuple[set[int], list[str]]:
    workflow_ids: set[int] = set()
    unresolved: list[str] = []
    by_name: dict[str, list[dict[str, Any]]] = {}
    for run in old_runs:
        by_name.setdefault(str(run.get("name", "")), []).append(run)
    for context in required:
        state, _ = context_state(context, current_runs, current_statuses)
        if state != "missing":
            continue
        candidates = by_name.get(context.name, [])
        if context.app_id is not None:
            candidates = [
                run for run in candidates if (run.get("app") or {}).get("id") == context.app_id
            ]
        run_ids = {
            run_id
            for run_id in (actions_run_id(run.get("details_url")) for run in candidates)
            if run_id is not None
        }
        if not run_ids:
            unresolved.append(f"{context.name}: no prior Actions run mapping")
            continue
        mapped = False
        for run_id in sorted(run_ids, reverse=True):
            run = api("GET", f"/actions/runs/{run_id}")
            workflow_id = int(run["workflow_id"])
            if workflow_id in workflow_ids:
                mapped = True
                break
            try:
                api(
                    "POST",
                    f"/actions/workflows/{workflow_id}/dispatches",
                    {"ref": head_ref},
                    accepted=(204,),
                )
            except ControllerError as error:
                unresolved.append(
                    f"{context.name}: workflow {workflow_id} did not accept workflow_dispatch ({error})"
                )
                continue
            workflow_ids.add(workflow_id)
            mapped = True
            break
        if not mapped and not any(item.startswith(f"{context.name}:") for item in unresolved):
            unresolved.append(f"{context.name}: no dispatchable workflow")
    return workflow_ids, unresolved


def wait_for_required(
    sha: str,
    required: list[RequiredContext],
    *,
    initial_unresolved: list[str],
) -> tuple[bool, list[str]]:
    deadline = time.monotonic() + MAX_WAIT_SECONDS
    last: list[str] = []
    while True:
        runs = check_runs(sha)
        statuses = commit_statuses(sha)
        last = []
        all_success = True
        for context in required:
            state, record = context_state(context, runs, statuses)
            if state != "success":
                all_success = False
                detail = ""
                if record:
                    detail = str(record.get("conclusion") or record.get("state") or record.get("status") or "")
                last.append(f"{context.name}: {state}{('/' + detail) if detail else ''}")
        if all_success:
            return True, []
        if time.monotonic() >= deadline:
            return False, initial_unresolved + last
        time.sleep(POLL_SECONDS)


def pull_graphql() -> dict[str, Any]:
    owner, name = REPOSITORY.split("/", 1)
    data = graphql(
        """
        query($owner: String!, $name: String!, $number: Int!) {
          repository(owner: $owner, name: $name) {
            pullRequest(number: $number) {
              id
              isDraft
              merged
              state
              headRefOid
              author { login }
              autoMergeRequest { enabledAt mergeMethod }
            }
          }
        }
        """,
        {"owner": owner, "name": name, "number": PR_NUMBER},
    )
    pr = data["repository"]["pullRequest"]
    if not pr:
        raise ControllerError(f"PR #{PR_NUMBER} not found")
    return pr


def mark_ready(pr_node: dict[str, Any]) -> None:
    if not pr_node["isDraft"]:
        return
    graphql(
        """
        mutation($id: ID!) {
          markPullRequestReadyForReview(input: {pullRequestId: $id}) {
            pullRequest { id isDraft }
          }
        }
        """,
        {"id": pr_node["id"]},
    )


def request_prior_independent_reviewers(pr_rest: dict[str, Any]) -> list[str]:
    author = str(pr_rest["user"]["login"])
    reviews = paged(f"/pulls/{PR_NUMBER}/reviews")
    requested = api("GET", f"/pulls/{PR_NUMBER}/requested_reviewers")
    already = {str(user["login"]) for user in requested.get("users", [])}
    reviewers: list[str] = []
    for review in reversed(reviews):
        user = review.get("user") or {}
        login = str(user.get("login") or "")
        if not login or login == author or login.endswith("[bot]") or login in already:
            continue
        if login not in reviewers:
            reviewers.append(login)
        if len(reviewers) >= 5:
            break
    if reviewers:
        try:
            api(
                "POST",
                f"/pulls/{PR_NUMBER}/requested_reviewers",
                {"reviewers": reviewers},
                accepted=(201,),
            )
        except ControllerError:
            # Readiness still causes ordinary CODEOWNERS requests where configured.
            return []
    return reviewers


def enable_auto_merge(pr_node: dict[str, Any]) -> tuple[bool, str]:
    if pr_node.get("autoMergeRequest"):
        return True, str(pr_node["autoMergeRequest"].get("mergeMethod") or "configured")
    repo = api("GET", "")
    if repo.get("allow_squash_merge"):
        method = "SQUASH"
    elif repo.get("allow_merge_commit"):
        method = "MERGE"
    elif repo.get("allow_rebase_merge"):
        method = "REBASE"
    else:
        return False, "repository exposes no allowed merge method"
    try:
        graphql(
            """
            mutation($id: ID!, $method: PullRequestMergeMethod!) {
              enablePullRequestAutoMerge(input: {pullRequestId: $id, mergeMethod: $method}) {
                pullRequest { id autoMergeRequest { enabledAt mergeMethod } }
              }
            }
            """,
            {"id": pr_node["id"], "method": method},
        )
    except ControllerError as error:
        return False, str(error)
    return True, method


def main() -> None:
    pr_rest = api("GET", f"/pulls/{PR_NUMBER}")
    if pr_rest.get("merged"):
        upsert_comment("PR is already merged; the controller made no changes.")
        return
    if pr_rest.get("state") != "open":
        raise ControllerError(f"PR #{PR_NUMBER} is not open")

    r5_ok, r5_state = successful_r5_attempt()
    if not r5_ok:
        raise ControllerError(f"no successful r5 qualification attempt: {r5_state}")

    head_sha = verify_candidate(pr_rest)
    required = required_contexts(pr_rest["base"]["ref"])
    current_runs = check_runs(head_sha)
    current_statuses = commit_statuses(head_sha)
    rerun_ids = rerun_current_failures(required, current_runs, current_statuses)
    current_runs = check_runs(head_sha)
    current_statuses = commit_statuses(head_sha)
    old_runs = check_runs(OLD_CANDIDATE_HEAD)
    workflow_ids, unresolved = dispatch_missing_workflows(
        required,
        current_runs,
        current_statuses,
        old_runs,
        pr_rest["head"]["ref"],
    )
    checks_ok, remaining = wait_for_required(
        head_sha,
        required,
        initial_unresolved=unresolved,
    )
    if not checks_ok:
        detail = "\n".join(f"- `{item}`" for item in remaining[:50])
        raise ControllerError(f"required checks did not converge on `{head_sha}`:\n{detail}")

    fresh_pr_rest = api("GET", f"/pulls/{PR_NUMBER}")
    if fresh_pr_rest["head"]["sha"] != head_sha:
        raise ControllerError("candidate head changed after qualification; refusing stale readiness")
    pr_node = pull_graphql()
    if pr_node["headRefOid"] != head_sha:
        raise ControllerError("GraphQL candidate head changed after qualification")
    mark_ready(pr_node)
    reviewers = request_prior_independent_reviewers(fresh_pr_rest)
    auto_ok, auto_detail = enable_auto_merge(pull_graphql())

    required_names = "\n".join(f"- `{context.name}`" for context in required)
    reviewer_text = ", ".join(f"@{login}" for login in reviewers) or "CODEOWNERS/existing requests unchanged"
    upsert_comment(
        "\n".join(
            [
                f"r5 qualification: **verified** ({r5_state})",
                f"exact candidate: `{head_sha}` with parent `{EXPECTED_PARENT}`",
                "single-parent and repair-marker checks: **passed**",
                "required checks on the exact candidate: **passed**",
                f"failed Actions runs re-requested: `{sorted(rerun_ids)}`",
                f"missing workflow dispatches issued: `{sorted(workflow_ids)}`",
                f"reviewers requested: {reviewer_text}",
                f"normal auto-merge: **{'enabled' if auto_ok else 'not enabled'}** (`{auto_detail}`)",
                "No administrator override, self-approval, synthetic check, or external-evidence substitution was used.",
                "\nRequired contexts:\n" + required_names,
            ]
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001 - controller must leave one audit surface.
        message = f"Controller stopped fail-closed: `{type(error).__name__}: {error}`"
        print(message, file=sys.stderr)
        try:
            upsert_comment(message)
        except Exception as comment_error:  # noqa: BLE001
            print(f"failed to update audit comment: {comment_error}", file=sys.stderr)
        raise
