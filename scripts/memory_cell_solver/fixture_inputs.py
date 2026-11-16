"""Read-only restoration of two explicitly pinned historical repository tasks."""

import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.error
import urllib.parse
import urllib.request

from edit_protocol import sha
from solver_common import file_identity, save
from solver_tasks import task_contract


REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
GOLD = {
    "codec": (
        "d847bb289159d8857f53cdcf5de79636e18df105",
        "qualification/ndu-dmgp-shadow/run_codec_acceptance.py",
        "9e98fd63845da16eed5aed1401c6de22ab3ee010f413eb5f79362be32d2b1f6a",
    ),
}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """A restoration credential is valid only for the original repository API."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def historical_file(repo, commit, path):
    attempt = subprocess.run(
        ["git", "show", f"{commit}:{path}"], cwd=repo, capture_output=True
    )
    if attempt.returncode == 0:
        return attempt.stdout, {
            "transport": "local_git_object",
            "commit": commit,
            "path": path,
        }
    token = os.environ.get("GITHUB_TOKEN")
    if not token or os.environ.get("GITHUB_REPOSITORY") != REPOSITORY:
        raise ValueError(
            "original object absent; authorized repository restoration token unavailable"
        )
    url = (
        "https://api.github.com/repos/"
        + REPOSITORY
        + "/contents/"
        + urllib.parse.quote(path, safe="/")
        + "?ref="
        + commit
    )
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "User-Agent": "hepta-memory-source-restore",
        },
    )
    try:
        with urllib.request.build_opener(NoRedirect).open(
            request, timeout=60
        ) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as error:
        if 300 <= error.code < 400:
            raise ValueError(
                "authenticated repository restoration redirect refused"
            ) from None
        raise
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("repository restoration response exceeds byte budget")
    value = json.loads(body)
    if (
        type(value) is not dict
        or value.get("type") != "file"
        or value.get("encoding") != "base64"
        or value.get("path") != path
        or type(value.get("content")) is not str
        or type(value.get("size")) is not int
    ):
        raise ValueError("repository response did not name the exact file")
    raw = base64.b64decode("".join(value["content"].split()), validate=True)
    blob = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
    if value["size"] != len(raw) or value.get("sha") != blob:
        raise ValueError("repository response bytes differ from Git blob metadata")
    return raw, {
        "transport": "authorized_repository_contents_api",
        "commit": commit,
        "path": path,
        "git_blob": value["sha"],
        "response_size": value["size"],
    }


def generated_ruff_control(fixture, spec, directory, ruff):
    """A tool-generated qualification control, never a claimed Git blob."""
    from test_ruff_executor import GOLD_SHA256

    gold = directory / "qualification-only-known-fix.py"
    gold.write_bytes((fixture / spec["target"]).read_bytes())
    argv = [
        str(ruff),
        "check",
        "--isolated",
        "--no-cache",
        "--select",
        "F401,E731",
        "--fix",
        "--unsafe-fixes",
        str(gold),
    ]
    before = file_identity(gold)
    result = subprocess.run(argv, capture_output=True, timeout=60)
    (directory / "control-generation.stdout").write_bytes(result.stdout)
    (directory / "control-generation.stderr").write_bytes(result.stderr)
    receipt = {
        "kind": "generated_qualification_only_control",
        "argv": argv,
        "returncode": result.returncode,
        "input": before,
        "tool": file_identity(ruff),
        "output": file_identity(gold),
        "original_source_commit": spec["failing_commit"],
        "original_source_path": spec["target"],
        "is_git_source_blob": False,
    }
    save(directory / "control-generation.json", receipt)
    if result.returncode or receipt["output"]["sha256"] != GOLD_SHA256:
        raise ValueError("generated Ruff positive control differs from qualified bytes")
    return gold, receipt


def restore_inputs(repo, task, directory, ruff=None):
    spec, contract_sha = task_contract(task)
    directory = Path(directory)
    fixture = directory / "fixture"
    fixture.mkdir(parents=True, exist_ok=False)
    rows = []
    for path, expected in spec["files"].items():
        raw, receipt = historical_file(repo, spec["failing_commit"], path)
        if {"bytes": len(raw), "sha256": sha(raw)} != expected:
            raise ValueError("historical source pin mismatch: " + path)
        destination = fixture / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
        rows.append({**receipt, **expected})
    if task == "ruff":
        gold, resolution = generated_ruff_control(fixture, spec, directory, ruff)
    else:
        commit, path, expected = GOLD[task]
        raw, receipt = historical_file(repo, commit, path)
        if sha(raw) != expected:
            raise ValueError("historical positive-control source pin mismatch")
        gold = directory / "qualification-only-known-fix.py"
        gold.write_bytes(raw)
        resolution = {**receipt, "sha256": expected}
    save(
        directory / "source-acquisition.json",
        {
            "contract_sha256": contract_sha,
            "original_sources": rows,
            "qualification_only_resolution": resolution,
            "resolution_is_solver_input": False,
            "native_source_authorization_qualified": False,
        },
    )
    return fixture, gold
