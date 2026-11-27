"""Identity checks for the reviewed OAuth-origin conformance fixture fork.

The fork changes only the trusted fixture launcher sideband. These checks do
not waive any MCP conformance assertion or turn a previous failure into a pass.
"""

import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import time
import urllib.error
import urllib.request

UPSTREAM_REPOSITORY = "modelcontextprotocol/conformance"
UPSTREAM_COMMIT = "49103de6ed70804e940637bf3e9e29e4a3f54e64"
UPSTREAM_TREE = "699705222f144a15fb7fdcc1b4f0b0a62825aef0"
PATCH_PATHS = (
    "src/runner/client.ts",
    "src/runner/oauth-authorization-origins.test.ts",
    "src/scenarios/client/auth/discovery-metadata.ts",
    "src/scenarios/client/auth/token-endpoint-auth.ts",
)
# Proposed new engineering bounds; the manifest stays inactive until Root
# explicitly accepts the complete source and these bounds.
CAPS = {"whole_seconds": 420, "command_seconds": 400, "retention_seconds": 20}
HEPTA_EXEC_GIT_BLOB = "491caed67eda5d820473d05717aaaa03b1828609"
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
COMMAND_LABELS = (
    "hepta-before",
    "hepta-before-commit",
    "hepta-before-status",
    "version-node",
    "version-npm",
    "source-controls",
    "upstream-init",
    "upstream-fetch",
    "upstream-checkout",
    "upstream-head",
    "upstream-tree",
    "patch-check",
    "patch-apply",
    "install",
    "controls",
    "build",
    "hepta-after",
    "hepta-after-commit",
    "hepta-after-status",
)


SOURCE_CONTROL_NAMES = (
    "test_conformance_fixture.FixtureReceiptTests.test_duplicate_json_and_symlink_dist_are_rejected",
    "test_conformance_fixture.FixtureReceiptTests.test_exact_executed_file_and_eight_names_are_required",
    "test_conformance_fixture.FixtureReceiptTests.test_manifest_stays_closed_without_explicit_root_activation",
    "test_conformance_fixture.FixtureReceiptTests.test_raw_commit_preserves_parents_tree_and_message_bytes",
    "test_oauth_authorization_origins.AuthorizationOriginSidebandTests.test_absent_sideband_and_empty_array_grant_nothing",
    "test_oauth_authorization_origins.AuthorizationOriginSidebandTests.test_duplicates_and_bounded_input_overflow_are_rejected",
    "test_oauth_authorization_origins.AuthorizationOriginSidebandTests.test_empty_origins_preserve_legacy_registration_shape",
    "test_oauth_authorization_origins.AuthorizationOriginSidebandTests.test_exact_canonical_origins_are_preserved",
    "test_oauth_authorization_origins.AuthorizationOriginSidebandTests.test_metadata_objects_and_malformed_values_are_not_authority",
    "test_oauth_authorization_origins.AuthorizationOriginSidebandTests.test_noncanonical_origin_aliases_paths_and_credentials_are_rejected",
    "test_oauth_authorization_origins.AuthorizationOriginSidebandTests.test_origin_config_retains_client_id_and_secret_environment_reference",
    "test_oauth_authorization_origins.AuthorizationOriginSidebandTests.test_owner_origin_is_written_even_without_a_pre_registered_client",
    "test_conformance_fixture.OriginalCandidateIdentityTests.test_same_head_old_run_attempt_and_job_are_rejected",
    "test_conformance_fixture.OriginalCandidateIdentityTests.test_publication_requires_actual_parent_and_exact_roster",
    "test_conformance_fixture.OriginalCandidateIdentityTests.test_binary_receipt_rejects_wrong_bytes_or_missing_sibling",
    "test_conformance_fixture.OriginalCandidateIdentityTests.test_binary_mutation_changes_actual_observation",
    "test_conformance_fixture.OriginalCandidateIdentityTests.test_full_physical_tree_rejects_changed_file_and_symlink",
    "test_conformance_fixture.OriginalCandidateIdentityTests.test_full_tree_digest_rejects_claimed_wrong_blob",
    "test_conformance_fixture.OriginalCandidateIdentityTests.test_current_job_rejects_ambiguity_and_wrong_attempt",
    "test_conformance_fixture.OriginalCandidateIdentityTests.test_original_build_prerequisite_cannot_be_pending_or_failed",
    "test_conformance_fixture.OriginalCandidateIdentityTests.test_identity_api_retains_partial_failure_bytes",
    "test_conformance_fixture.OriginalCandidateIdentityTests.test_current_execution_queued_run_requires_active_original_job_and_step",
    "test_conformance_fixture.OriginalCandidateIdentityTests.test_current_execution_rejects_run_identity_and_terminal_states",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def regular_bytes(path: Path, limit: int) -> bytes:
    before = path.lstat()
    require(
        stat.S_ISREG(before.st_mode) and not path.is_symlink(),
        f"not a regular file: {path}",
    )
    require(before.st_size <= limit, f"file exceeds bound: {path}")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        raw = stream.read(limit + 1)
        finished = os.fstat(stream.fileno())
        after = path.lstat()
        common = lambda value: (
            value.st_dev,
            value.st_ino,
            value.st_size,
            value.st_mtime_ns,
        )
        require(
            all(
                stat.S_ISREG(value.st_mode)
                for value in (before, opened, finished, after)
            )
            and common(before) == common(opened) == common(finished) == common(after)
            and before.st_ctime_ns == after.st_ctime_ns
            and opened.st_ctime_ns == finished.st_ctime_ns
            and len(raw) == before.st_size <= limit,
            f"file changed while reading: {path}",
        )
    return raw


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    value = {}
    for key, item in pairs:
        require(key not in value, f"duplicate JSON field: {key}")
        value[key] = item
    return value


def read_json(path: Path, limit: int = 4 * 1024 * 1024) -> tuple[dict, str]:
    raw = regular_bytes(path, limit)
    value = json.loads(raw, object_pairs_hook=_unique_object)
    require(isinstance(value, dict), "JSON document must be an object")
    return value, hashlib.sha256(raw).hexdigest()


def git_blob(raw: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def commit_identity(raw: bytes) -> dict:
    headers = raw.split(b"\n\n", 1)[0].decode("utf-8").splitlines()
    trees = [line[5:] for line in headers if line.startswith("tree ")]
    parents = [line[7:] for line in headers if line.startswith("parent ")]
    require(
        len(trees) == 1 and HEX40.fullmatch(trees[0]) is not None,
        "Git commit tree header differs",
    )
    require(
        all(HEX40.fullmatch(parent) is not None for parent in parents),
        "Git commit parent header differs",
    )
    return {
        "commit": hashlib.sha1(
            b"commit " + str(len(raw)).encode() + b"\0" + raw
        ).hexdigest(),
        "tree": trees[0],
        "parents": parents,
        "dirty": False,
    }


def safe_relative(value: str) -> str:
    require(isinstance(value, str) and bool(value), "file path must be nonempty text")
    path = PurePosixPath(value)
    require(
        not path.is_absolute()
        and str(path) == value
        and all(part not in ("", ".", "..", ".git") for part in value.split("/"))
        and "\\" not in value
        and "\0" not in value,
        "noncanonical relative file path",
    )
    return value


def source_tree(files: dict, prefix: str = "") -> str:
    children = {}
    for path, leaf in files.items():
        if not path.startswith(prefix):
            continue
        name, separator, _ = path[len(prefix) :].partition("/")
        if separator:
            require(
                name not in children or children[name] is None,
                "file/directory collision",
            )
            children[name] = None
        else:
            require(name not in children, "duplicate tree entry")
            children[name] = leaf
    raw = bytearray()
    for name, leaf in sorted(
        children.items(), key=lambda item: item[0] + ("/" if item[1] is None else "")
    ):
        digest = (
            source_tree(files, prefix + name + "/")
            if leaf is None
            else leaf["git_blob"]
        )
        raw.extend(
            ("40000" if leaf is None else "100644").encode()
            + b" "
            + name.encode()
            + b"\0"
        )
        raw.extend(bytes.fromhex(digest))
    return hashlib.sha1(b"tree " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def _validate_files(files: object, expected_count: int) -> dict:
    require(
        isinstance(files, dict) and len(files) == expected_count,
        "source leaf count differs",
    )
    for path, leaf in files.items():
        safe_relative(path)
        require(
            isinstance(leaf, dict) and set(leaf) == {"bytes", "git_blob"},
            "source leaf schema differs",
        )
        require(
            type(leaf["bytes"]) is int and 0 <= leaf["bytes"] <= 2 * 1024 * 1024,
            "invalid source byte bound",
        )
        require(
            isinstance(leaf["git_blob"], str)
            and HEX40.fullmatch(leaf["git_blob"]) is not None,
            "invalid Git blob",
        )
    return files


def load_manifest(path: Path) -> tuple[dict, str]:
    manifest, digest = read_json(path)
    require(
        manifest.get("schema") == "hepta-oauth-origin-fixture-v2",
        "fixture manifest schema differs",
    )
    require(
        manifest.get("activated") is True, "fixture source is not activated by Root"
    )
    admission = manifest.get("root_admission")
    require(
        isinstance(admission, dict)
        and admission.get("reviewer") == "root"
        and admission.get("accepted") is True,
        "missing explicit Root admission",
    )
    require(
        isinstance(admission.get("sha256"), str)
        and HEX64.fullmatch(admission["sha256"]) is not None,
        "invalid Root admission hash",
    )
    require(
        manifest.get("upstream")
        == {
            "repository": UPSTREAM_REPOSITORY,
            "commit": UPSTREAM_COMMIT,
            "tree": UPSTREAM_TREE,
        },
        "upstream identity differs",
    )
    require(manifest.get("caps") == CAPS, "fixture budget differs")
    publication_binding(manifest)
    before = _validate_files(manifest.get("source_files"), 263)
    after = _validate_files(manifest.get("postimage_files"), 264)
    require(
        sum(leaf["bytes"] for leaf in before.values()) == 2923041,
        "upstream source byte sum differs",
    )
    require(source_tree(before) == UPSTREAM_TREE, "upstream Git tree differs")
    require(
        isinstance(manifest.get("fork_source_tree"), str)
        and source_tree(after) == manifest["fork_source_tree"],
        "fork Git tree differs",
    )
    changes = sorted(
        path for path in set(before) | set(after) if before.get(path) != after.get(path)
    )
    require(changes == list(PATCH_PATHS), "fixture patch changed an unexpected path")
    patch = manifest.get("patch")
    require(
        isinstance(patch, dict) and patch.get("path") == "oauth-origin-fixture.patch",
        "patch path differs",
    )
    require(
        type(patch.get("bytes")) is int and 0 < patch["bytes"] <= 128 * 1024,
        "invalid patch byte bound",
    )
    require(
        isinstance(patch.get("sha256"), str)
        and HEX64.fullmatch(patch["sha256"]) is not None,
        "invalid patch SHA256",
    )
    controls = manifest.get("controls")
    require(
        isinstance(controls, dict) and controls.get("file") == PATCH_PATHS[1],
        "fixture control file differs",
    )
    names = controls.get("titles")
    require(
        isinstance(names, list)
        and len(names) == 8
        and all(isinstance(name, str) and name for name in names),
        "fixture requires eight named controls",
    )
    require(len(set(names)) == 8, "duplicate fixture control name")
    return manifest, digest


def validate_controls(document: dict, source: Path, names: list[str]) -> list[dict]:
    require(document.get("success") is True, "fixture controls did not succeed")
    for key in (
        "numFailedTests",
        "numPendingTests",
        "numTodoTests",
        "numFailedTestSuites",
        "numPendingTestSuites",
    ):
        require(
            type(document.get(key)) is int and document[key] == 0,
            f"fixture controls have {key}",
        )
    require(
        document.get("numTotalTests") == len(names) == document.get("numPassedTests"),
        "fixture control count differs",
    )
    require(
        type(document.get("numTotalTestSuites")) is int
        and document["numTotalTestSuites"] > 0
        and document["numPassedTestSuites"] == document["numTotalTestSuites"],
        "fixture suite count differs",
    )
    results = document.get("testResults")
    require(
        isinstance(results, list) and len(results) == 1,
        "fixture controls must use one exact test file",
    )
    result = results[0]
    require(
        result.get("name") == str(source.resolve())
        and result.get("status") == "passed"
        and result.get("message") == "",
        "fixture control file identity or terminal differs",
    )
    assertions = result.get("assertionResults")
    require(
        isinstance(assertions, list) and len(assertions) == len(names),
        "fixture assertions missing or extra",
    )
    observed = []
    for assertion in assertions:
        require(
            assertion.get("status") == "passed"
            and assertion.get("failureMessages") == [],
            "fixture assertion failed, skipped or unobserved",
        )
        require(
            isinstance(assertion.get("title"), str), "fixture assertion lacks its name"
        )
        observed.append(assertion["title"])
    require(
        len(set(observed)) == len(names) and sorted(observed) == sorted(names),
        "fixture names missing, duplicate or extra",
    )
    return assertions


def validate_source_controls(raw: bytes) -> None:
    text = raw.decode("utf-8")
    observed = []
    for line in text.splitlines():
        if line.endswith(" ... ok"):
            observed.append(line)
    expected = [
        f"{name.rsplit('.', 1)[1]} ({name}) ... ok" for name in SOURCE_CONTROL_NAMES
    ]
    require(
        sorted(observed) == sorted(expected),
        "Python source controls missing, duplicate, extra or skipped",
    )
    require(
        len(
            re.findall(
                rf"(?m)^Ran {len(SOURCE_CONTROL_NAMES)} tests in [0-9.]+s$", text
            )
        )
        == 1
        and len(re.findall(r"(?m)^OK$", text)) == 1,
        "Python source control terminal differs",
    )


def snapshot_dist(directory: Path) -> dict:
    require(
        directory.is_dir() and not directory.is_symlink(),
        "fixture dist is not a directory",
    )
    result = {}
    total = 0
    for root, directories, names in os.walk(directory):
        for name in directories:
            require(not (Path(root) / name).is_symlink(), "symlink in fixture dist")
        for name in names:
            path = Path(root) / name
            raw = regular_bytes(path, 32 * 1024 * 1024)
            total += len(raw)
            require(
                total <= 64 * 1024 * 1024 and len(result) < 512,
                "fixture dist exceeds bound",
            )
            result[path.relative_to(directory).as_posix()] = {
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
    require("index.js" in result, "fixture CLI was not built")
    return result


def verify_receipt(
    receipt_path: Path,
    manifest_path: Path,
    cli_path: Path,
    source_identity: dict | None,
    codex_path: Path,
    phase: str,
) -> dict:
    manifest, manifest_sha = load_manifest(manifest_path)
    receipt, receipt_sha = read_json(receipt_path)
    require(
        receipt.get("schema") == "hepta-oauth-origin-fixture-build-v2"
        and receipt.get("status") == "passed",
        "fixture build lacks a passing terminal receipt",
    )
    require(
        receipt.get("kind") == "reviewed-upstream-fixture-fork",
        "fixture provenance differs",
    )
    require(
        type(receipt.get("exit_code_before_final_io")) is int
        and receipt["exit_code_before_final_io"] == 0,
        "fixture build has no successful command result",
    )
    require(receipt.get("caps") == CAPS, "fixture receipt budget differs")
    original_build, actual_source = observe_fixture_use(
        receipt_path, manifest, receipt, source_identity, codex_path, phase
    )
    source_identity = actual_source
    commands = receipt.get("commands")
    require(
        isinstance(commands, list)
        and [row.get("label") for row in commands] == list(COMMAND_LABELS),
        "fixture command evidence missing, repeated or reordered",
    )
    for row in commands:
        execution = row.get("execution")
        require(
            isinstance(execution, dict)
            and type(execution.get("returncode")) is int
            and execution["returncode"] == 0
            and execution.get("timed_out") is False
            and execution.get("output_limit_exceeded") is False,
            "fixture child command lacks a successful terminal",
        )
        command_elapsed = row.get("elapsed_seconds")
        cap = row.get("cap_seconds")
        require(
            type(command_elapsed) in (float, int)
            and type(cap) in (float, int)
            and math.isfinite(command_elapsed)
            and 0 <= command_elapsed <= cap <= 180,
            "fixture command exceeded its bound",
        )
        log = row.get("log")
        require(
            isinstance(log, dict) and log.get("path") == row["label"] + ".log",
            "fixture log path differs",
        )
        log_raw = regular_bytes(
            receipt_path.resolve().parent / log["path"], 16 * 1024 * 1024
        )
        log_sha = hashlib.sha256(log_raw).hexdigest()
        require(
            log.get("bytes") == execution.get("log_bytes") == len(log_raw)
            and log.get("sha256") == execution.get("log_sha256") == log_sha,
            "fixture raw child output changed",
        )
    require(
        receipt.get("manifest_sha256") == manifest_sha
        and receipt.get("upstream") == manifest["upstream"],
        "fixture manifest or upstream binding differs",
    )
    require(
        receipt.get("fork_source_tree") == manifest["fork_source_tree"],
        "fixture postimage tree differs",
    )
    require(
        receipt.get("source_before") == source_identity == receipt.get("source_after"),
        "fixture was built for different Hepta source",
    )
    elapsed = receipt.get("elapsed_seconds_before_final_io")
    require(
        type(elapsed) in (float, int)
        and math.isfinite(elapsed)
        and 0 <= elapsed <= CAPS["whole_seconds"],
        "fixture build time differs",
    )
    require(
        receipt.get("within_budget_before_final_io") is True,
        "fixture build exceeded its acceptance deadline",
    )
    validate_source_controls(
        regular_bytes(
            receipt_path.resolve().parent / "source-controls.log", 16 * 1024 * 1024
        )
    )
    expected_cli = receipt_path.resolve().parent / "upstream" / "dist" / "index.js"
    require(cli_path.resolve() == expected_cli, "fixture CLI path differs")
    require(
        snapshot_dist(expected_cli.parent) == receipt.get("dist_files"),
        "fixture CLI or chunk bytes changed",
    )
    controls, control_sha = read_json(receipt_path.resolve().parent / "controls.json")
    require(
        control_sha == receipt.get("controls_sha256"),
        "fixture control artifact changed",
    )
    validate_controls(
        controls,
        expected_cli.parent.parent / manifest["controls"]["file"],
        manifest["controls"]["titles"],
    )
    require(
        receipt.get("dependency_install")
        == "npm ci --ignore-scripts --no-audit --no-fund",
        "fixture dependency installation differs",
    )
    lock = regular_bytes(
        expected_cli.parent.parent / "package-lock.json", 2 * 1024 * 1024
    )
    require(
        git_blob(lock) == manifest["source_files"]["package-lock.json"]["git_blob"],
        "fixture dependency lock changed",
    )
    return {
        "kind": receipt["kind"],
        "upstream": receipt["upstream"],
        "forkSourceTree": receipt["fork_source_tree"],
        "manifestSha256": manifest_sha,
        "buildReceiptSha256": receipt_sha,
        "distFiles": receipt["dist_files"],
        "controls": manifest["controls"]["titles"],
        "newConformancePassClaimed": False,
        "originalBuild": original_build,
        "sourceIdentity": actual_source,
        "consumptionBoundary": phase,
    }


# Source/event/binary binding is independent of conformance result assertions.
HEPTA_REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
HEPTA_PARENT = {
    "head": "c4e55200f120d3afe9741364f091085ed1a27458",
    "tree": "22ae104f62c4f8d8cee35a020d9f4c45a3059011",
}
HEPTA_CHANGED_PATHS = (
    "scripts/mcp_conformance/README.md",
    "scripts/mcp_conformance/conformance_fixture.py",
    "scripts/mcp_conformance/oauth-origin-fixture.json",
    "scripts/mcp_conformance/test_conformance_fixture.py",
)
BUILD_STEP = "Build codex and code-mode host with Bazel"
FIXTURE_STEP = "Build reviewed OAuth-origin conformance fixture"
TEST_STEP = "Test SDK packages"
SOURCE_BYTES_LIMIT = 512 * 1024 * 1024
BINARY_BYTES_LIMIT = 1024 * 1024 * 1024


def identity_remaining(deadline):
    left = deadline - time.monotonic()
    require(
        math.isfinite(left) and left > 0,
        "identity observation exhausted its existing deadline",
    )
    return left


def identity_save(path, raw):
    with path.open("xb") as stream:
        require(stream.write(raw) == len(raw), "short identity evidence write")
        stream.flush()
        os.fsync(stream.fileno())


def identity_json(path, value):
    identity_save(
        path, (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    )


class _NoIdentityRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("identity API redirects are not accepted")


class IdentityAPI:
    def __init__(self, output, deadline):
        self.output, self.deadline, self.rows = output, deadline, []
        self.token = os.environ.get("GH_TOKEN", "")
        require(bool(self.token), "current workflow read token is absent")
        self.opener = urllib.request.build_opener(_NoIdentityRedirect())

    def get(self, suffix, label):
        require(
            re.fullmatch(r"[a-z0-9-]+", label) is not None, "identity evidence label"
        )
        url = "https://api.github.com/repos/" + HEPTA_REPOSITORY + suffix
        require(
            suffix.startswith("/") and "\\" not in suffix and "#" not in suffix,
            "identity API path",
        )
        row = {"request_url": url, "received_bytes": 0, "retained_bytes": 0}
        self.rows.append(row)
        chunks, original = [], None
        response = None
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "Authorization": "Bearer " + self.token,
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                    "User-Agent": "hepta-c2-original-identity-v3",
                },
            )
            try:
                response = self.opener.open(
                    request, timeout=min(10, identity_remaining(self.deadline))
                )
            except urllib.error.HTTPError as error:
                response, original = error, error
            with response:
                row.update(
                    status=response.status,
                    response_url=response.geturl(),
                    headers=dict(response.headers.items()),
                )
                require(
                    row["response_url"] == url, "identity API response origin changed"
                )
                limit = 1024 * 1024 if original is not None else 12 * 1024 * 1024
                while True:
                    identity_remaining(self.deadline)
                    try:
                        block = response.read(
                            min(65536, limit - row["retained_bytes"] + 1)
                        )
                    except BaseException as error:
                        row["body_read_error"] = repr(error)
                        partial = getattr(error, "partial", b"")
                        if isinstance(partial, bytes):
                            row["received_bytes"] += len(partial)
                            kept = partial[: max(0, limit - row["retained_bytes"])]
                            chunks.append(kept)
                            row["retained_bytes"] += len(kept)
                            row["exception_partial_bytes"] = len(partial)
                            row["body_overflow"] = row["received_bytes"] > limit
                        elif partial:
                            row["exception_partial_unavailable"] = repr(type(partial))
                        if original is not None:
                            raise original from error
                        raise
                    if not block:
                        row["body_eof"] = True
                        break
                    row["received_bytes"] += len(block)
                    kept = block[: max(0, limit - row["retained_bytes"])]
                    chunks.append(kept)
                    row["retained_bytes"] += len(kept)
                    require(
                        row["received_bytes"] <= limit,
                        "identity API body exceeds its bound",
                    )
                if original is not None:
                    raise original
                require(row["status"] == 200, "identity API status")
                value = json.loads(
                    b"".join(chunks),
                    object_pairs_hook=_unique_object,
                    parse_constant=lambda value: (_ for _ in ()).throw(
                        ValueError(value)
                    ),
                )
                require(isinstance(value, dict), "identity API object")
                return value
        except BaseException as error:
            if original is None:
                original = error
            row["error"] = repr(original)
            if original is not error:
                raise original from error
            raise
        finally:
            raw = b"".join(chunks)
            row["sha256"] = hashlib.sha256(raw).hexdigest()
            try:
                identity_save(self.output / (label + ".body"), raw)
                identity_json(self.output / (label + ".json"), row)
                identity_remaining(self.deadline)
            except BaseException as retention:
                row["retention_error"] = repr(retention)
                if original is None:
                    raise
                original.add_note(
                    "identity API evidence retention failed: " + repr(retention)
                )


def publication_binding(manifest):
    publication = manifest.get("publication")
    require(isinstance(publication, dict), "publication binding is absent")
    require(
        publication.get("parent") == HEPTA_PARENT,
        "fixture does not bind the accepted parent",
    )
    require(
        publication.get("source_paths") == list(HEPTA_CHANGED_PATHS),
        "Hepta exact source scope differs",
    )
    require(
        publication.get("requires_actual_parent") is True
        and publication.get("root_must_bind_final_candidate") is True,
        "publication authority changed",
    )
    return publication


def source_map(document, expected_tree):
    require(
        document.get("sha") == expected_tree and document.get("truncated") is False,
        "complete immutable Git tree is required",
    )
    entries = document.get("tree")
    require(
        isinstance(entries, list) and 0 < len(entries) <= 25000, "Git tree cardinality"
    )
    result = {}
    for leaf in entries:
        path = safe_relative(leaf["path"])
        if leaf.get("type") == "tree":
            require(leaf.get("mode") == "040000", "tree mode")
            continue
        require(
            leaf.get("type") == "blob"
            and leaf.get("mode") in ("100644", "100755", "120000"),
            "unsupported source object",
        )
        require(
            path not in result and HEX40.fullmatch(leaf["sha"]) is not None,
            "duplicate source/blob",
        )
        require(
            type(leaf.get("size")) is int and 0 <= leaf["size"] <= SOURCE_BYTES_LIMIT,
            "source size",
        )
        result[path] = {
            "bytes": leaf["size"],
            "git_blob": leaf["sha"],
            "mode": leaf["mode"],
        }
    require(
        len(result) <= 20000
        and sum(row["bytes"] for row in result.values()) <= SOURCE_BYTES_LIMIT,
        "source tree exceeds original observation bounds",
    )
    require(
        identity_tree(result) == expected_tree, "full Git tree reconstruction differs"
    )
    return result


def identity_tree(files, prefix=""):
    children = {}
    for path, leaf in files.items():
        if path.startswith(prefix):
            name, sep, _ = path[len(prefix) :].partition("/")
            require(
                name not in children or (sep and children[name] is None),
                "tree collision",
            )
            children[name] = None if sep else leaf
    raw = bytearray()
    for name, leaf in sorted(
        children.items(), key=lambda item: item[0] + ("/" if item[1] is None else "")
    ):
        mode = "40000" if leaf is None else leaf["mode"]
        digest = (
            identity_tree(files, prefix + name + "/")
            if leaf is None
            else leaf["git_blob"]
        )
        raw.extend(mode.encode() + b" " + name.encode() + b"\0" + bytes.fromhex(digest))
    return hashlib.sha1(b"tree " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def file_observation(path, deadline, maximum=SOURCE_BYTES_LIMIT):
    path = Path(path)
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode), f"nonregular identity file: {path}")
    require(
        before.st_size <= maximum,
        f"identity file exceeds byte bound: {path}: {before.st_size} > {maximum}",
    )
    sha, git = (
        hashlib.sha256(),
        hashlib.sha1(b"blob " + str(before.st_size).encode() + b"\0"),
    )
    count = 0
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        while True:
            identity_remaining(deadline)
            raw = stream.read(min(1024 * 1024, maximum - count + 1))
            if not raw:
                break
            count += len(raw)
            require(count <= maximum, "file grew beyond bound")
            sha.update(raw)
            git.update(raw)
        finished = os.fstat(stream.fileno())
    after = path.lstat()
    fields = lambda value: (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )
    require(
        fields(before) == fields(opened) == fields(finished) == fields(after)
        and count == before.st_size,
        "file changed during identity read",
    )
    return {
        "bytes": count,
        "sha256": sha.hexdigest(),
        "git_blob": git.hexdigest(),
        "physical": list(fields(before)),
    }


def physical_source(root, files, deadline):
    result, errors = {}, []
    for relative, expected in sorted(files.items()):
        try:
            identity_remaining(deadline)
            path = root / safe_relative(relative)
            parent = path.parent
            while parent != root:
                require(
                    parent.is_dir() and not parent.is_symlink(),
                    "symlink source ancestor",
                )
                parent = parent.parent
            require(
                root.is_dir() and not root.is_symlink(),
                "source root is not a regular directory",
            )
            if expected["mode"] == "120000":
                before = path.lstat()
                require(
                    stat.S_ISLNK(before.st_mode), "source symlink became another type"
                )
                raw = os.fsencode(os.readlink(path))
                after = path.lstat()
                require(
                    (before.st_ino, before.st_mtime_ns, before.st_ctime_ns)
                    == (after.st_ino, after.st_mtime_ns, after.st_ctime_ns),
                    "source symlink changed",
                )
                row = {
                    "bytes": len(raw),
                    "git_blob": git_blob(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "physical": [
                        before.st_dev,
                        before.st_ino,
                        before.st_mode,
                        before.st_size,
                        before.st_mtime_ns,
                        before.st_ctime_ns,
                    ],
                }
                mode = "120000"
            else:
                row = file_observation(path, deadline)
                mode = "100755" if row["physical"][2] & 0o111 else "100644"
            row["mode"] = mode
            require(
                {key: row[key] for key in expected} == expected,
                "source bytes or mode differ",
            )
            result[relative] = row
        except BaseException as error:
            errors.append({"path": relative, "error": repr(error)})
            if time.monotonic() >= deadline:
                break
    return {
        "files": result,
        "errors": errors,
        "complete": len(result) == len(files) and not errors,
        "tree": identity_tree(result)
        if len(result) == len(files) and not errors
        else None,
    }


def current_execution(manifest, root, output, deadline, stage):
    publication_binding(manifest)
    require(
        root == Path(os.environ["GITHUB_WORKSPACE"]).resolve(),
        "executed Hepta source root differs",
    )
    event, event_sha = read_json(Path(os.environ["GITHUB_EVENT_PATH"]), 8 * 1024 * 1024)
    require(
        event.get("repository", {}).get("full_name")
        == HEPTA_REPOSITORY
        == os.environ.get("GITHUB_REPOSITORY"),
        "provider repository differs",
    )
    run_text, attempt_text = (
        os.environ.get("GITHUB_RUN_ID", ""),
        os.environ.get("GITHUB_RUN_ATTEMPT", ""),
    )
    require(
        re.fullmatch(r"[1-9][0-9]*", run_text) is not None and attempt_text == "1",
        "only the original workflow attempt is admitted",
    )
    run_id, attempt = int(run_text), int(attempt_text)
    event_name, event_commit = (
        os.environ.get("GITHUB_EVENT_NAME"),
        os.environ.get("GITHUB_SHA"),
    )
    require(
        event_name in ("pull_request", "push")
        and HEX40.fullmatch(event_commit or "") is not None,
        "unsupported provider event",
    )
    if event_name == "pull_request":
        pr = event.get("pull_request", {})
        require(
            pr.get("head", {}).get("repo", {}).get("full_name") == HEPTA_REPOSITORY
            and pr.get("base", {}).get("repo", {}).get("full_name") == HEPTA_REPOSITORY,
            "fork or unrelated PR source is not this admitted candidate",
        )
        head, branch = pr["head"]["sha"], pr["head"]["ref"]
        require(
            pr.get("base", {}).get("sha") == HEPTA_PARENT["head"],
            "actual PR base is not the accepted parent",
        )
        pr_number = event.get("number")
        require(type(pr_number) is int and pr_number > 0, "provider PR number")
    else:
        head, branch, pr_number = (
            event.get("after"),
            event.get("ref", "").removeprefix("refs/heads/"),
            None,
        )
        require(
            head == event_commit and event.get("deleted") is False,
            "push source identity differs",
        )
    require(
        isinstance(head, str)
        and HEX40.fullmatch(head) is not None
        and os.environ.get("HEPTA_C2_SOURCE_HEAD") == head,
        "checkout source selector differs",
    )
    require(os.environ.get("GITHUB_JOB") == "sdks", "wrong reusable job")
    api = IdentityAPI(output, deadline)
    run = api.get(f"/actions/runs/{run_id}/attempts/{attempt}", "run")
    require(
        run.get("id") == run_id
        and run.get("run_attempt") == attempt
        and run.get("head_sha") == head
        and run.get("head_branch") == branch
        and run.get("event") == event_name,
        "provider original run identity differs",
    )
    # Aggregate state does not prove execution. The original SDK job and current
    # step must still be proved active below before this function returns identity.
    require(
        run.get("status") in ("queued", "in_progress")
        and run.get("conclusion") is None,
        "provider original run is terminal or has an unsupported state",
    )
    require(
        run.get("repository", {}).get("full_name") == HEPTA_REPOSITORY
        and run.get("path") == ".github/workflows/blocking-ci.yml",
        "actual reusable caller differs",
    )
    if pr_number is not None:
        prs = [
            item
            for item in run.get("pull_requests", [])
            if item.get("number") == pr_number
        ]
        require(
            len(prs) == 1
            and prs[0].get("head", {}).get("sha") == head
            and prs[0].get("base", {}).get("sha") == HEPTA_PARENT["head"],
            "run does not attest the original PR source/base",
        )
    jobs, total = [], None
    for page in range(1, 6):
        document = api.get(
            f"/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100&page={page}",
            f"jobs-{page}",
        )
        require(
            type(document.get("total_count")) is int
            and 0 < document["total_count"] <= 500,
            "job list cardinality",
        )
        require(
            total is None or total == document["total_count"],
            "job list changed during observation",
        )
        total = document["total_count"]
        rows = document.get("jobs")
        require(isinstance(rows, list) and len(rows) <= 100, "job page shape")
        jobs.extend(rows)
        if len(jobs) >= total:
            break
        require(len(rows) == 100, "incomplete job page")
    require(
        len(jobs) == total and len({row["id"] for row in jobs}) == total,
        "job coverage incomplete",
    )
    job = select_original_job(
        jobs, run_id, attempt, head, os.environ.get("RUNNER_NAME"), stage
    )
    commit = api.get("/git/commits/" + head, "source-commit")
    require(
        commit.get("sha") == head
        and [row["sha"] for row in commit.get("parents", [])] == [HEPTA_PARENT["head"]],
        "actual source head does not have the sole accepted parent",
    )
    tree = commit.get("tree", {}).get("sha")
    require(
        isinstance(tree, str) and HEX40.fullmatch(tree) is not None,
        "source tree identity",
    )
    if event_name == "pull_request":
        merge = api.get("/git/commits/" + event_commit, "actual-event-merge")
        require(
            merge.get("sha") == event_commit
            and merge.get("tree", {}).get("sha") == tree
            and [row["sha"] for row in merge.get("parents", [])]
            == [HEPTA_PARENT["head"], head],
            "event merge cannot be proved equivalent to this source checkout",
        )
    workflow_refs = [
        row
        for row in run.get("referenced_workflows", [])
        if row.get("path", "").startswith(
            HEPTA_REPOSITORY + "/.github/workflows/sdk.yml@"
        )
    ]
    require(
        len(workflow_refs) == 1
        and workflow_refs[0].get("sha") == event_commit
        and workflow_refs[0].get("path")
        == HEPTA_REPOSITORY + "/.github/workflows/sdk.yml@" + event_commit
        and os.environ.get("GITHUB_WORKFLOW_SHA") == workflow_refs[0]["sha"],
        "provider did not attest this exact reusable workflow definition",
    )
    head_path = root / ".git" / "HEAD"
    require(
        head_path.parent.is_dir() and not head_path.parent.is_symlink(),
        "ordinary original checkout required",
    )
    require(
        regular_bytes(head_path, 128) == (head + "\n").encode(),
        "actual detached checkout HEAD differs",
    )
    identity = {
        "repository": HEPTA_REPOSITORY,
        "run_id": run_id,
        "run_attempt": attempt,
        "job_id": job["id"],
        "job_name": job["name"],
        "runner_id": job["runner_id"],
        "runner_name": job["runner_name"],
        "event_name": event_name,
        "event_sha": event_commit,
        "source_head": head,
        "source_tree": tree,
        "source_parents": [HEPTA_PARENT["head"]],
        "parent": HEPTA_PARENT,
        "pr_number": pr_number,
        "workflow_id": run["workflow_id"],
        "workflow_definition_sha": workflow_refs[0]["sha"],
    }
    identity_json(
        output / "context.json",
        {
            "identity": identity,
            "event_file_sha256": event_sha,
            "actual_step": stage,
            "api_reads": api.rows,
            "origin_limit": "Provider records plus exact reviewed workflow; original run/job readback remains required.",
        },
    )
    return identity, api


def same_execution(expected, actual):
    require(
        isinstance(expected, dict) and expected == actual,
        "old run/attempt/job or source identity",
    )


def verified_source(manifest, root, output, deadline, stage, expected_files=None):
    context, api = current_execution(manifest, root, output, deadline, stage)
    if expected_files is None:
        files = source_map(
            api.get(
                "/git/trees/" + context["source_tree"] + "?recursive=1", "source-tree"
            ),
            context["source_tree"],
        )
        parent = source_map(
            api.get(
                "/git/trees/" + HEPTA_PARENT["tree"] + "?recursive=1", "parent-tree"
            ),
            HEPTA_PARENT["tree"],
        )
        changed = sorted(
            path
            for path in set(parent) | set(files)
            if parent.get(path) != files.get(path)
        )
        require(
            changed == list(HEPTA_CHANGED_PATHS)
            and all(
                files.get(path, {}).get("mode") == "100644"
                for path in HEPTA_CHANGED_PATHS
            ),
            "actual changed source roster is not the accepted exact4",
        )
    else:
        files = {
            path: {key: row[key] for key in ("bytes", "git_blob", "mode")}
            for path, row in expected_files.items()
        }
        require(
            identity_tree(files) == context["source_tree"],
            "retained source map is not this actual tree",
        )
    snapshot = physical_source(root, files, deadline)
    identity_json(output / "source.json", snapshot)
    require(
        snapshot["complete"] and snapshot["tree"] == context["source_tree"],
        "physical Hepta source differs",
    )
    require(
        globals().get("__hepta_compiled_sha256__")
        == snapshot["files"]["scripts/mcp_conformance/conformance_fixture.py"][
            "sha256"
        ],
        "executed identity module bytes differ from this physical candidate",
    )
    return context, snapshot


def binary_identity(path, deadline):
    resolved = Path(path).resolve(strict=True)
    row = file_observation(resolved, deadline, maximum=BINARY_BYTES_LIMIT)
    require(bool(row["physical"][2] & 0o111), "built binary is not executable")
    return {"path": str(Path(path).absolute()), "resolved": str(resolved), **row}


def compare_build_binaries(original, staged):
    require(
        set(original) == set(staged) == {"codex", "code_mode_host"},
        "exact build outputs",
    )
    for name in original:
        require(
            (original[name]["bytes"], original[name]["sha256"])
            == (staged[name]["bytes"], staged[name]["sha256"]),
            "staged binary differs from original build",
        )


def current_staged_binaries(root, deadline):
    directory = root / ".tmp" / "sdk-ci"
    require(
        directory.parent.is_dir()
        and not directory.parent.is_symlink()
        and directory.is_dir()
        and not directory.is_symlink(),
        "SDK staging directory is a symlink",
    )
    require(
        all(
            (directory / name).is_file() and not (directory / name).is_symlink()
            for name in ("codex", "codex-code-mode-host")
        ),
        "staged executable is not a regular file",
    )
    return {
        "codex": binary_identity(directory / "codex", deadline),
        "code_mode_host": binary_identity(directory / "codex-code-mode-host", deadline),
    }


def select_original_job(jobs, run_id, attempt, head, runner_name, stage):
    candidates = [
        row
        for row in jobs
        if row.get("name") == "sdk / sdks"
        and row.get("runner_name") == runner_name
        and row.get("status") == "in_progress"
        and row.get("conclusion") is None
    ]
    require(len(candidates) == 1, "current original SDK job is absent or ambiguous")
    job = candidates[0]
    require(
        type(job.get("id")) is int
        and job["id"] > 0
        and job.get("run_id") == run_id
        and job.get("run_attempt") == attempt
        and job.get("head_sha") == head
        and type(job.get("runner_id")) is int
        and job["runner_id"] > 0,
        "provider job identity differs",
    )
    selected = [row for row in job.get("steps", []) if row.get("name") == stage]
    require(
        len(selected) == 1
        and selected[0].get("status") == "in_progress"
        and selected[0].get("conclusion") is None,
        "actual current SDK step differs",
    )
    required_prior = [] if stage == BUILD_STEP else [BUILD_STEP]
    if stage == TEST_STEP:
        required_prior.append(FIXTURE_STEP)
    for prior in required_prior:
        rows = [row for row in job["steps"] if row.get("name") == prior]
        require(
            len(rows) == 1
            and rows[0].get("status") == "completed"
            and rows[0].get("conclusion") == "success",
            "original prerequisite step did not succeed",
        )
    return job


def inspect_original_build(
    build_receipt_path, manifest, root, output, deadline, stage, codex_path=None
):
    build, build_sha = read_json(build_receipt_path, 32 * 1024 * 1024)
    require(
        build.get("schema") == "hepta-sdk-original-build-v1"
        and build.get("status") == "pending-original-step-terminal",
        "original build provenance is absent",
    )
    require(
        build.get("build_step") == BUILD_STEP
        and build.get("original_build_exit_code") == 0,
        "original Bazel build did not reach its successful staging boundary",
    )
    before, after = build.get("source_before"), build.get("source_after")
    require(
        isinstance(before, dict) and before.get("complete") is True and after == before,
        "original build source changed or was incomplete",
    )
    context, source = verified_source(
        manifest, root, output, deadline, stage, before["files"]
    )
    same_execution(build.get("identity_before"), context)
    same_execution(build.get("identity_after"), context)
    require(source == before, "original source changed since build")
    staged = current_staged_binaries(root, deadline)
    require(
        staged == build.get("staged_binaries"),
        "current staged binary differs from this original build",
    )
    compare_build_binaries(build.get("original_binaries", {}), staged)
    if codex_path is not None:
        require(
            str(codex_path.resolve(strict=True)) == staged["codex"]["resolved"],
            "supplied Codex binary is not this original staged artifact",
        )
    return {
        "path": str(build_receipt_path.resolve()),
        "sha256": build_sha,
        "identity": context,
        "source_tree": source["tree"],
        "binaries": staged,
    }


def finish_identity_boundary(path, record, deadline, original):
    record["completed_monotonic_before_final_io"] = time.monotonic()
    record["terminal_scope"] = (
        "Provisional before final IO; the original workflow step must independently succeed."
    )
    try:
        identity_json(path, record)
        identity_remaining(deadline)
    except BaseException as error:
        if original is None:
            raise
        original.add_note("identity boundary retention/deadline failed: " + repr(error))


def observe_fixture_use(
    receipt_path, manifest, receipt, source_identity, codex_path, phase
):
    require(
        phase
        in (
            "before-conformance",
            "after-conformance",
            "before-reviewer",
            "after-reviewer",
        ),
        "unknown original SDK consumption boundary",
    )
    deadline = time.monotonic() + 20
    root = Path(__file__).resolve().parents[2]
    observations = receipt_path.parent / "identity-observations"
    observations.mkdir(exist_ok=True)
    require(
        not observations.is_symlink(), "identity observation directory is a symlink"
    )
    output = Path(tempfile.mkdtemp(prefix=phase + "-", dir=observations))
    record = {
        "schema": "hepta-c2-consumption-identity-v1",
        "phase": phase,
        "status": "failed",
    }
    original = None
    try:
        reference = receipt.get("original_build")
        require(
            isinstance(reference, dict), "fixture does not bind an original SDK build"
        )
        build_path = Path(reference["path"])
        origin = inspect_original_build(
            build_path, manifest, root, output, deadline, TEST_STEP, codex_path
        )
        require(
            reference == origin,
            "fixture belongs to another build, binary, run, attempt or job",
        )
        actual_source = {
            "commit": origin["identity"]["source_head"],
            "tree": origin["source_tree"],
            "parents": origin["identity"]["source_parents"],
            "dirty": False,
        }
        require(
            source_identity is None or source_identity == actual_source,
            "raw checkout commit differs",
        )
        require(
            receipt.get("source_before")
            == actual_source
            == receipt.get("source_after"),
            "fixture source differs from the current authenticated source",
        )
        record.update(status="observed", original_build=origin)
        return origin, actual_source
    except BaseException as error:
        original = error
        record["error"] = repr(error)
        raise
    finally:
        finish_identity_boundary(output / "RESULT.json", record, deadline, original)


def record_sdk_build_boundary(output, manifest_path, root, originals=None):
    deadline = time.monotonic() + 20
    if originals is None:
        require(
            not output.exists() and not output.is_relative_to(root),
            "fresh original-build directory required",
        )
        output.mkdir(parents=True, mode=0o700)
    require(
        output.is_dir() and not output.is_symlink(),
        "original-build directory is invalid",
    )
    phase = "before" if originals is None else "after"
    observation = output / phase
    observation.mkdir(mode=0o700)
    record = {
        "schema": "hepta-sdk-original-build-boundary-v1",
        "phase": phase,
        "status": "failed",
    }
    original = None
    try:
        manifest, manifest_sha = load_manifest(manifest_path)
        record["manifest_sha256"] = manifest_sha
        first = (
            None
            if originals is None
            else read_json(output / "before" / "RESULT.json", 32 * 1024 * 1024)[0]
        )
        expected = None if first is None else first["source"]["files"]
        context, source = verified_source(
            manifest, root, observation, deadline, BUILD_STEP, expected
        )
        if first is not None:
            require(
                first.get("status") == "observed",
                "original pre-build boundary was not successful",
            )
            same_execution(first["identity"], context)
            require(
                source == first["source"],
                "source changed across the original Bazel build",
            )
            before_binaries = {
                name: binary_identity(path, deadline)
                for name, path in originals.items()
            }
            staged = current_staged_binaries(root, deadline)
            compare_build_binaries(before_binaries, staged)
            build = {
                "schema": "hepta-sdk-original-build-v1",
                "status": "pending-original-step-terminal",
                "build_step": BUILD_STEP,
                "original_build_exit_code": 0,
                "identity_before": first["identity"],
                "identity_after": context,
                "source_before": first["source"],
                "source_after": source,
                "original_binaries": before_binaries,
                "staged_binaries": staged,
                "source_origin": "Original reviewed Bazel step; consumption also requires provider step success.",
            }
            identity_json(output / "RESULT.json", build)
        record.update(status="observed", identity=context, source=source)
    except BaseException as error:
        original = error
        record["error"] = repr(error)
        raise
    finally:
        finish_identity_boundary(
            observation / "RESULT.json", record, deadline, original
        )
