#!/usr/bin/env python3
"""One explicitly admitted fresh Windows credential candidate: cold build/list/nine.

Exact original source/handles, shared2400/2100/300 clock and no old167 replay.
This source is inactive until independent Root publication, account and budget
admission. A result remains provisional until original platform/host review.
"""

import ctypes
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import struct
import sys
import time
import types
import urllib.error
import urllib.parse
import urllib.request

REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
PARENT_HEAD = "dd1c9b529c44a2efd54ee1b35b0c6e24b398ce87"
PARENT_TREE = "4c744183c696313dbb781d223071893324b184f7"
BASE_BRANCH = "fix/hepta-windows-credentials-owned-nine-20261127-7c9e"
HEAD_BRANCH = "fix/hepta-windows-credentials-cross-drive-20261127-7c9e"
WORKFLOW = ".github/workflows/hepta-windows-current-ci.yml"
CALLER_PATH = "scripts/run_hepta_windows_credentials_nine_v1.py"
COLLECTOR_PATH = "scripts/hepta_windows_credentials_nine_collector_v1.py"
INPUT_PATH = "scripts/hepta_windows_credentials_nine_inputs_v1.json"
LIFECYCLE_PATH = "scripts/hepta_windows_credential_lifecycle_v1.py"
OWNER_PATH = "scripts/hepta_windows_credential_native_owner_v1.py"
CONTROL_PATH = "scripts/hepta_windows_credentials_cross_drive_controls_v1.py"
CANDIDATE_PATHS = [
    ".github/fixtures/windows-current-ci-scope.json",
    ".github/workflows/hepta-windows-current-ci.yml",
    "codex-rs/windows-sandbox-rs/src/acl.rs",
    "codex-rs/windows-sandbox-rs/src/bin/command_runner/win.rs",
    "codex-rs/windows-sandbox-rs/src/bin/setup_main/win.rs",
    "codex-rs/windows-sandbox-rs/src/bin/setup_main/win/sandbox_users.rs",
    "codex-rs/windows-sandbox-rs/src/cap.rs",
    "codex-rs/windows-sandbox-rs/src/credential_store.rs",
    "codex-rs/windows-sandbox-rs/src/delete_permission_matrix_tests.rs",
    "codex-rs/windows-sandbox-rs/src/desktop.rs",
    "codex-rs/windows-sandbox-rs/src/elevated/runner_client.rs",
    "codex-rs/windows-sandbox-rs/src/elevated_impl.rs",
    "codex-rs/windows-sandbox-rs/src/hosted_credential_lifetime.rs",
    "codex-rs/windows-sandbox-rs/src/identity.rs",
    "codex-rs/windows-sandbox-rs/src/lib.rs",
    "codex-rs/windows-sandbox-rs/src/setup.rs",
    "codex-rs/windows-sandbox-rs/src/setup_error.rs",
    "codex-rs/windows-sandbox-rs/src/spawn_prep.rs",
    "codex-rs/windows-sandbox-rs/src/token.rs",
    "codex-rs/windows-sandbox-rs/src/token_tests.rs",
    "codex-rs/windows-sandbox-rs/src/unified_exec/acl_setup_tests.rs",
    "codex-rs/windows-sandbox-rs/src/unified_exec/delete_permission_tests.rs",
    "codex-rs/windows-sandbox-rs/src/unified_exec/tests.rs",
    "scripts/hepta_windows_credential_lifecycle_v1.py",
    "scripts/hepta_windows_credential_native_owner_v1.py",
    "scripts/hepta_windows_credentials_nine_collector_v1.py",
    "scripts/hepta_windows_credentials_nine_inputs_v1.json",
    "scripts/run_hepta_windows_credentials_nine_v1.py",
    CONTROL_PATH,
]
CHANGED_PATHS = [WORKFLOW, COLLECTOR_PATH, CONTROL_PATH, INPUT_PATH, CALLER_PATH]
ADDED_PATHS = [CONTROL_PATH]
FORMATTED24 = [
    {
        "repo_path": ".github/fixtures/windows-current-ci-scope.json",
        "bytes": 31543,
        "sha256": "5443e2825a21fb239900ce833f9736ad592abeaa26b960a1b440c0ad87d5a5c4",
        "git_blob": "25560adf7beaa353cbc88c18f5d90ba4f586020e",
    },
    {
        "repo_path": "codex-rs/windows-sandbox-rs/src/acl.rs",
        "bytes": 29888,
        "sha256": "6bd7f019dac7cf5ccca4c61611663867fbafd3104916a6c24cff4a20d5f7228f",
        "git_blob": "7f82f9c0afbc9aacb00ec3ecd870df08e33a29c4",
    },
    {
        "repo_path": "codex-rs/windows-sandbox-rs/src/bin/command_runner/win.rs",
        "bytes": 36980,
        "sha256": "02242af7f9c1d3ceab8d8ecb10fccc54d264c2ffce497474db2c60c698c7e902",
        "git_blob": "c4a14883022d707c16457ad67b91fd0b7570b2ed",
    },
    {
        "repo_path": "codex-rs/windows-sandbox-rs/src/bin/setup_main/win.rs",
        "bytes": 46970,
        "sha256": "b73013593cb619adc347db7c5de9ad4a014dede5d00038cf432b0152dc78df1e",
        "git_blob": "5fff5fb2c21abfd69378c8c7324220f6dc8aff5b",
    },
    {
        "repo_path": "codex-rs/windows-sandbox-rs/src/bin/setup_main/win/sandbox_users.rs",
        "bytes": 22747,
        "sha256": "f1afee1a9442819c6af3386ec80aa4cbb599dc980ae569dd64b51f3e203f4a56",
        "git_blob": "8bf4616eccd795211b5207e5efa6bb50d9c9c9a6",
    },
    {
        "repo_path": "codex-rs/windows-sandbox-rs/src/cap.rs",
        "bytes": 9609,
        "sha256": "f2be7e0486558d3b73a30da2573b745b62c0f3baf2f1cc17a2261ab494c75bbe",
        "git_blob": "84d03085bf8f6c0600cccd2d32a1b6486cbf69f5",
    },
    {
        "repo_path": "codex-rs/windows-sandbox-rs/src/credential_store.rs",
        "bytes": 43054,
        "sha256": "2ddc7f095180aa5a2d789378d3d02533b8e4e523c4e9b711d7211bdc07ee16c5",
        "git_blob": "97b17a81c476501b135450575cde424131751961",
    },
    {
        "repo_path": "codex-rs/windows-sandbox-rs/src/delete_permission_matrix_tests.rs",
        "bytes": 17861,
        "sha256": "efd82765e2c0c9c1c56e1993e014ac92d424ed8c3b4f677ec69267f8806c6b61",
        "git_blob": "b344c4abae9ae8066e7880a1f64f720aa40f8979",
    },
    {
        "repo_path": "codex-rs/windows-sandbox-rs/src/desktop.rs",
        "bytes": 11248,
        "sha256": "ad0a4207a4d98c841ba1657c5c552586f853fb8bdd92d7e8067a1c5f2d62fb50",
        "git_blob": "b4cbe3ec836e1ede92eb4e2174d004654a1d1736",
    },
    {
        "repo_path": "codex-rs/windows-sandbox-rs/src/elevated/runner_client.rs",
        "bytes": 27089,
        "sha256": "bf4bc85cc3d3900cfbf8197a5e548d55fbc8f439f4bf31f9a9fad77f69e88dbc",
        "git_blob": "3456424a03cf43aeb1a0ca2bb9d028f44428b04e",
    },
    {
        "repo_path": "codex-rs/windows-sandbox-rs/src/elevated_impl.rs",
        "bytes": 10428,
        "sha256": "60a0afd3e356e481ddf1022f38371f23a10d138d398b86495712483d213712bd",
        "git_blob": "b4925c4ccd56295c6d1887f8ab6950fe65dca977",
    },
    {
        "repo_path": "codex-rs/windows-sandbox-rs/src/hosted_credential_lifetime.rs",
        "bytes": 42839,
        "sha256": "14839896d336cb6b2f6277601fa07ab1defd7dfa86216d6039e858fdbe59e169",
        "git_blob": "cfb958e51eabde9eeb8d38e1290a4d71bb3fc9fd",
    },
    {
        "repo_path": "codex-rs/windows-sandbox-rs/src/identity.rs",
        "bytes": 14671,
        "sha256": "61d3b6c0ec57c80265d3549515ed76a15b13fa3637154bf11d7a0d31910ad05c",
        "git_blob": "af867b875b600f685ffbc5ea5e43082a463fa41f",
    },
    {
        "repo_path": "codex-rs/windows-sandbox-rs/src/lib.rs",
        "bytes": 32092,
        "sha256": "299ffe7f52eb6a76b5dcc3a8ca4e8a221da6ac431415cca3202e990a6b1239ae",
        "git_blob": "325a59adb168d1efca00cf35ce2115bdfdbc0a7f",
    },
    {
        "repo_path": "codex-rs/windows-sandbox-rs/src/setup.rs",
        "bytes": 87286,
        "sha256": "6ed88b2a7b23cd7019107016d3e35613cf84ddfadb1f4e825d9214594dbd45be",
        "git_blob": "9e4475da08bb3bd8b6fc7a3f630f844fad0e0e84",
    },
    {
        "repo_path": "codex-rs/windows-sandbox-rs/src/setup_error.rs",
        "bytes": 12650,
        "sha256": "73463922af55591e4b9540ad26bf8684c1971c2a3825b0b4d2155bec5a86eb90",
        "git_blob": "5e0114000e52823e58621194ece87c6340cc1833",
    },
    {
        "repo_path": "codex-rs/windows-sandbox-rs/src/spawn_prep.rs",
        "bytes": 26944,
        "sha256": "d6d15d8bba94b71bd35015661c3a047b2735f9c1d1f513bf8de4c392cf4d4e6c",
        "git_blob": "b4704f6c84119eaca320c7141b3cdf8ab09bf21a",
    },
    {
        "repo_path": "codex-rs/windows-sandbox-rs/src/token.rs",
        "bytes": 21338,
        "sha256": "21fb7da41e02f81e97613bfdc57bfaf0ea725ca973ebf406b7c90d3222bc1b79",
        "git_blob": "610efb9a4261c6a025000df6afe853c20f12166e",
    },
    {
        "repo_path": "codex-rs/windows-sandbox-rs/src/token_tests.rs",
        "bytes": 29399,
        "sha256": "b2f6bbcdbfdc9a74ef98d7570e7745bbd54feed0331b33d047cdfce360866850",
        "git_blob": "94c36df494bcb59dbba85ab78fedcee2b5351e36",
    },
    {
        "repo_path": "codex-rs/windows-sandbox-rs/src/unified_exec/acl_setup_tests.rs",
        "bytes": 20647,
        "sha256": "f5fe083337ee501b9934b6f8fce8d693f78e037978c52c42da1f37d371b1e10a",
        "git_blob": "4854358d913ef4a2fbfcd42e1289c6da8b6867cc",
    },
    {
        "repo_path": "codex-rs/windows-sandbox-rs/src/unified_exec/delete_permission_tests.rs",
        "bytes": 7950,
        "sha256": "43e061875c91cba34e31ea8276d3623358128c66934ef08df8f59a356c33b0f8",
        "git_blob": "32207bc7e67fce70d4782028275f69bcb29ff274",
    },
    {
        "repo_path": "codex-rs/windows-sandbox-rs/src/unified_exec/tests.rs",
        "bytes": 48784,
        "sha256": "026b17e1abec64a9dd40ed182a957d155da1037a062bb3d4abd7a0d304361ae5",
        "git_blob": "347d53ee180c8a04196a1b52d797e5991b5603f1",
    },
    {
        "repo_path": "scripts/hepta_windows_credential_lifecycle_v1.py",
        "bytes": 70490,
        "sha256": "3d58f4b6c0ccfd61c5e21b18babc54b695a237888654c3bf7e81ab6bebf90121",
        "git_blob": "dd8c8186b5c1914ba51adc9754e7c50a8835ec13",
    },
    {
        "repo_path": "scripts/hepta_windows_credential_native_owner_v1.py",
        "bytes": 53604,
        "sha256": "be255914609d2b8b420357af6992c494b08523109616bb9e5d7d5436c9971be5",
        "git_blob": "6d75fc28d3f5a52e949bcb02ed6179e32b07a8a5",
    },
]
EXACT_TESTS = [
    "token::tests::workspace_capabilities_deny_writes_and_deletes_under_broad_identity_aces",
    "unified_exec::tests::acl_setup_tests::elevated_capture_rejects_deny_acl_setup_failure_before_spawn",
    "unified_exec::tests::acl_setup_tests::elevated_session_rejects_deny_acl_setup_failure_before_spawn",
    "unified_exec::tests::elevated_non_tty_cmd_forwards_env_output_and_exit",
    "unified_exec::tests::elevated_non_tty_cmd_emits_output",
    "unified_exec::tests::elevated_non_tty_cmd_enforces_deny_read_overrides",
    "unified_exec::tests::elevated_workspace_write_delete_is_limited_to_writable_roots",
    "token::tests::workspace_capability_delete_routes_require_the_capability_in_all_four_cells",
    "unified_exec::tests::delete_permission_tests::elevated_delete_routes_require_workspace_capability_in_all_four_cells",
]
UNIT_INVENTORY_ONLY = [
    "identity::tests::failed_login_revalidation_preserves_existing_credential_bytes",
    "identity::tests::failed_login_revalidation_does_not_create_missing_credentials",
    "elevated::runner_client::tests::rejected_revalidation_keeps_initial_native_failure_and_never_spawns_again",
    "elevated::runner_client::tests::failed_single_retry_keeps_both_native_failures_without_third_attempt",
]
PHASES = [
    "01-rustc-identity",
    "02-cargo-identity",
    "03-locked-metadata",
    "04-cold-helpers",
    "05-cold-library",
    "06-complete-list",
    "07-ignored-list",
]
BUDGET = {
    "whole_seconds": 2400,
    "work_seconds": 2100,
    "retention_seconds": 300,
    "platform_upload_reserve_seconds": 60,
    "tool_identity_shared_seconds": 20,
    "locked_metadata_seconds": 60,
    "shared_cold_build_seconds": 1400,
    "complete_inventory_seconds": 90,
    "nine_case_shared_seconds": 540,
    "case_seconds": [60, 60, 60, 60, 60, 60, 60, 60, 60],
}
HISTORY = {
    "original7164": {
        "head": "1b2ae899a8956ee96201956bced828f0824ea5f3",
        "run_id": 45933361561,
        "run_attempt": 1,
        "job_id": 140290838427,
        "status": "FAIL",
        "whole_seconds": 3584,
        "groups": 19,
        "expected": 167,
        "selected": 165,
        "passed": 158,
        "failed": 7,
        "missing": 2,
        "helper_seconds_nested": 655.25,
        "group_seconds_nested": 2877.281,
        "reset_or_refund": False,
        "replayed_here": False,
    },
    "original7176": {
        "run_id": 45953835760,
        "job_id": 140355614176,
        "status": "FAIL",
        "whole_seconds": 65,
        "commands": 0,
        "phase_attempts": 0,
        "cause": "KeyError('RUSTUP_HOME')",
        "source_lineage_not_automatically_adopted": True,
        "replayed_here": False,
    },
    "original7186": {
        "head": "dd1c9b529c44a2efd54ee1b35b0c6e24b398ce87",
        "tree": "4c744183c696313dbb781d223071893324b184f7",
        "run_id": 45992607643,
        "run_attempt": 1,
        "job_id": 140483967919,
        "status": "FAIL",
        "whole_seconds": 51,
        "commands": 2,
        "phase_attempts": 2,
        "native_cases": 0,
        "cause": 'ValueError("Paths don\'t have the same drive")',
        "original_result_sha256": "7530fb08f62e24cc5321155ecb2e7289b316c78d31aaed40415c674169dac98c",
        "Root_archive_authentication_sha256": "b3ad40a965b8a0572b2e99c7f9c6deadf7ba852abdc0fe477d786ee4498a26ff",
        "reset_or_refund": False,
        "prior_result_reused_as_pass": False,
        "same_candidate_replayed": False,
    },
    "frozen_E1_E6_transferred_seconds": 0,
    "Setup7_scope_transferred_seconds": 0,
}
EPHEMERAL_POLICY = {
    "runner_environment": "github-hosted",
    "runs_on": "windows-2025",
    "platform_original_attempt": 1,
    "fresh_fixed_accounts_required": True,
    "account_names": ["CodexSandboxOffline", "CodexSandboxOnline"],
    "one_owned_credential_home_per_scope": True,
    "per_case_native_lease_required": True,
    "account_password_rotation_or_automatic_deletion": False,
    "host_disposal_requires_original_provider_review": True,
    "persistent_or_self_hosted_runner_allowed": False,
    "shared_multi_home_production_isolation_qualified": False,
}
WHOLE_SECONDS = 2400
WORK_SECONDS = 2100
RETENTION_DEADLINE_SECONDS = 2340
LINK_PATH = "codex-rs/vendor/bubblewrap/LICENSE"
LINK_BLOB = "d24842f3cdcf2e447f9a7a26fa387ad63f5c4b91"
SOURCE_LIMIT = 768 * 1024 * 1024
FILE_LIMIT = 256 * 1024 * 1024
TOOLCHAIN_BYTES = 4 * 1024 * 1024 * 1024
TOOLCHAIN_FILES = 50000
DEPENDENCY_BYTES = 4 * 1024 * 1024 * 1024
DEPENDENCY_FILES = 200000


def need(value, message):
    if not value:
        raise RuntimeError(message)


def duplicate_free(pairs):
    value = {}
    for key, item in pairs:
        need(key not in value, "duplicate JSON key: " + key)
        value[key] = item
    return value


def parse(raw):
    return json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=duplicate_free,
        parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
    )


def digest(raw):
    return {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "git_blob": hashlib.sha1(
            b"blob " + str(len(raw)).encode() + b"\0" + raw
        ).hexdigest(),
    }


def durable(path, raw):
    with open(path, "xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {**digest(raw), "path": str(path)}


def json_file(path, value):
    return durable(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())


def read_bound(path, limit):
    with open(path, "rb") as stream:
        raw = stream.read(limit + 1)
    need(len(raw) <= limit, "original file byte bound: " + str(path))
    return raw


def source_module(name, path, expected):
    raw = read_bound(path, 128 * 1024)
    need(digest(raw)["sha256"] == expected, "source loader hash mismatch: " + str(path))
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = ""
    sys.modules[name] = module
    try:
        exec(compile(raw, str(path), "exec"), module.__dict__)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module, raw


def utc(value):
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def tree_map(value):
    need(value.get("truncated") is False, "truncated original Git tree")
    entries = value.get("tree")
    need(isinstance(entries, list) and len(entries) < 40000, "Git tree entry bound")
    leaves, directories, seen = {}, {}, set()
    for entry in entries:
        path = entry["path"]
        need(
            isinstance(path, str)
            and path
            and "\\" not in path
            and not path.startswith("/")
            and all(p not in ("", ".", "..") for p in path.split("/")),
            "unsafe original Git path",
        )
        need(path not in seen, "duplicate Git tree path")
        seen.add(path)
        if entry["type"] == "tree":
            directories[path] = entry["sha"]
        else:
            need(
                entry["type"] == "blob"
                and entry["mode"] in ("100644", "100755", "120000"),
                "submodule or unsupported tree leaf",
            )
            need(
                isinstance(entry.get("size"), int) and 0 <= entry["size"] <= FILE_LIMIT,
                "Git blob size bound",
            )
            need(re.fullmatch("[0-9a-f]{40}", entry["sha"]), "Git blob identity")
            leaves[path] = {
                "mode": entry["mode"],
                "git_blob": entry["sha"],
                "bytes": entry["size"],
            }
    need(
        len({p.casefold() for p in leaves}) == len(leaves),
        "Windows case-colliding tracked paths",
    )
    need(
        sum(v["bytes"] for v in leaves.values()) <= SOURCE_LIMIT,
        "full source byte bound",
    )
    # Reconstruct native Git trees from all leaves, then check every API tree.
    nested = {}
    for path, entry in leaves.items():
        pieces = path.split("/")
        node = nested
        for piece in pieces[:-1]:
            child = node.setdefault(piece, {})
            need(isinstance(child, dict), "file/directory prefix collision")
            node = child
        need(pieces[-1] not in node, "Git leaf collision")
        node[pieces[-1]] = (entry["mode"], entry["git_blob"])

    def merkle(node, prefix):
        items = []
        for name, child in node.items():
            if isinstance(child, dict):
                sha = merkle(child, prefix + name + "/")
                items.append((name.encode("utf-8") + b"/", "40000", name, sha))
            else:
                mode, sha = child
                items.append((name.encode("utf-8"), mode, name, sha))
        data = b"".join(
            mode.encode() + b" " + name.encode("utf-8") + b"\0" + bytes.fromhex(sha)
            for _, mode, name, sha in sorted(items)
        )
        sha = hashlib.sha1(
            b"tree " + str(len(data)).encode() + b"\0" + data
        ).hexdigest()
        if prefix:
            need(
                directories.get(prefix[:-1]) == sha,
                "API subtree Merkle mismatch: " + prefix,
            )
        return sha

    need(merkle(nested, "") == value["sha"], "full source tree Merkle mismatch")
    return leaves


class Api:
    def __init__(self, output, token, deadline):
        self.output = output
        self.token = token
        self.deadline = deadline
        self.reads = []

    def get(self, suffix, label):
        need(
            suffix not in [item["suffix"] for item in self.reads],
            "duplicate original API read",
        )
        need(time.monotonic() < self.deadline, "original preparation deadline")
        need(re.fullmatch("[A-Za-z0-9_.-]+", label), "unsafe API observation label")
        request_url = "https://api.github.com/repos/" + REPOSITORY + "/" + suffix
        row = {
            "suffix": suffix,
            "label": label,
            "attempts": 1,
            "status": "UNKNOWN",
            "request_url": request_url,
            "received_bytes": 0,
            "retained_bytes": 0,
            "body_complete": False,
            "body_truncated": False,
            "retention_errors": [],
        }
        self.reads.append(row)
        request = urllib.request.Request(
            request_url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": "Bearer " + self.token,
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "hepta-setup7-original-read-v1",
            },
        )
        chunks = []
        original_error = None

        def capture_headers(response):
            # Preserve the original status and available headers before any body IO.
            row["status"] = response.getcode()
            row["response_url"] = response.geturl()
            row["headers"] = {
                key: response.headers.get(key)
                for key in ("Date", "ETag", "X-GitHub-Request-Id", "Link")
            }

        def keep_delivered(block, limit):
            row["received_bytes"] += len(block)
            remaining = max(0, limit - row["retained_bytes"])
            kept = block[:remaining]
            if kept:
                chunks.append(kept)
                row["retained_bytes"] += len(kept)
            overflow = block[len(kept) :]
            if overflow:
                row["body_truncated"] = True
                row["unretained_overflow_bytes"] = (
                    row["received_bytes"] - row["retained_bytes"]
                )
                # Normal reads request at most one byte beyond the original cap.
                # Keep that probe, without presenting it as a complete body.
                row["overflow_probe_hex"] = overflow[:1].hex()
                row["overflow_block_sha256"] = hashlib.sha256(overflow).hexdigest()

        def read_body(response, limit):
            row["body_limit_bytes"] = limit
            while True:
                need(time.monotonic() < self.deadline, "original API read deadline")
                wanted = min(65536, limit - row["retained_bytes"] + 1)
                try:
                    block = response.read(wanted)
                except BaseException as read_error:
                    row["body_read_error"] = repr(read_error)
                    partial = getattr(read_error, "partial", None)
                    if isinstance(partial, bytes) and partial:
                        keep_delivered(partial, limit)
                    raise
                if not block:
                    row["body_complete"] = True
                    return b"".join(chunks)
                keep_delivered(block, limit)
                need(not row["body_truncated"], "original API response byte bound")

        try:
            with urllib.request.urlopen(
                request, timeout=max(0.1, min(10, self.deadline - time.monotonic()))
            ) as response:
                capture_headers(response)
                need(row["status"] == 200, "original GitHub GET was not 200")
                need(
                    row["response_url"].startswith(
                        "https://api.github.com/repos/" + REPOSITORY + "/"
                    ),
                    "API redirect outside the bound repository",
                )
                raw = read_body(response, 12 * 1024 * 1024)
                need(
                    not response.headers.get("Link"),
                    "unconsumed original API pagination",
                )
            row["raw"] = durable(self.output / (label + ".raw.json"), raw)
            # Raw original is durable before interpretation.
            return parse(raw)
        except BaseException as error:
            original_error = error
            row["error"] = repr(error)
            if isinstance(error, urllib.error.HTTPError):
                try:
                    with error:
                        capture_headers(error)
                        read_body(error, 1024 * 1024)
                except BaseException as body_error:
                    row["http_error_body_error"] = repr(body_error)
                row["error_body_truncated"] = row["body_truncated"]
            if "raw" not in row:
                try:
                    row["raw"] = durable(
                        self.output / (label + ".partial.raw"), b"".join(chunks)
                    )
                except BaseException as retention_error:
                    row["retention_errors"].append("body: " + repr(retention_error))
            raise
        finally:
            try:
                json_file(self.output / (label + ".read.json"), row)
            except BaseException as retention_error:
                row["retention_errors"].append("read record: " + repr(retention_error))
                # The live row is also attached to the main RESULT. Do not replace
                # the original request/read exception with its retention failure.
                if original_error is None:
                    raise


def enumerate_files(root, allowed_generated=()):
    result = set()
    for parent, dirs, files in os.walk(root, topdown=True, followlinks=False):
        parent_path = Path(parent)
        if parent_path == root and ".git" in dirs:
            dirs.remove(".git")
        for name in dirs:
            path = parent_path / name
            need(
                not path.is_symlink() and not path.is_junction(),
                "untracked reparse directory",
            )
        for name in files:
            path = parent_path / name
            relative = path.relative_to(root).as_posix()
            if relative not in allowed_generated:
                result.add(relative)
    return result


def retain_tree(
    owner,
    api,
    cancellation,
    root,
    held,
    generated,
    ledger,
    *,
    deadline,
    byte_cap,
    file_cap,
    skip_git=False,
):
    """Hold exact original physical inputs before build; no executable is imported."""
    root = Path(root).absolute()
    need(
        root.is_dir() and not root.is_symlink() and not root.is_junction(),
        "materialized input directory is not an ordinary original object",
    )
    directory_paths, file_paths = [], []
    for parent, dirs, files in os.walk(root, topdown=True, followlinks=False):
        cancellation.check()
        need(time.monotonic() < deadline, "materialized input enumeration deadline")
        current = Path(parent)
        directory_paths.append(current)
        if skip_git and current == root and ".git" in dirs:
            dirs.remove(".git")
        for name in dirs:
            child = current / name
            need(
                not child.is_symlink() and not child.is_junction(),
                "materialized input has a reparse directory",
            )
        for name in files:
            path = current / name
            need(
                not path.is_symlink() and not path.is_junction(),
                "materialized input has a reparse file",
            )
            file_paths.append(path)
            need(len(file_paths) <= file_cap, "materialized input file count bound")
    need(file_paths, "materialized input tree is empty")
    for path in sorted(directory_paths, key=lambda item: (len(item.parts), str(item))):
        cancellation.check()
        need(time.monotonic() < deadline, "materialized directory custody deadline")
        held.append(owner.PinnedFile(api, path, 0, directory=True))
    rows, used = [], 0
    for path in sorted(file_paths, key=str):
        cancellation.check()
        need(time.monotonic() < deadline, "materialized input custody deadline")
        pin = owner.PinnedFile(api, path, FILE_LIMIT)
        held.append(pin)
        generated.append(pin)
        info, _ = pin.read(deadline=deadline)
        used += info["bytes"]
        need(used <= byte_cap, "materialized input aggregate byte bound")
        rows.append({**info, "relative_path": path.relative_to(root).as_posix()})
    record = {
        "root": str(root),
        "files": rows,
        "bytes": used,
        "file_count": len(rows),
        "held_until_original_final_audit": True,
    }
    ledger.append(record)
    return record


def retain_dependencies(
    owner,
    api,
    cancellation,
    packages,
    lock_raw,
    collector,
    repo,
    cargo_home,
    held,
    generated,
    output,
    deadline,
    materialized_roots,
):
    plan = collector.dependency_plan(packages, lock_raw, repo, cargo_home)
    roots, records, sources = {}, [], []
    total_bytes, total_files = 0, 0
    for item in plan:
        cancellation.check()
        need(time.monotonic() < deadline, "locked dependency input deadline")
        sources.append(item)
        if item["kind"] == "retained_complete_candidate":
            continue
        root = Path(item["root"]).absolute()
        if item["kind"] == "git":
            checkout_bound = Path(cargo_home) / "git/checkouts"
            while not (root / ".git").exists():
                need(
                    collector.beneath(root, checkout_bound),
                    "no original Git checkout metadata",
                )
                root = root.parent
            need(
                (root / ".git").is_dir(),
                "Cargo Git checkout metadata is not a directory",
            )
            head_raw = read_bound(root / ".git/HEAD", 4096)
            need(
                head_raw == (item["locked_commit"] + "\n").encode("ascii"),
                "actual detached Cargo Git checkout differs from the locked commit",
            )
            item["observed_checkout_root"] = str(root)
            item["detached_head"] = item["locked_commit"]
        key = os.path.normcase(str(root))
        if key not in roots:
            record = retain_tree(
                owner,
                api,
                cancellation,
                root,
                held,
                generated,
                records,
                deadline=deadline,
                byte_cap=DEPENDENCY_BYTES - total_bytes,
                file_cap=DEPENDENCY_FILES - total_files,
            )
            total_bytes += record["bytes"]
            total_files += record["file_count"]
            roots[key] = record
        record = roots[key]
        if item["kind"] == "registry":
            by_path = {row["relative_path"]: row for row in record["files"]}
            need(
                ".cargo-checksum.json" in by_path,
                "original registry checksum manifest absent",
            )
            checksum_raw = read_bound(root / ".cargo-checksum.json", 8 * 1024 * 1024)
            need(
                digest(checksum_raw)["sha256"]
                == by_path[".cargo-checksum.json"]["sha256"],
                "original registry checksum buffer drift",
            )
            checksum = parse(checksum_raw)
            need(
                checksum.get("package") == item["archive_sha256"],
                "original registry package checksum disagrees with lock",
            )
            files = checksum.get("files")
            need(
                isinstance(files, dict) and files, "complete registry member checksums"
            )
            need(
                set(by_path) - set(files) <= {".cargo-checksum.json", ".cargo-ok"}
                and set(files) <= set(by_path),
                "untracked/missing registry source file",
            )
            need(
                all(
                    re.fullmatch("[0-9a-f]{64}", value)
                    and by_path[name]["sha256"] == value
                    for name, value in files.items()
                ),
                "registry original member checksum differs",
            )
            archive = owner.PinnedFile(api, item["archive"], FILE_LIMIT)
            held.append(archive)
            generated.append(archive)
            info, _ = archive.read(deadline=deadline)
            need(
                info["sha256"] == item["archive_sha256"],
                "actual .crate archive checksum",
            )
            total_bytes += info["bytes"]
            total_files += 1
            need(
                total_bytes <= DEPENDENCY_BYTES and total_files <= DEPENDENCY_FILES,
                "external dependency retained input bound",
            )
            item["original_archive"] = info
            item["original_checksum_manifest"] = by_path[".cargo-checksum.json"]
    materialized_roots.extend(records)
    observation = {
        "schema": "hepta.windows_credentials.original_dependency_inputs.v1",
        "locked_reachable_packages": sources,
        "retained_external_roots": records,
        "total_external_bytes": total_bytes,
        "total_external_files": total_files,
        "registry_archive_and_member_checksums_verified": True,
        "Git_locked_detached_HEAD_and_all_physical_checkout_inputs_retained": True,
        "independent_Git_object_database_authentication": False,
        "same_source_input_custody_not_hermetic_future_reuse": True,
    }
    return json_file(output / "DEPENDENCY_INPUTS_BEFORE.json", observation)


class ColdHelperArtifact:
    """Only a selected helper from the original completed cold Cargo command."""

    def __init__(
        self,
        owner,
        api,
        collector,
        cancellation,
        selected,
        name,
        fresh_target,
        producer,
        attempt,
        compiler_raw,
        journal,
        deadline,
    ):
        cancellation.check()
        need(time.monotonic() < deadline, "cold helper custody deadline")
        collector.command_terminal(producer)
        need(
            set(selected) == set(collector.HELPERS) and name in collector.HELPERS,
            "only the two selected cold helpers may use artifact custody",
        )
        need(
            attempt["phase"] == PHASES[3]
            and attempt["owner_returned"] is True
            and attempt["within_original_phase_ceiling"] is True
            and attempt["max_attempts"] == 1
            and attempt["original_receipt"] == producer["receipt_path"]
            and attempt["argv"] == producer["argv"]
            and digest(compiler_raw)["sha256"] == producer["stdout"]["sha256"],
            "cold helper has no exact completed original producer",
        )
        artifact = selected[name]
        path = Path(artifact["executable"]).absolute()
        need(
            artifact["reason"] == "compiler-artifact"
            and artifact["target"]["name"] == name
            and artifact["target"]["kind"] == ["bin"]
            and artifact["profile"]["test"] is False
            and collector.beneath(path, fresh_target)
            and any(collector.same_path(path, item) for item in artifact["filenames"]),
            "cold helper artifact escaped its validated compiler declaration",
        )
        journal.update(
            original_producer_receipt=producer["receipt_path"],
            original_producer_argv=producer["argv"],
            original_compiler_stdout=digest(compiler_raw),
            selected_compiler_artifact=artifact,
        )
        self.owner, self.api, self.path = owner, api, path
        self.directory, self.handle, self.before = False, None, None
        # Keep the original object without write/delete sharing. Only this
        # compiler-selected original may have multiple observed links.
        journal["original_open_attempts"] = 1
        handle = api.CreateFileW(str(path), 0x80000000, 1, None, 3, 0x00200000, None)
        need(
            handle not in (None, 0, owner.INVALID_HANDLE_VALUE),
            "cannot retain original cold helper",
        )
        self.handle = handle
        journal["original_handle_opened"] = True
        try:
            info = owner.FILE_INFORMATION()
            api.check(
                api.GetFileInformationByHandle(handle, ctypes.byref(info)),
                "GetFileInformationByHandle(cold helper)",
            )
            need(
                not info.attributes & (0x400 | 0x10) and info.links >= 1,
                "cold helper is reparse, nonregular or has no link",
            )
            self.size = (int(info.size_high) << 32) | int(info.size_low)
            need(0 < self.size <= FILE_LIMIT, "cold helper byte bound")
            buffer = ctypes.create_unicode_buffer(32768)
            length = int(api.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0))
            need(0 < length < len(buffer), "cold helper physical path unavailable")
            physical = buffer.value
            if physical.startswith("\\\\?\\UNC\\"):
                physical = "\\\\" + physical[8:]
            elif physical.startswith("\\\\?\\"):
                physical = physical[4:]
            need(
                os.path.normcase(os.path.abspath(physical))
                == os.path.normcase(str(path)),
                "cold helper parent path is redirected",
            )
            self.identity = {
                "path": str(path),
                "physical_path": physical,
                "bytes": self.size,
                "volume": int(info.volume),
                "file_id": (int(info.index_high) << 32) | int(info.index_low),
                "links": int(info.links),
                "attributes": int(info.attributes),
            }
            journal["original_open_identity"] = self.identity
        except BaseException as error:
            try:
                api.close(self.handle)
                self.handle = None
                journal["original_handle_closed_after_open_failure"] = True
            except BaseException as close_error:
                journal["original_handle_cleanup_unknown"] = repr(close_error)
                error.add_note("cold helper open cleanup: " + repr(close_error))
            raise

    def read(self, *, keep_bytes=False, deadline=None):
        # Reuse the original same-handle read/hash/identity-drift algorithm.
        return self.owner.PinnedFile.read(
            self, keep_bytes=keep_bytes, deadline=deadline
        )

    def close(self):
        return self.owner.PinnedFile.close(self)


def materialize_cold_helper(
    owner,
    api,
    collector,
    cancellation,
    selected,
    name,
    fresh_target,
    producer,
    attempt,
    compiler_raw,
    destination,
    held,
    generated,
    journal,
    deadline,
):
    journal.update(
        schema="hepta.windows_credentials.cold_helper_copy.v1",
        status="FAILED_OR_UNKNOWN",
        destination=str(destination),
        original_open_attempts=0,
        original_handle_opened=False,
        copy_create_attempts=0,
        copy_created=False,
        write_api_calls=0,
        confirmed_written_bytes=0,
        failed_write_tail_unknown=False,
        write_observation=None,
        first_write_failure=None,
        flushed=False,
        bridge_open_attempts=0,
        bridge_opened=False,
        write_close_attempts=0,
        write_handle_closed=False,
        bridge_close_attempts=0,
        bridge_closed=False,
        destination_pinned=False,
        close_errors=[],
    )
    original = ColdHelperArtifact(
        owner,
        api,
        collector,
        cancellation,
        selected,
        name,
        fresh_target,
        producer,
        attempt,
        compiler_raw,
        journal,
        deadline,
    )
    held.append(original)
    generated.append(original)
    original_info, raw = original.read(keep_bytes=True, deadline=deadline)
    journal["original_before_copy"] = original_info
    cancellation.check()
    need(
        time.monotonic() < deadline and not os.path.lexists(str(destination)),
        "cold helper copy is not fresh or its original deadline expired",
    )
    # These two local function objects do not replace any original owner API.
    write_file = ctypes.WINFUNCTYPE(
        owner.BOOL,
        owner.HANDLE,
        owner.PTR,
        owner.DWORD,
        ctypes.POINTER(owner.DWORD),
        owner.PTR,
        use_last_error=True,
    )(("WriteFile", api.kernel))
    flush_file = ctypes.WINFUNCTYPE(
        owner.BOOL,
        owner.HANDLE,
        use_last_error=True,
    )(("FlushFileBuffers", api.kernel))
    handles = {"write": None, "bridge": None}
    failure = None

    def identity(handle):
        value = owner.FILE_INFORMATION()
        api.check(
            api.GetFileInformationByHandle(handle, ctypes.byref(value)),
            "GetFileInformationByHandle(new helper copy)",
        )
        need(
            not value.attributes & (0x400 | 0x10) and value.links == 1,
            "new helper copy is not an independent regular file",
        )
        return {
            "bytes": (int(value.size_high) << 32) | int(value.size_low),
            "volume": int(value.volume),
            "file_id": (int(value.index_high) << 32) | int(value.index_low),
            "links": int(value.links),
            "attributes": int(value.attributes),
        }

    def close_once(label):
        handle = handles[label]
        if handle is None or journal[label + "_close_attempts"]:
            return
        journal[label + "_close_attempts"] += 1
        try:
            api.close(handle)
        except BaseException as error:
            journal["close_errors"].append({"handle": label, "error": repr(error)})
            raise
        handles[label] = None
        journal["write_handle_closed" if label == "write" else "bridge_closed"] = True

    try:
        cancellation.check()
        need(time.monotonic() < deadline, "new helper copy creation deadline")
        journal["copy_create_attempts"] = 1
        # GENERIC_READ|WRITE, share READ only, CREATE_NEW, OPEN_REPARSE_POINT.
        handle = api.CreateFileW(
            str(destination), 0xC0000000, 1, None, 1, 0x00200000, None
        )
        need(
            handle not in (None, 0, owner.INVALID_HANDLE_VALUE),
            "CREATE_NEW helper copy failed",
        )
        handles["write"] = handle
        journal["copy_created"] = True
        before = identity(handle)
        need(before["bytes"] == 0, "CREATE_NEW helper copy was not empty")
        journal["copy_created_identity"] = before
        while journal["confirmed_written_bytes"] < len(raw):
            cancellation.check()
            need(time.monotonic() < deadline, "helper copy write deadline")
            offset = journal["confirmed_written_bytes"]
            chunk = raw[offset : offset + 65536]
            data, written = ctypes.create_string_buffer(chunk), owner.DWORD()
            observation = {
                "phase": "native_call",
                "attempt": journal["write_api_calls"] + 1,
                "requested_bytes": len(chunk),
                "confirmed_prefix_before": offset,
                "return_received": False,
                "ok": None,
                "reported_bytes": None,
                "native_error": None,
            }
            journal["write_observation"] = observation
            # The call may raise or return an impossible count after effects.
            # Only a legal successful return can confirm and clear this tail.
            journal["failed_write_tail_unknown"] = True
            try:
                journal["write_api_calls"] += 1
                ok = write_file(handle, data, len(chunk), ctypes.byref(written), None)
                error = ctypes.get_last_error()
                observation.update(
                    phase="returned_progress_validation",
                    return_received=True,
                    ok=bool(ok),
                    reported_bytes=int(written.value),
                    native_error=error,
                )
                if not ok:
                    journal["failed_write_reported_bytes"] = int(written.value)
                    journal["failed_write_error"] = error
                    raise ctypes.WinError(error)
                need(
                    0 < written.value <= len(chunk),
                    "helper copy write made invalid progress",
                )
                journal["confirmed_written_bytes"] += int(written.value)
                observation["phase"] = "confirmed"
                observation["confirmed_prefix_after"] = journal[
                    "confirmed_written_bytes"
                ]
                journal["failed_write_tail_unknown"] = False
            except BaseException as write_error:
                observation["error"] = repr(write_error)
                if journal["first_write_failure"] is None:
                    journal["first_write_failure"] = dict(observation)
                raise
        api.check(flush_file(handle), "FlushFileBuffers(new helper copy)")
        journal["flushed"] = True
        after = identity(handle)
        need(
            after["bytes"] == len(raw)
            and (after["volume"], after["file_id"])
            == (before["volume"], before["file_id"]),
            "new helper copy identity or complete length differs",
        )
        journal["copy_after_flush_identity"] = after
        cancellation.check()
        need(time.monotonic() < deadline, "helper copy custody transition deadline")
        # This read-only bridge prevents replacement during handoff. Its
        # temporary share-write allowance admits the still-open writer; the
        # unchanged final PinnedFile refuses any outstanding writer. Its full
        # same-object byte check then precedes every use of the copy.
        journal["bridge_open_attempts"] = 1
        bridge = api.CreateFileW(
            str(destination), 0x80000000, 3, None, 3, 0x00200000, None
        )
        need(
            bridge not in (None, 0, owner.INVALID_HANDLE_VALUE),
            "new helper read-only custody bridge failed",
        )
        handles["bridge"] = bridge
        journal["bridge_opened"] = True
        need(
            identity(bridge) == after, "helper bridge is not the same CREATE_NEW object"
        )
        close_once("write")
        actual, actual_info, copied = native_pe(
            owner,
            api,
            cancellation,
            destination,
            held,
            generated,
            deadline,
        )
        journal["destination_pinned"] = True
        need(
            all(actual_info[key] == after[key] for key in after)
            and copied == raw
            and all(
                actual_info[key] == original_info[key]
                for key in ("bytes", "sha256", "git_blob")
            ),
            "independent helper copy differs from its original held artifact",
        )
        observed_after, _ = original.read(deadline=deadline)
        need(observed_after == original_info, "held Cargo helper changed during copy")
        journal["original_after_copy"] = observed_after
        journal["execution_copy"] = actual_info
        journal["status"] = "VERIFIED_PENDING_FINAL_AUDIT"
        return actual, actual_info, original_info
    except BaseException as error:
        failure = error
        journal["status"] = "FAILED_OR_UNKNOWN"
        journal["error"] = repr(error)
        raise
    finally:
        for label in ("write", "bridge"):
            try:
                close_once(label)
            except BaseException:
                # close_once retained the exact failure and never retries it.
                pass
        if journal["close_errors"]:
            journal["status"] = "FAILED_OR_UNKNOWN"
            if failure is None:
                journal["error"] = "helper copy handle closure unresolved: " + repr(
                    journal["close_errors"]
                )
                raise RuntimeError(journal["error"])
            failure.add_note(
                "helper copy closure unresolved: " + repr(journal["close_errors"])
            )


def native_pe(owner, api, cancellation, path, held, generated, deadline):
    cancellation.check()
    pin = owner.PinnedFile(api, path, FILE_LIMIT)
    held.append(pin)
    generated.append(pin)
    info, raw = pin.read(keep_bytes=True, deadline=deadline)
    need(raw[:2] == b"MZ" and len(raw) >= 64, "original native executable is not PE")
    offset = struct.unpack_from("<I", raw, 60)[0]
    need(
        offset + 6 <= len(raw)
        and raw[offset : offset + 4] == b"PE\0\0"
        and struct.unpack_from("<H", raw, offset + 4)[0] == 0x8664,
        "original executable is not Windows x64 PE",
    )
    return pin, info, raw


def materialized_names(root, cancellation, deadline):
    names = set()
    for parent, dirs, files in os.walk(root, topdown=True, followlinks=False):
        need(
            time.monotonic() <= deadline,
            "final materialized input enumeration deadline",
        )
        parent = Path(parent)
        for name in dirs:
            path = parent / name
            need(
                not path.is_symlink() and not path.is_junction(),
                "final materialized directory reparse",
            )
        for name in files:
            path = parent / name
            need(
                not path.is_symlink() and not path.is_junction(),
                "final materialized file reparse",
            )
            names.add(path.relative_to(root).as_posix())
    return names


def main():
    result = {
        "schema": "hepta-windows-credentials-nine-observation-v1",
        "status": "FAIL_OR_UNKNOWN",
        "native_observation_pass": False,
        "whole_job_acceptance": "PENDING_ORIGINAL_PLATFORM_AND_UPLOAD_REVIEW",
        "frozen_scope": {
            "E2_parameter_updates_consumed": "two students, 8 + 8 = 16 / 16",
            "E6_seconds_remaining_unchanged": 1.9960488015785813,
            "budget_transferred": 0,
            "old_windows167_invocations": 0,
            "global_frozen_roster_complete_claim": False,
        },
        "commands": [],
        "phase_attempts": [],
        "errors": [],
        "unlaunched_phases": list(PHASES),
        "unlaunched_phases_basis": "No original created:true receipt; unresolved launch remains UNKNOWN in the attempt row.",
        "hermetic_reuse_authorized": False,
        "production_acl_account_firewall_qualification": False,
        "host_disposal_acceptance": "PENDING_ORIGINAL_EPHEMERAL_PLATFORM_REVIEW",
        "unit_controls_inventoried_not_executed": [],
        "ConPTY_selected": 0,
    }
    output = None
    owner = None
    api_native = None
    cancellation = None
    held = []
    source_files = []
    source_before = []
    tool_files = []
    tool_before = []
    generated_files = []
    materialized_roots = []
    prepared = False
    final_io_pass = False
    operation_deadline = None
    cleanup_deadline = None
    finish_deadline = None
    start = time.monotonic()
    repo = Path(os.environ.get("GITHUB_WORKSPACE", "")).absolute()
    try:
        run_id = os.environ.get("GITHUB_RUN_ID", "")
        need(re.fullmatch("[1-9][0-9]*", run_id), "original workflow run ID")
        output = Path(os.environ["RUNNER_TEMP"]).absolute() / (
            "hepta-windows-credentials-nine-" + run_id
        )
        need(
            output.is_dir(),
            "first workflow step must own the fresh observation directory",
        )
        need(
            set(p.name for p in output.iterdir()) == {"BOOTSTRAP.json"},
            "observation directory is not fresh",
        )
        boot_raw = read_bound(output / "BOOTSTRAP.json", 16384)
        boot = parse(boot_raw)
        need(
            boot.get("schema") == "hepta.windows_credentials.original_job_clock.v1"
            and boot.get("shared_whole_seconds") == WHOLE_SECONDS
            and boot.get("working_seconds") == WORK_SECONDS
            and boot.get("retention_seconds") == 300
            and boot.get("includes_checkout_tools_diagnostics_failures_and_upload")
            is True,
            "original shared job clock and budget declaration",
        )
        if sys.platform == "win32":
            clock_kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            clock_kernel.GetTickCount64.restype = ctypes.c_uint64
            clock_kernel.GetTickCount64.argtypes = []
            current_tick = int(clock_kernel.GetTickCount64())
            need(
                isinstance(boot.get("tick_count_ms"), int)
                and 0 <= boot["tick_count_ms"] <= current_tick,
                "original bootstrap cost clock",
            )
            start = time.monotonic() - (current_tick - boot["tick_count_ms"]) / 1000
            operation_deadline, cleanup_deadline, finish_deadline = (
                start + WORK_SECONDS,
                start + RETENTION_DEADLINE_SECONDS,
                start + WHOLE_SECONDS,
            )
        need(
            boot["run_id"] == run_id and boot["run_attempt"] == "1",
            "original bootstrap identity",
        )
        input_raw = read_bound(repo / INPUT_PATH, 65536)
        need(
            digest(input_raw)["sha256"]
            == os.environ.get("HEPTA_WINDOWS_CREDENTIALS_INPUT_SHA256"),
            "workflow/input byte identity",
        )
        config = parse(input_raw)
        result["input"] = durable(output / "INPUT.original.json", input_raw)
        need(
            config["schema"] == "hepta.windows_credentials.nine_input.v1",
            "input schema",
        )
        need(
            config["root_execution_authorized"] is True
            and config["root_budget_accepted"] is True
            and config["root_original_first_attempt_cleared"] is True
            and config["root_new_candidate_regression_approved"] is True
            and config["root_account_operations_approved"] is True
            and config["root_ephemeral_host_lifetime_accepted"] is True
            and config["root_cross_drive_controls_approved"] is True,
            "Root first-native admission is inactive",
        )
        need(
            config["parent"] == {"head": PARENT_HEAD, "tree": PARENT_TREE},
            "actual7186 source predecessor binding",
        )
        need(
            config["scope_id"] == "hepta-windows-credentials-cross-drive-20261127-7c9e",
            "frozen new scope identity",
        )
        for key in (
            "root_admission_sha256",
            "first_native_clearance_sha256",
            "root_source_review_sha256",
            "root_account_lifetime_sha256",
            "root_first24_format_acceptance_sha256",
        ):
            need(
                re.fullmatch("[0-9a-f]{64}", config.get(key) or ""),
                "missing original Root receipt: " + key,
            )
        need(
            config["root_first24_format_acceptance_sha256"]
            == "af5be0bb40cf944995ece5980d4c6ec067de32d1dd3cb93899823a56ec5cedce",
            "actual first24 formatter acceptance",
        )
        need(config["history"] == HISTORY, "original failed observations/costs changed")
        result["prior_original_observations"] = config["history"]
        need(config["budget"] == BUDGET, "new candidate original budget changed")
        need(
            config["ephemeral_host_policy"] == EPHEMERAL_POLICY,
            "account/host lifetime policy differs",
        )
        need(
            config["source_paths"] == list(CANDIDATE_PATHS)
            and config["new_paths"] == list(ADDED_PATHS)
            and config["changed_paths"] == list(CHANGED_PATHS),
            "exact29 source closure and exact5 changed paths",
        )
        need(
            set(config["source_sha256"])
            == set(CANDIDATE_PATHS) - {INPUT_PATH, WORKFLOW},
            "complete noncircular source hash roster",
        )
        need(
            all(
                re.fullmatch("[0-9a-f]{64}", value)
                for value in config["source_sha256"].values()
            ),
            "source hash syntax",
        )
        need(
            config["original_first24_source_pins"] == FORMATTED24,
            "actual24 unchanged formatted source bindings",
        )
        need(
            all(
                config["source_sha256"][row["repo_path"]] == row["sha256"]
                for row in FORMATTED24
            ),
            "configured source hashes differ from actual formatted24",
        )
        need(
            config["tool_capture_policy"]
            == "root-approved-first-observation-no-hermetic-reuse",
            "unapproved mutable runner tool policy",
        )
        need(
            config["exact_tests"] == list(EXACT_TESTS)
            and config["unit_inventory_only"] == list(UNIT_INVENTORY_ONLY),
            "input exact-nine plus unexecuted unit roster",
        )
        need(
            sys.platform == "win32" and sys.version_info >= (3, 12),
            "native Windows Python 3.12+",
        )
        need(
            os.environ.get("GITHUB_ACTIONS") == "true"
            and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
            and os.environ.get("RUNNER_OS") == "Windows"
            and os.environ.get("RUNNER_ARCH") == "X64",
            "original disposable GitHub-hosted Windows x64 envelope",
        )
        lifecycle, lifecycle_raw = source_module(
            "hepta_windows_credential_lifecycle_v1",
            repo / LIFECYCLE_PATH,
            config["source_sha256"][LIFECYCLE_PATH],
        )
        collector, collector_raw = source_module(
            "hepta_windows_credentials_nine_collector_v1",
            repo / COLLECTOR_PATH,
            config["source_sha256"][COLLECTOR_PATH],
        )
        controls, controls_raw = source_module(
            "hepta_windows_credentials_cross_drive_controls_v1",
            repo / CONTROL_PATH,
            config["source_sha256"][CONTROL_PATH],
        )
        need(
            list(controls.CONTROL_METHODS) == config["cross_drive_control_methods"],
            "exact eight new path controls",
        )
        need(
            list(lifecycle.TESTS) == list(collector.TESTS) == config["exact_tests"]
            and list(collector.UNIT_INVENTORY_ONLY) == config["unit_inventory_only"],
            "both original source rosters must bind this input",
        )
        owner_raw = read_bound(repo / OWNER_PATH, 65536)
        need(
            digest(owner_raw)["sha256"] == config["source_sha256"][OWNER_PATH],
            "unchanged original owner bytes",
        )
        owner, api_native, cancellation = lifecycle.create_native_runtime(
            owner_raw, str((repo / OWNER_PATH).absolute()), config
        )
        cancellation.__enter__()
        now_ticks = int(api_native.GetTickCount64())
        need(
            isinstance(boot["tick_count_ms"], int)
            and 0 <= boot["tick_count_ms"] <= now_ticks,
            "original cross-process monotonic clock",
        )
        start = time.monotonic() - (now_ticks - boot["tick_count_ms"]) / 1000
        operation_deadline, cleanup_deadline, finish_deadline = (
            start + WORK_SECONDS,
            start + RETENTION_DEADLINE_SECONDS,
            start + WHOLE_SECONDS,
        )
        need(
            time.monotonic() < operation_deadline,
            "setup already exhausted original work budget",
        )
        api_dir = output / "original-api"
        api_dir.mkdir()
        reader = Api(api_dir, os.environ["GH_TOKEN"], operation_deadline)
        result["original_api_reads"] = reader.reads
        event_raw = read_bound(Path(os.environ["GITHUB_EVENT_PATH"]), 2 * 1024 * 1024)
        result["original_event"] = durable(output / "ORIGINAL_EVENT.json", event_raw)
        event = parse(event_raw)
        need(
            os.environ.get("GITHUB_EVENT_NAME") == "pull_request"
            and event.get("action") == "opened",
            "only the original opened event is admitted",
        )
        need(
            os.environ.get("GITHUB_REPOSITORY") == REPOSITORY
            and os.environ.get("GITHUB_RUN_ATTEMPT") == "1",
            "repository/attempt changed",
        )
        pr = event["pull_request"]
        need(
            pr["head"]["repo"]["full_name"]
            == REPOSITORY
            == pr["base"]["repo"]["full_name"],
            "foreign repository",
        )
        need(
            pr["head"]["ref"] == HEAD_BRANCH and pr["base"]["ref"] == BASE_BRANCH,
            "original fixed branch pair",
        )
        need(
            pr["base"]["sha"] == PARENT_HEAD
            and pr["user"]["login"] == "ProfHepta"
            and event["sender"]["login"] == "ProfHepta",
            "Root source event identity",
        )
        head = pr["head"]["sha"]
        need(re.fullmatch("[0-9a-f]{40}", head), "real source head")
        result["source_head"] = head
        result["pr_number"] = pr["number"]
        original_run = reader.get("actions/runs/" + run_id, "01-original-run")
        need(
            original_run["run_attempt"] == 1
            and original_run["head_sha"] == head
            and original_run["event"] == "pull_request"
            and original_run["path"] == WORKFLOW,
            "original workflow run identity",
        )
        jobs = reader.get(
            "actions/runs/" + run_id + "/attempts/1/jobs?per_page=100",
            "02-original-jobs",
        )
        need(
            jobs["total_count"] == len(jobs["jobs"]) == 1, "original single native job"
        )
        job = jobs["jobs"][0]
        need(
            job["name"] == "owned-credential-nine"
            and job["run_id"] == int(run_id)
            and job["status"] == "in_progress",
            "original job envelope",
        )
        need(
            set(job.get("labels", [])) == {"windows-2025"},
            "original job labels differ from the accepted hosted image",
        )
        result["original_host_envelope"] = {
            key: job.get(key)
            for key in (
                "runner_id",
                "runner_name",
                "runner_group_id",
                "runner_group_name",
                "labels",
                "started_at",
            )
        }
        pre_boot = (utc(boot["utc"]) - utc(job["started_at"])).total_seconds()
        need(pre_boot >= -2, "UTC/monotonic original job clock disagreement")
        # Charge runner/setup time before the first script as well as all actions.
        start -= max(0, pre_boot)
        operation_deadline, cleanup_deadline, finish_deadline = (
            start + WORK_SECONDS,
            start + RETENTION_DEADLINE_SECONDS,
            start + WHOLE_SECONDS,
        )
        reader.deadline = operation_deadline
        result["clock"] = {
            "job_started_at": job["started_at"],
            "bootstrap": boot,
            "pre_first_step_seconds": max(0, pre_boot),
            "original_start_monotonic": start,
            "work_deadline": operation_deadline,
            "cleanup_deadline": cleanup_deadline,
            "whole_deadline": finish_deadline,
            "final_platform_envelope_required": True,
        }
        pulls = reader.get(
            "pulls?state=all&head="
            + urllib.parse.quote("TrillionniumFoundation:" + HEAD_BRANCH, safe="")
            + "&per_page=100",
            "03-original-branch-prs",
        )
        need(
            isinstance(pulls, list)
            and len(pulls) == 1
            and pulls[0]["number"] == pr["number"],
            "this fixed scope branch has a competing/reopened PR",
        )
        need(
            pulls[0]["head"]["sha"] == head
            and pulls[0]["created_at"] == pr["created_at"],
            "original first PR identity changed",
        )
        runs = reader.get(
            "actions/runs?head_sha=" + head + "&per_page=100", "04-original-head-runs"
        )
        need(
            runs["total_count"] == len(runs["workflow_runs"]) < 100,
            "complete head run directory",
        )
        scope_runs = [r for r in runs["workflow_runs"] if r["path"] == WORKFLOW]
        need(
            len(scope_runs) == 1
            and scope_runs[0]["id"] == int(run_id)
            and scope_runs[0]["run_attempt"] == 1,
            "same-head/same-scope replay is refused",
        )
        commit = reader.get("git/commits/" + head, "05-original-source-commit")
        need(
            [p["sha"] for p in commit["parents"]] == [PARENT_HEAD], "source sole parent"
        )
        original_parent = reader.get(
            "git/trees/" + PARENT_TREE + "?recursive=1", "06-original-parent-tree"
        )
        original_current = reader.get(
            "git/trees/" + commit["tree"]["sha"] + "?recursive=1",
            "07-original-source-tree",
        )
        need(
            original_parent["sha"] == PARENT_TREE
            and original_current["sha"] == commit["tree"]["sha"],
            "API/source tree identity",
        )
        parent, current = tree_map(original_parent), tree_map(original_current)
        need(
            len(parent) == 16154
            and sum(x["bytes"] for x in parent.values()) == 336024308,
            "actual7186 complete parent inventory",
        )
        need(
            {p for p in parent if parent[p]["mode"] == "120000"} == {LINK_PATH}
            and parent[LINK_PATH]
            == {"mode": "120000", "git_blob": LINK_BLOB, "bytes": 7},
            "original symlink inventory",
        )
        changed = {
            p for p in set(parent) | set(current) if parent.get(p) != current.get(p)
        }
        need(
            changed == set(CHANGED_PATHS)
            and set(ADDED_PATHS).isdisjoint(parent)
            and set(CANDIDATE_PATHS) - set(ADDED_PATHS) <= set(parent),
            "candidate must match exact5 changes, one actual absence and the full source closure",
        )
        need(
            all(current[p]["mode"] == "100644" for p in CANDIDATE_PATHS)
            and all(
                parent[p]["mode"] == "100644"
                for p in set(CANDIDATE_PATHS) - set(ADDED_PATHS)
            ),
            "candidate source modes",
        )
        need(len(current) == 16155, "full current source leaf count")
        attrs = {
            p: value
            for p, value in current.items()
            if PurePosixPath(p).name == ".gitattributes"
        }
        need(
            set(attrs) == set(config["attributes_sha256"]),
            "complete applicable Git attributes",
        )
        need(
            not (repo / ".git/info/attributes").exists(),
            "untracked Git attribute injection",
        )
        need(
            enumerate_files(repo) == set(current),
            "untracked, missing or alternate source inputs",
        )
        directories = {repo}
        for path in current:
            node = (repo / path).parent
            while node != repo:
                directories.add(node)
                node = node.parent
        for path in sorted(directories, key=lambda item: (len(item.parts), str(item))):
            need(
                time.monotonic() < operation_deadline,
                "source custody preparation deadline",
            )
            held.append(owner.PinnedFile(api_native, path, 0, directory=True))
        for path, entry in sorted(current.items()):
            need(
                time.monotonic() < operation_deadline,
                "source custody byte audit deadline",
            )
            pin = owner.PinnedFile(api_native, repo / path, FILE_LIMIT)
            held.append(pin)
            source_files.append((path, pin))
            info, raw = pin.read(
                keep_bytes=path in CANDIDATE_PATHS or path == LINK_PATH,
                deadline=operation_deadline,
            )
            need(
                info["bytes"] == entry["bytes"]
                and info["git_blob"] == entry["git_blob"],
                "physical source/Git byte mismatch: " + path,
            )
            info = {**info, "repo_path": path, "git_mode": entry["mode"]}
            formatted = [row for row in FORMATTED24 if row["repo_path"] == path]
            if formatted:
                need(
                    all(
                        info[key] == formatted[0][key]
                        for key in ("bytes", "sha256", "git_blob")
                    ),
                    "actual formatted source bytes differ: " + path,
                )
            source_before.append(info)
            if path in config["source_sha256"]:
                need(
                    info["sha256"] == config["source_sha256"][path],
                    "approved source pin: " + path,
                )
            if path in config["attributes_sha256"]:
                need(
                    info["sha256"] == config["attributes_sha256"][path],
                    "attribute byte identity: " + path,
                )
            if path == LINK_PATH:
                need(raw == b"COPYING", "original Windows symlink text materialization")
            if path in CANDIDATE_PATHS:
                durable(
                    output
                    / ("source-" + str(CANDIDATE_PATHS.index(path)) + ".original"),
                    raw,
                )
        need(
            dict((p, f.before["sha256"]) for p, f in source_files)[INPUT_PATH]
            == digest(input_raw)["sha256"],
            "input changed between bootstrap and held source custody",
        )
        result["source_before"] = json_file(
            output / "SOURCE_BEFORE.json", source_before
        )
        result["source_tree"] = commit["tree"]["sha"]
        result["source_changes"] = sorted(changed)
        # The API commit is not a substitute for the physical checkout HEAD.
        # Retain original Git metadata while build scripts may read it.
        git_directory = repo / ".git"
        held.append(owner.PinnedFile(api_native, git_directory, 0, directory=True))
        git_metadata = []
        for name in ("HEAD", "config", "index", "shallow", "packed-refs"):
            path = git_directory / name
            if not path.exists():
                need(
                    name not in ("HEAD", "config", "index"),
                    "required local Git metadata missing",
                )
                git_metadata.append({"path": str(path), "exists": False})
                continue
            pin = owner.PinnedFile(api_native, path, FILE_LIMIT)
            held.append(pin)
            generated_files.append(pin)
            info, raw = pin.read(keep_bytes=name == "HEAD", deadline=operation_deadline)
            if name == "HEAD":
                need(
                    raw == (head + "\n").encode("ascii"),
                    "physical detached HEAD differs from original event",
                )
            git_metadata.append({**info, "exists": True})
        need(
            not (git_directory / "objects/info/alternates").exists(),
            "unapproved alternate Git object store",
        )
        result["local_git_before"] = json_file(
            output / "SOURCE_LOCAL_GIT_BEFORE.json", git_metadata
        )
        result["symlink_mode_materialized_text"] = {
            "path": LINK_PATH,
            "bytes": 7,
            "git_blob": LINK_BLOB,
        }
        result["tool_setup_steps"] = [
            s
            for s in job["steps"]
            if s["number"]
            < next(
                s["number"]
                for s in job["steps"]
                if s["name"] == "Observe the owned nine credential cases"
            )
        ]
        need(
            all(step["conclusion"] == "success" for step in result["tool_setup_steps"]),
            "original provisioning steps did not finish successfully",
        )
        # Homes are explicitly declared before both pinned provisioning actions.
        # No USERPROFILE/default-home lookup or alternate executable is admitted.
        tools_root = Path(os.environ["RUNNER_TEMP"]).absolute() / (
            "hepta-windows-credentials-tools-" + run_id
        )
        rustup = tools_root / "rustup"
        cargo_home = tools_root / "cargo"
        toolchain = rustup / "toolchains/1.96.0-x86_64-pc-windows-msvc/bin"
        expected_homes = {
            "schema": "hepta.windows_credentials.explicit_tool_homes.v1",
            "root": str(tools_root),
            "rustup_home": str(rustup),
            "cargo_home": str(cargo_home),
            "toolchain": "1.96.0-x86_64-pc-windows-msvc",
            "toolchain_bin": str(toolchain),
            "selection": "explicit-before-provision-no-defaults",
        }
        result["tool_home_binding"] = {
            "bootstrap": boot.get("tool_homes"),
            "environment": {
                name: os.environ.get(name) for name in ("RUSTUP_HOME", "CARGO_HOME")
            },
            "expected": expected_homes,
            "accepted": False,
        }
        need(boot.get("tool_homes") == expected_homes, "original explicit tool homes")
        need(
            os.environ.get("RUSTUP_HOME") == str(rustup)
            and os.environ.get("CARGO_HOME") == str(cargo_home),
            "provisioning environment differs from the original declared homes",
        )
        result["tool_home_binding"]["accepted"] = True
        # Direct libtest needs no just or nextest installation.
        # These exact provisioned tool bytes are retained; no hermetic reuse is asserted.
        tools = {
            "cargo": toolchain / "cargo.exe",
            "rustc": toolchain / "rustc.exe",
            "python": Path(sys.executable),
        }
        tool_directories = {tools_root, rustup, cargo_home}
        for path in tools.values():
            for parent_directory in path.absolute().parents:
                if parent_directory != Path(parent_directory.anchor):
                    tool_directories.add(parent_directory)
        for path in sorted(
            tool_directories, key=lambda item: (len(item.parts), str(item))
        ):
            held.append(owner.PinnedFile(api_native, path, 0, directory=True))
        for name, path in tools.items():
            pin = owner.PinnedFile(api_native, path, FILE_LIMIT)
            held.append(pin)
            tool_files.append((name, pin))
            info, _ = pin.read(deadline=operation_deadline)
            tool_before.append({"tool": name, **info})
        result["tools_before"] = json_file(output / "TOOLS_BEFORE.json", tool_before)
        result["runtime"] = {
            "python": sys.version,
            "executable": sys.executable,
            "os_version": list(sys.getwindowsversion()),
            "image_os": os.environ.get("ImageOS"),
            "image_version": os.environ.get("ImageVersion"),
            "runner_arch": os.environ.get("RUNNER_ARCH"),
            "rust_toolchain_requested": "1.96.0",
            "just_or_nextest_used": False,
            "provisioned_tool_reuse": False,
        }
        for external in (cargo_home / "config", cargo_home / "config.toml"):
            need(not external.exists(), "unapproved external Cargo config")
        target = output / "cold-target"
        target.mkdir(exist_ok=False)
        output_directories = [target, output]
        parent_directory = output.parent
        while parent_directory != Path(parent_directory.anchor):
            output_directories.append(parent_directory)
            parent_directory = parent_directory.parent
        for path in reversed(output_directories):
            held.append(owner.PinnedFile(api_native, path, 0, directory=True))
        (output / "commands").mkdir()
        need(
            not (repo / "codex-rs/target").exists(),
            "cold workspace has a previous target directory",
        )
        child_env = dict(os.environ)
        for key in list(child_env):
            upper = key.upper()
            if upper.startswith(
                ("NEXTEST_", "CARGO_", "RUST", "GIT_", "PYTHON", "HEPTA_CREDENTIAL_")
            ) or upper in ("GH_TOKEN", "GITHUB_TOKEN", "LD_PRELOAD", "LD_LIBRARY_PATH"):
                del child_env[key]
        for key in list(child_env):
            upper = key.upper()
            if upper in (
                "CC",
                "CXX",
                "AR",
                "AS",
                "CL",
                "LINK",
                "CFLAGS",
                "CPPFLAGS",
                "CXXFLAGS",
                "LDFLAGS",
                "LIBCLANG_PATH",
                "LLVM_CONFIG_PATH",
                "CMAKE_TOOLCHAIN_FILE",
                "CMAKE_GENERATOR",
                "VCPKG_ROOT",
                "VCPKG_INSTALLED_ROOT",
                "RUSTC_WRAPPER",
                "RUSTC_WORKSPACE_WRAPPER",
            ) or upper.startswith(
                ("CC_", "CXX_", "AR_", "HOST_CC", "HOST_CXX", "TARGET_CC", "TARGET_CXX")
            ):
                del child_env[key]
        child_env.update(
            {
                "PATH": str(toolchain)
                + os.pathsep
                + str(cargo_home / "bin")
                + os.pathsep
                + child_env.get("PATH", ""),
                "CARGO_HOME": str(cargo_home),
                "RUSTUP_HOME": str(rustup),
                "RUSTUP_TOOLCHAIN": "1.96.0-x86_64-pc-windows-msvc",
                "CARGO": str(tools["cargo"]),
                "RUSTC": str(tools["rustc"]),
                "CARGO_TARGET_DIR": str(target),
                "CARGO_BUILD_JOBS": "1",
                "CARGO_INCREMENTAL": "0",
                "CARGO_TERM_COLOR": "never",
                "RUST_MIN_STACK": "8388608",
                "CODEX_TEST_WINDOWS_ELEVATED_FIXTURE": "github-hosted-admin-v1",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_ATTR_NOSYSTEM": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        need(child_env.get("RUNNER_ARCH") == "X64", "native x64 runner required")
        result["child_environment"] = {
            key: value
            for key, value in child_env.items()
            if key.startswith(("CARGO", "RUST", "NEXTEST", "GIT_", "PYTHON"))
            or key in ("PATH", "PATHEXT", "SystemRoot", "TEMP", "TMP")
        }
        result["dependency_materialization"] = (
            "Original locked resolution and fresh compiled target; registry bytes may be fetched once and costs are charged."
        )
        workspace = repo / "codex-rs"
        meta_path = output / "cargo-metadata.windows.json"
        phase_rows = []

        def invoke(index, argv, group_deadline):
            cancellation.check()
            need(index == len(phase_rows), "phase order or repeated phase")
            now = time.monotonic()
            need(now < operation_deadline, "original shared work budget exhausted")
            for external in (cargo_home / "config", cargo_home / "config.toml"):
                need(not external.exists(), "external Cargo configuration appeared")
            need(
                not (repo / ".git/info/attributes").exists()
                and not (repo / ".git/objects/info/alternates").exists(),
                "external Git attributes/object store appeared",
            )
            phase_deadline = min(operation_deadline, group_deadline)
            attempt = {
                "phase": PHASES[index],
                "argv": argv,
                "max_attempts": 1,
                "started_monotonic": now,
                "operation_deadline": phase_deadline,
                "owner_returned": False,
                "launch_state": "UNKNOWN_UNTIL_ORIGINAL_OWNER_RETURN",
            }
            result["phase_attempts"].append(attempt)
            json_file(output / (PHASES[index] + ".ORIGINAL_ATTEMPT.json"), attempt)
            row = owner.run_owned(
                api_native,
                cancellation,
                argv,
                workspace,
                child_env,
                output / "commands" / PHASES[index],
                operation_deadline=phase_deadline,
                cleanup_deadline=cleanup_deadline,
                limits=config["owner_limits"],
            )
            phase_rows.append(row)
            result["commands"].append(row)
            if row.get("created") is True:
                result["unlaunched_phases"].remove(PHASES[index])
            attempt["owner_returned"] = True
            attempt["launch_state"] = {
                "created": row["created"],
                "launch_attempts": row["launch_attempts"],
            }
            attempt["original_receipt"] = row["receipt_path"]
            after_owner_io = time.monotonic()
            attempt["owner_returned_monotonic"] = after_owner_io
            attempt["seconds_including_owner_receipt_io"] = after_owner_io - now
            attempt["within_original_phase_ceiling"] = after_owner_io <= phase_deadline
            need(
                attempt["within_original_phase_ceiling"],
                "owner receipt IO exceeded the original phase ceiling",
            )
            collector.command_terminal(row)
            lifecycle.verify_original_runtime(owner, api_native, cancellation)
            cancellation.check()
            need(
                time.monotonic() < operation_deadline,
                "phase and diagnostics exhausted shared work budget",
            )
            return row

        def retain_stdout(row, destination):
            raw = read_bound(
                row["stdout"]["path"], config["owner_limits"]["stream_bytes"]
            )
            need(
                digest(raw)["sha256"] == row["stdout"]["sha256"],
                "owned stdout source mismatch",
            )
            durable(destination, raw)
            pin = owner.PinnedFile(api_native, destination, FILE_LIMIT)
            held.append(pin)
            generated_files.append(pin)
            info, same = pin.read(keep_bytes=True, deadline=operation_deadline)
            need(same == raw, "generated metadata publication changed")
            return raw

        # Source/HEAD custody is complete before these new in-process controls.
        # The isolated collector copy executes the same checked raw buffer; no
        # native command, native owner replacement, extra phase or budget is added.
        cancellation.check()
        need(
            time.monotonic() < operation_deadline, "no work time left for path controls"
        )
        result["cross_drive_control_source"] = {
            "repo_path": CONTROL_PATH,
            **digest(controls_raw),
        }
        control_observation = {}
        result["cross_drive_controls"] = control_observation
        controls.observe(
            collector_raw,
            config["source_sha256"][COLLECTOR_PATH],
            str(repo / COLLECTOR_PATH),
            operation_deadline,
            cancellation.check,
            control_observation,
        )
        need(
            control_observation.get("status") == "PASS"
            and control_observation.get("tests_run") == 8
            and control_observation.get("within_original_work_deadline") is True,
            "new path controls have no complete in-budget observation",
        )
        result["cross_drive_control_record"] = json_file(
            output / "CROSS_DRIVE_CONTROLS.original.json", control_observation
        )
        lifecycle.verify_original_runtime(owner, api_native, cancellation)
        cancellation.check()
        need(
            time.monotonic() < operation_deadline,
            "path control retention exhausted the original work budget",
        )
        prepared = True
        result["ordinary_scope_budget"] = BUDGET
        result["account_host_admission"] = {
            "root_account_lifetime_sha256": config["root_account_lifetime_sha256"],
            "policy": EPHEMERAL_POLICY,
            "actual_provider_terminal_and_disposal_not_yet_observed": True,
        }
        # All preparatory native commands use the same original runtime and clock.
        identity_deadline = min(operation_deadline, time.monotonic() + 20)
        row = invoke(0, [str(tools["rustc"]), "-vV"], identity_deadline)
        rustc_version_raw = retain_stdout(row, output / "RUSTC_VERSION.original.txt")
        row = invoke(1, [str(tools["cargo"]), "-Vv"], identity_deadline)
        cargo_version_raw = retain_stdout(row, output / "CARGO_VERSION.original.txt")
        result["actual_compiler_identity"] = collector.compiler_identity(
            rustc_version_raw, cargo_version_raw
        )
        # Capture the complete provisioned Rust toolchain and the actual Python
        # modules already imported by this trusted caller. Windows/SDK/system
        # dependencies remain original runner observations, not hermetic reuse.
        result["materialized_input_roots"] = materialized_roots
        toolchain_record = retain_tree(
            owner,
            api_native,
            cancellation,
            toolchain.parent,
            held,
            generated_files,
            result["materialized_input_roots"],
            deadline=operation_deadline,
            byte_cap=TOOLCHAIN_BYTES,
            file_cap=TOOLCHAIN_FILES,
        )
        result["toolchain_materialization"] = json_file(
            output / "TOOLCHAIN_INPUTS_BEFORE.json", toolchain_record
        )
        python_modules, python_paths = [], set()
        for name, module in sorted(sys.modules.items()):
            filename = getattr(module, "__file__", None)
            if not filename:
                continue
            path = Path(filename).absolute()
            if not path.is_file():
                continue
            key = os.path.normcase(str(path))
            if key in python_paths or collector.beneath(path, repo):
                continue
            cancellation.check()
            need(
                time.monotonic() < operation_deadline, "Python module custody deadline"
            )
            pin = owner.PinnedFile(api_native, path, FILE_LIMIT)
            held.append(pin)
            generated_files.append(pin)
            info, _ = pin.read(deadline=operation_deadline)
            python_paths.add(key)
            python_modules.append({"module": name, **info})
        result["observed_python_module_inputs"] = json_file(
            output / "PYTHON_MODULES_BEFORE.json", python_modules
        )
        metadata_deadline = min(operation_deadline, time.monotonic() + 60)
        row = invoke(
            2,
            [
                str(tools["cargo"]),
                "metadata",
                "--locked",
                "--format-version",
                "1",
                "--filter-platform",
                "x86_64-pc-windows-msvc",
            ],
            metadata_deadline,
        )
        metadata_raw = retain_stdout(row, meta_path)
        full_metadata, package, reachable = collector.metadata(
            metadata_raw, workspace, target
        )
        lock_raw = read_bound(workspace / "Cargo.lock", 4 * 1024 * 1024)
        source_by_path = {path: pin for path, pin in source_files}
        need(
            digest(lock_raw)["sha256"]
            == source_by_path["codex-rs/Cargo.lock"].before["sha256"],
            "locked dependency buffer differs from the retained original source",
        )
        result["dependency_inputs_before"] = retain_dependencies(
            owner,
            api_native,
            cancellation,
            reachable,
            lock_raw,
            collector,
            repo,
            cargo_home,
            held,
            generated_files,
            output,
            operation_deadline,
            materialized_roots,
        )
        result["source_root_holds_before_build"] = {
            "complete_candidate": True,
            "external_dependencies_materialized_once_from_original_locked_metadata": True,
            "build_commands_offline_after_materialization": True,
            "future_hermetic_or_cross_machine_reuse_authorized": False,
        }
        # One shared cold-build ceiling, not one1400 allowance per command.
        cold_started = time.monotonic()
        cold_deadline = min(operation_deadline, cold_started + 1400)
        row = invoke(
            3,
            [
                str(tools["cargo"]),
                "build",
                "--locked",
                "--offline",
                "-p",
                collector.PACKAGE,
                "--profile",
                "dev-small",
                "--message-format=json",
                "--bin",
                collector.HELPERS[0],
                "--bin",
                collector.HELPERS[1],
            ],
            cold_deadline,
        )
        helper_producer = row
        helper_raw = retain_stdout(row, output / "HELPER_COMPILER.original.jsonl")
        helper_artifacts = collector.compiler_artifacts(
            helper_raw, package, workspace, target, helpers=True
        )
        row = invoke(
            4,
            [
                str(tools["cargo"]),
                "test",
                "--locked",
                "--offline",
                "-p",
                collector.PACKAGE,
                "--lib",
                "--no-run",
                "--profile",
                "dev-small",
                "--message-format=json",
            ],
            cold_deadline,
        )
        harness_raw = retain_stdout(row, output / "LIBRARY_COMPILER.original.jsonl")
        harness_artifacts = collector.compiler_artifacts(
            harness_raw, package, workspace, target, helpers=False
        )
        need(
            time.monotonic() <= cold_deadline,
            "two cold builds and their collection exceeded shared1400",
        )
        result["cold_build_shared_clock"] = {
            "started_monotonic": cold_started,
            "operation_deadline": cold_deadline,
            "seconds": time.monotonic() - cold_started,
            "both_builds_share_same_fresh_target": True,
            "preexisting_binary_or_original_old_check_reused": False,
        }
        harness_path = Path(
            harness_artifacts[collector.LIBRARY]["executable"]
        ).absolute()
        native_paths = [harness_path] + [
            Path(helper_artifacts[name]["executable"]).absolute()
            for name in collector.HELPERS
        ]
        native_dirs = set()
        for path in native_paths:
            parent_directory = path.parent
            while parent_directory != target:
                need(
                    collector.beneath(parent_directory, target),
                    "compiler artifact parent escaped the original fresh target",
                )
                native_dirs.add(parent_directory)
                parent_directory = parent_directory.parent
        for path in sorted(native_dirs, key=lambda item: (len(item.parts), str(item))):
            held.append(owner.PinnedFile(api_native, path, 0, directory=True))
        harness, harness_info, _ = native_pe(
            owner,
            api_native,
            cancellation,
            harness_path,
            held,
            generated_files,
            operation_deadline,
        )
        retained_binaries = {"test_executable": harness}
        binary_infos = {"test_executable": harness_info}
        helper_sources = {}
        result["cold_helper_copy_attempts"] = []
        for role, name in zip(("setup_helper", "runner_helper"), collector.HELPERS):
            copy_attempt = {"role": role, "helper": name}
            result["cold_helper_copy_attempts"].append(copy_attempt)
            sibling = harness_path.parent / (name + ".exe")
            actual, actual_info, original_info = materialize_cold_helper(
                owner,
                api_native,
                collector,
                cancellation,
                helper_artifacts,
                name,
                target,
                helper_producer,
                result["phase_attempts"][3],
                helper_raw,
                sibling,
                held,
                generated_files,
                copy_attempt,
                operation_deadline,
            )
            retained_binaries[role] = actual
            binary_infos[role] = actual_info
            helper_sources[role] = {
                "compiler_original": original_info,
                "create_only_sibling": actual_info,
                "copy_observation": copy_attempt,
            }
        result["original_cold_binaries"] = binary_infos
        result["original_helper_materialization"] = helper_sources
        cold_receipt = json_file(
            output / "COLD_BUILD_ORIGINAL_RECEIPT.json",
            {
                "schema": "hepta.windows_credentials.original_cold_binary_receipt.v1",
                "source_head": head,
                "source_tree": commit["tree"]["sha"],
                "input_sha256": digest(input_raw)["sha256"],
                "original_compiler_identity": result["actual_compiler_identity"],
                "metadata": digest(metadata_raw),
                "helper_compiler": digest(helper_raw),
                "library_compiler": digest(harness_raw),
                "source_before": result["source_before"],
                "tools_before": result["tools_before"],
                "dependency_inputs": result["dependency_inputs_before"],
                "original_commands": result["commands"][3:5],
                "shared_clock": result["cold_build_shared_clock"],
                "binaries": binary_infos,
                "helper_siblings": helper_sources,
                "provisional_until_final_source_and_native_and_platform_readback": True,
            },
        )
        # One90-second same-binary discovery envelope; neither list runs a body.
        inventory_started = time.monotonic()
        inventory_deadline = min(operation_deadline, inventory_started + 90)
        row = invoke(
            5,
            [str(harness_path), "--list", "--format=terse", "--color=never"],
            inventory_deadline,
        )
        all_list = retain_stdout(row, output / "LIBTEST_ALL.original.txt")
        row = invoke(
            6,
            [
                str(harness_path),
                "--list",
                "--ignored",
                "--format=terse",
                "--color=never",
            ],
            inventory_deadline,
        )
        ignored_list = retain_stdout(row, output / "LIBTEST_IGNORED.original.txt")
        result["inventory"] = collector.libtest_inventory(all_list, ignored_list)
        result["unit_controls_inventoried_not_executed"] = list(UNIT_INVENTORY_ONLY)
        need(
            time.monotonic() <= inventory_deadline,
            "two inventory observations exceeded shared90",
        )
        result["inventory_shared_clock"] = {
            "started_monotonic": inventory_started,
            "operation_deadline": inventory_deadline,
            "seconds": time.monotonic() - inventory_started,
            "native_test_bodies_executed": 0,
        }
        json_file(output / "COMPLETE_LIBRARY_INVENTORY.json", result["inventory"])
        need(
            len(result["commands"]) == len(PHASES) and not result["unlaunched_phases"],
            "all seven original preparation commands",
        )
        cancellation.check()
        need(
            time.monotonic() < operation_deadline,
            "no original work budget left for cases",
        )
        case_started = time.monotonic()
        case_deadline = min(operation_deadline, case_started + 540)
        context = {
            "schema": "hepta-windows-credential-native-context-v1",
            "root_execution_authorized": config["root_execution_authorized"],
            "root_new_candidate_regression_approved": config[
                "root_new_candidate_regression_approved"
            ],
            "root_original_first_attempt_cleared": config[
                "root_original_first_attempt_cleared"
            ],
            "root_admission_sha256": config["root_admission_sha256"],
            "root_source_acceptance_sha256": config["root_source_review_sha256"],
            "original_cold_build_receipt_sha256": cold_receipt["sha256"],
            "source_head": head,
            "source_tree": commit["tree"]["sha"],
            "run_nonce": os.urandom(16).hex(),
            "budget_transferred_from_E1_E6": 0,
            "old_failed_observations_retained": True,
            "test_names": list(EXACT_TESTS),
            "case_seconds": BUDGET["case_seconds"],
            "whole_engineering_seconds": WHOLE_SECONDS,
            "input_and_binaries_retained_before_cases": True,
            "native_harness_exact_tests_verified": True,
            "binary_pins": binary_infos,
            "owned_ephemeral_host_lifetime_review_required": True,
            **{role: str(pin.path) for role, pin in retained_binaries.items()},
            "protected_run_root": str(
                Path(os.environ["RUNNER_TEMP"]).absolute()
                / ("hepta-owned-credentials-private-" + run_id)
            ),
            "workspace": str(workspace),
            "caller_source": str(repo / CALLER_PATH),
            "caller_source_pin": config["source_sha256"][CALLER_PATH],
        }
        need(
            not Path(context["protected_run_root"]).exists(),
            "original protected account lifetime path already exists",
        )
        commands = [
            [
                str(harness_path),
                "--exact",
                name,
                "--show-output",
                "--test-threads=1",
                "--color=never",
                "--format=pretty",
            ]
            for name in EXACT_TESTS
        ]
        native_output = output / "exact-nine"
        native_output.mkdir(exist_ok=False)
        result["original_native_context"] = json_file(
            output / "NATIVE_CONTEXT.original.json", context
        )
        result["native_case_shared_clock"] = {
            "started_monotonic": case_started,
            "operation_deadline": case_deadline,
            "maximum_case_group_seconds": 540,
            "per_case_ceiling_seconds": 60,
            "same_original_work_and_cleanup_deadlines": True,
        }
        case_result = lifecycle.run_cases(
            owner,
            owner_raw,
            api_native,
            cancellation,
            context,
            retained_binaries,
            commands,
            child_env,
            native_output,
            original_start=start,
            operation_deadline=case_deadline,
            cleanup_deadline=cleanup_deadline,
            limits=config["owner_limits"],
        )
        result["original_credential_lifecycle"] = case_result
        need(
            case_result.get("successful") is True
            and case_result.get("native_all_nine_complete") is True,
            "original owned credential lifecycle did not complete all nine",
        )
        need(
            len(case_result.get("cases", [])) == 9
            and not case_result.get("unlaunched"),
            "exact-nine actual original case roster",
        )
        for case in case_result["cases"]:
            collector.command_terminal(case["native"])
        need(
            time.monotonic() <= case_deadline,
            "nine cases and their evidence exceeded the original540/work deadline",
        )
        cancellation.check()
        lifecycle.verify_original_runtime(owner, api_native, cancellation)
        need(
            time.monotonic() < operation_deadline,
            "all original work and diagnostics exceeded2100",
        )
        result["native_observation_pass"] = True
    except BaseException as error:
        result["errors"].append(repr(error))
    finally:
        result["prepared_before_first_native_launch"] = prepared
        if output is not None and output.is_dir():
            # Retention remains charged even on malformed input/bootstrap failure.
            if source_files:
                after = []
                try:
                    for path, pin in source_files:
                        info, _ = pin.read(deadline=cleanup_deadline)
                        after.append({"repo_path": path, **info})
                    result["source_after"] = json_file(
                        output / "SOURCE_AFTER.json", after
                    )
                    result["source_unchanged"] = all(
                        (
                            item["repo_path"],
                            item["sha256"],
                            item["git_blob"],
                            item["bytes"],
                        )
                        == (
                            previous["repo_path"],
                            previous["sha256"],
                            previous["git_blob"],
                            previous["bytes"],
                        )
                        for item, previous in zip(after, source_before)
                    ) and len(after) == len(source_before)
                    allowed = set()
                    expected = {path for path, _ in source_files}
                    result["no_untracked_source_after"] = (
                        enumerate_files(repo, allowed) == expected
                    )
                    need(
                        not (repo / ".git/info/attributes").exists()
                        and not (repo / ".git/objects/info/alternates").exists(),
                        "final Git configuration/object injection",
                    )
                    if "cargo_home" in locals():
                        need(
                            not (cargo_home / "config").exists()
                            and not (cargo_home / "config.toml").exists(),
                            "final external Cargo configuration injection",
                        )
                except BaseException as error:
                    result["source_unchanged"] = False
                    result["errors"].append("final source audit: " + repr(error))
            else:
                result["source_unchanged"] = False
            if tool_files:
                after = []
                try:
                    for name, pin in tool_files:
                        info, _ = pin.read(deadline=cleanup_deadline)
                        after.append({"tool": name, **info})
                    result["tools_after"] = json_file(
                        output / "TOOLS_AFTER.json", after
                    )
                    result["tools_unchanged"] = after == tool_before
                except BaseException as error:
                    result["tools_unchanged"] = False
                    result["errors"].append("final tool audit: " + repr(error))
            else:
                result["tools_unchanged"] = False
            result["materialized_name_audits"] = []
            for original in materialized_roots:
                try:
                    current_names = materialized_names(
                        Path(original["root"]), cancellation, cleanup_deadline
                    )
                    need(
                        current_names
                        == {row["relative_path"] for row in original["files"]},
                        "original materialized input file set changed",
                    )
                    result["materialized_name_audits"].append(
                        {
                            "root": original["root"],
                            "unchanged": True,
                            "file_count": len(current_names),
                        }
                    )
                except BaseException as error:
                    result["errors"].append(
                        "materialized input final names: " + repr(error)
                    )
                    result["materialized_name_audits"].append(
                        {
                            "root": original["root"],
                            "unchanged": False,
                            "error": repr(error),
                        }
                    )
            result["generated_input_after_read_attempts"] = 0
            for pin in generated_files:
                try:
                    pin.read(deadline=cleanup_deadline)
                    result["generated_input_after_read_attempts"] += 1
                except BaseException as error:
                    result["errors"].append(
                        "generated input/binary drift: " + repr(error)
                    )
            for pin in reversed(held):
                try:
                    pin.close()
                except BaseException as error:
                    result["errors"].append("held source/tool cleanup: " + repr(error))
            if cancellation is not None:
                # This is a standalone observer. Retain the pure-latch handlers
                # through durable RESULT and final stdout; the OS releases them
                # at observer exit. Restoring defaults here would reopen a
                # normal-signal gap before the original result is durable.
                result["cancellation"] = {
                    "count": cancellation.count,
                    "events": cancellation.events,
                    "handlers_retained_through_observer_exit": True,
                    "late_or_forced_platform_termination_requires_original_review": True,
                }
                if cancellation.count:
                    result["errors"].append("scope cancelled")
            result["elapsed_through_final_audit_seconds"] = time.monotonic() - start
            result["source_retention_within_original_reserve"] = (
                cleanup_deadline is not None and time.monotonic() <= cleanup_deadline
            )
            result["native_observation_pass"] = bool(
                result["native_observation_pass"]
                and not result["errors"]
                and result.get("source_unchanged")
                and result.get("tools_unchanged")
                and result.get("no_untracked_source_after")
                and result["source_retention_within_original_reserve"]
            )
            result["status"] = (
                "NATIVE_PASS_PENDING_FINAL_IO_AND_ORIGINAL_WHOLE_JOB_REVIEW"
                if result["native_observation_pass"]
                else "FAIL_OR_UNKNOWN"
            )
            result["original_total_budget_seconds"] = WHOLE_SECONDS
            result["upload_and_outer_job_not_yet_observed"] = True
            result["retention_clock_basis"] = "before durable RESULT and final stdout"
            result["final_io_acceptance"] = (
                "PENDING_AFTER_IO_RECORD_AND_ACTUAL_OBSERVER_EXIT"
            )
            result_pin = None
            tail_errors = []
            try:
                result_pin = json_file(output / "RESULT.json", result)
            except BaseException as error:
                tail_errors.append("RESULT retention: " + repr(error))
            after_result_io = time.monotonic()
            candidate = bool(
                result["native_observation_pass"]
                and result_pin is not None
                and cleanup_deadline is not None
                and after_result_io <= cleanup_deadline
                and not (cancellation is not None and cancellation.count)
            )
            try:
                print(
                    json.dumps(
                        {
                            "status": "FINAL_IO_PENDING"
                            if candidate
                            else "FAIL_OR_UNKNOWN",
                            "candidate_before_this_stdout": candidate,
                            "elapsed_after_RESULT_io_seconds": after_result_io - start,
                            "this_stdout_and_terminal_record_io_not_yet_observed": True,
                            "tail_errors": tail_errors,
                            "original_native_retention_limit_seconds": RETENTION_DEADLINE_SECONDS,
                            "original_whole_limit_seconds": WHOLE_SECONDS,
                        }
                    ),
                    flush=True,
                )
            except BaseException as error:
                tail_errors.append("final stdout: " + repr(error))
                candidate = False
            after_stdout_io = time.monotonic()
            candidate = bool(
                candidate
                and not tail_errors
                and cleanup_deadline is not None
                and after_stdout_io <= cleanup_deadline
                and not (cancellation is not None and cancellation.count)
            )
            after_io = {
                "schema": "hepta.windows_credentials.after_result_and_stdout_io.v1",
                "RESULT": result_pin,
                "elapsed_after_RESULT_io_seconds": after_result_io - start,
                "elapsed_after_final_stdout_io_seconds": after_stdout_io - start,
                "candidate_before_this_record_io": candidate,
                "tail_errors": tail_errors,
                "cancellation_count": cancellation.count
                if cancellation is not None
                else None,
                "original_native_retention_limit_seconds": RETENTION_DEADLINE_SECONDS,
                "this_record_io_and_actual_exit_still_require_outer_terminal": True,
                "original_whole_job_and_upload_review_required": True,
            }
            try:
                json_file(output / "AFTER_IO.json", after_io)
                final_io_pass = candidate
            except BaseException as error:
                final_io_pass = False
                try:
                    print(
                        json.dumps(
                            {
                                "fatal_after_io_retention_error": repr(error),
                                "native_pass": False,
                            }
                        ),
                        file=sys.stderr,
                        flush=True,
                    )
                except BaseException:
                    pass
            # No normal output after this actual post-fsync clock. The immutable
            # AFTER_IO record describes its own earlier boundary; the outer
            # bootstrap's original exit/clock remains required for acceptance.
            after_final_io = time.monotonic()
            final_io_pass = bool(
                final_io_pass
                and cleanup_deadline is not None
                and after_final_io <= cleanup_deadline
                and not (cancellation is not None and cancellation.count)
            )
        else:
            print(
                json.dumps({"status": "BOOTSTRAP_FAILURE", "errors": result["errors"]}),
                file=sys.stderr,
                flush=True,
            )
    if cancellation is not None and cancellation.count:
        return 1
    return (
        0
        if (
            final_io_pass
            and cleanup_deadline is not None
            and time.monotonic() <= cleanup_deadline
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
