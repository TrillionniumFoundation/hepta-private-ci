"""Read only the source-bound output of the original schema refresh job."""

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

ARCHIVE_PATH = (
    "codex-rs/app-server-protocol/schema/precomputed/app-server-exports-experimental.json.zst"
)
COMMANDS = [
    ("stable", ["just", "write-app-server-schema"]),
    ("experimental", ["just", "write-app-server-schema", "--experimental"]),
    ("owning-tests", ["just", "test", "-p", "codex-app-server-protocol"]),
]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require_hex(value: object, digits: int, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(f"[0-9a-f]{{{digits}}}", value) is None:
        raise ValueError(f"invalid {label}")
    return value


def load_evidence(
    evidence: Path,
    source_commit: str,
    source_tree: str,
    archive_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Require actual successful generation and owning tests for the exact source."""
    require_hex(source_commit, 40, "source commit")
    require_hex(source_tree, 40, "source tree")
    require_hex(archive_sha256, 64, "experimental archive SHA256")
    source_bytes = (evidence / "source.json").read_bytes()
    manifest_bytes = (evidence / "generated-manifest.json").read_bytes()
    commands_bytes = (evidence / "commands.json").read_bytes()
    tool_bytes = (evidence / "tool-versions.txt").read_bytes()
    source = json.loads(source_bytes)
    manifest = json.loads(manifest_bytes)
    commands = json.loads(commands_bytes)
    if source.get("source_sha") != source_commit or source.get("source_tree") != source_tree:
        raise ValueError("schema evidence belongs to a different source commit or tree")
    if (
        manifest.get("source_sha") != source_commit
        or manifest.get("unexpected_paths") != []
        or type(manifest.get("diff_check_exit_code")) is not int
        or manifest["diff_check_exit_code"] != 0
    ):
        raise ValueError("schema generation changed its source or failed its original checks")
    if not isinstance(commands, list) or len(commands) != len(COMMANDS):
        raise ValueError("incomplete original schema command receipts")
    for command, (name, argv) in zip(commands, COMMANDS, strict=True):
        if (
            command.get("name") != name
            or command.get("argv") != argv
            or command.get("cwd") != "codex-rs"
            or type(command.get("exit_code")) is not int
            or command["exit_code"] != 0
        ):
            raise ValueError(f"original schema command did not succeed: {name}")
    archive = (evidence / "generated" / ARCHIVE_PATH).read_bytes()
    records = [
        entry for entry in manifest.get("generated_files", []) if entry.get("path") == ARCHIVE_PATH
    ]
    if (
        len(records) != 1
        or records[0].get("size") != len(archive)
        or records[0].get("sha256") != archive_sha256
        or sha256(archive) != archive_sha256
    ):
        raise ValueError("experimental archive does not match its source-bound manifest")
    # Decompress the already hashed bytes, not a subsequently reopened pathname.
    # zstd is an explicit generator prerequisite, never a replacement schema source.
    decoded = subprocess.run(
        ["zstd", "--decompress", "--stdout"],
        input=archive,
        capture_output=True,
        check=True,
    ).stdout
    exports = json.loads(decoded)
    if set(exports) != {"typescript", "json_schema", "internal_json_schema"}:
        raise ValueError("unexpected original precomputed export format")
    if exports["internal_json_schema"] != {}:
        raise ValueError("expected experimental exports, not stable/internal exports")
    server_text = exports["json_schema"]["ServerNotification.json"]
    if not isinstance(server_text, str):
        raise ValueError("ServerNotification export is not JSON text")
    provenance = {
        "source_commit": source_commit,
        "source_tree": source_tree,
        "experimental_archive_sha256": archive_sha256,
        "server_notification_sha256": sha256(server_text.encode()),
        "source_receipt_sha256": sha256(source_bytes),
        "generated_manifest_sha256": sha256(manifest_bytes),
        "commands_receipt_sha256": sha256(commands_bytes),
        "tool_versions_sha256": sha256(tool_bytes),
        "run_id": source.get("run_id"),
        "run_attempt": source.get("run_attempt"),
    }
    return json.loads(server_text), provenance
