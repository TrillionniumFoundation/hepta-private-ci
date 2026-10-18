"""Create one bounded draft PR for an already-published self-iteration candidate.

This boundary can create a review object only. It cannot push a branch, mark a
pull request ready, approve, merge, activate, promote, deploy, or release it.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
from typing import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .control_plane import EngineeringError, canonical_repo_path, path_is_within

MAX_TITLE_BYTES = 240
MAX_BODY_BYTES = 64 * 1024
MAX_ALLOWED_ROOTS = 32
MAX_CHANGED_FILES = 256
MAX_COMMITS = 128
_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_SHA1 = re.compile(r"[0-9a-f]{40}")
_FORBIDDEN = (
    ".github",
    "docs/branch-policy.json",
    "docs/governance",
    "docs/security",
    "scripts/hepta_repository_controls.py",
    "tools/hepta-engineering-control",
)


@dataclass(frozen=True)
class DraftPullRequestRequest:
    repository: str
    base: str
    head: str
    expected_head_sha: str
    title: str
    body: str
    allowed_paths: tuple[str, ...]


@dataclass(frozen=True)
class DraftPullRequestReceipt:
    repository: str
    number: int
    url: str
    head_sha: str
    created: bool
    draft: bool = True
    merge_authority: bool = False
    activation_authority: bool = False
    promotion_authority: bool = False
    release_authority: bool = False


ApiCall = Callable[[str, str, Mapping[str, object] | None], object]


def _fail(code: str) -> None:
    raise EngineeringError(code)


def _bounded_text(value: str, limit: int, code: str) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > limit:
        _fail(code)
    return value


def _validate_request(value: DraftPullRequestRequest) -> tuple[str, ...]:
    if not _REPOSITORY.fullmatch(value.repository):
        _fail("invalid_repository")
    if value.base != "main":
        _fail("self_iteration_base_must_be_main")
    if (
        not isinstance(value.head, str)
        or not value.head.startswith("self-iteration/")
        or value.head.endswith("/")
        or ".." in value.head
        or not re.fullmatch(r"[A-Za-z0-9._/-]+", value.head)
    ):
        _fail("invalid_self_iteration_head")
    if not _SHA1.fullmatch(value.expected_head_sha):
        _fail("invalid_head_sha")
    _bounded_text(value.title, MAX_TITLE_BYTES, "invalid_pr_title")
    _bounded_text(value.body, MAX_BODY_BYTES, "invalid_pr_body")
    if (
        not isinstance(value.allowed_paths, tuple)
        or not value.allowed_paths
        or len(value.allowed_paths) > MAX_ALLOWED_ROOTS
    ):
        _fail("invalid_allowed_paths")
    roots = tuple(canonical_repo_path(path) for path in value.allowed_paths)
    if len(set(roots)) != len(roots):
        _fail("duplicate_allowed_path")
    for root in roots:
        if any(path_is_within(root, (denied,)) or path_is_within(denied, (root,)) for denied in _FORBIDDEN):
            _fail("protected_path_requested")
    return roots


def _as_mapping(value: object, code: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        _fail(code)
    return value


def _changed_paths(compare: Mapping[str, object], roots: tuple[str, ...]) -> None:
    ahead = compare.get("ahead_by")
    commits = compare.get("total_commits")
    files = compare.get("files")
    if type(ahead) is not int or ahead <= 0:
        _fail("candidate_not_ahead")
    if type(commits) is not int or not 1 <= commits <= MAX_COMMITS:
        _fail("candidate_commit_bound")
    if not isinstance(files, list) or not files or len(files) > MAX_CHANGED_FILES:
        _fail("candidate_file_bound")
    for item in files:
        row = _as_mapping(item, "invalid_candidate_file")
        path = canonical_repo_path(row.get("filename"))
        if any(path_is_within(path, (denied,)) for denied in _FORBIDDEN):
            _fail("protected_path_changed")
        if not any(path_is_within(path, (root,)) for root in roots):
            _fail("candidate_path_outside_envelope")


def open_draft_pull_request(
    value: DraftPullRequestRequest,
    api: ApiCall,
) -> DraftPullRequestReceipt:
    roots = _validate_request(value)
    repository = quote(value.repository, safe="/")
    head_path = quote(value.head, safe="")
    ref = _as_mapping(
        api("GET", f"/repos/{repository}/git/ref/heads/{head_path}", None),
        "invalid_head_observation",
    )
    target = _as_mapping(ref.get("object"), "invalid_head_observation")
    if target.get("type") != "commit" or target.get("sha") != value.expected_head_sha:
        _fail("head_sha_mismatch")

    compare_path = (
        f"/repos/{repository}/compare/"
        f"{quote(value.base, safe='')}...{head_path}"
    )
    compare = _as_mapping(api("GET", compare_path, None), "invalid_compare_observation")
    if compare.get("status") not in {"ahead", "diverged"}:
        _fail("candidate_not_reviewable")
    _changed_paths(compare, roots)

    owner = value.repository.split("/", 1)[0]
    query = urlencode(
        {
            "state": "open",
            "base": value.base,
            "head": f"{owner}:{value.head}",
            "per_page": "2",
        }
    )
    existing = api("GET", f"/repos/{repository}/pulls?{query}", None)
    if not isinstance(existing, list) or len(existing) > 1:
        _fail("invalid_existing_pr_observation")
    if existing:
        row = _as_mapping(existing[0], "invalid_existing_pr_observation")
        head = _as_mapping(row.get("head"), "invalid_existing_pr_observation")
        if row.get("draft") is not True or head.get("sha") != value.expected_head_sha:
            _fail("existing_pr_conflict")
        return _receipt(value, row, created=False)

    created = _as_mapping(
        api(
            "POST",
            f"/repos/{repository}/pulls",
            {
                "title": value.title,
                "body": value.body,
                "head": value.head,
                "base": value.base,
                "draft": True,
                "maintainer_can_modify": False,
            },
        ),
        "invalid_created_pr",
    )
    return _receipt(value, created, created=True)


def _receipt(
    request: DraftPullRequestRequest,
    value: Mapping[str, object],
    *,
    created: bool,
) -> DraftPullRequestReceipt:
    number = value.get("number")
    url = value.get("html_url")
    if type(number) is not int or number <= 0 or not isinstance(url, str) or not url:
        _fail("invalid_pr_receipt")
    return DraftPullRequestReceipt(
        repository=request.repository,
        number=number,
        url=url,
        head_sha=request.expected_head_sha,
        created=created,
    )


def github_api(token: str, api_root: str = "https://api.github.com") -> ApiCall:
    if not isinstance(token, str) or not token or api_root != "https://api.github.com":
        _fail("invalid_github_transport")

    def call(method: str, path: str, payload: Mapping[str, object] | None) -> object:
        if method not in {"GET", "POST"} or not path.startswith("/repos/"):
            _fail("forbidden_github_operation")
        if method == "POST" and not path.endswith("/pulls"):
            _fail("forbidden_github_operation")
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            api_root + path,
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "hepta-control-engineering",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                raw = response.read(MAX_BODY_BYTES + 1)
        except (HTTPError, URLError, TimeoutError) as error:
            raise EngineeringError("github_pr_transport_failed") from error
        if len(raw) > MAX_BODY_BYTES:
            _fail("github_response_too_large")
        try:
            return json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise EngineeringError("invalid_github_response") from error

    return call
