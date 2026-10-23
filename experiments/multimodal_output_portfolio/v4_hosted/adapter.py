"""Host the unchanged v4 confirmation; infrastructure and scientific claims are separate."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import time
import traceback
import venv
import zipfile

SCIENCE = "7713023e604746a3947e0e0e2d31e8eaef6e48b1"
PROTOCOL = "4f90f435e3ce419a09f42412af1fc6fe3515f3c198e5e8555115b1996c1aab0b"
INPUTS = "e06e58460e0d711f65920b9f1900280553a2ff39f1cef6fdc31ee7fbb495c9db"
BASE = "experiments/multimodal_output_portfolio/"


def require(value, message):
    if not value:
        raise RuntimeError(message)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def relative(value):
    path = PurePosixPath(value)
    require(isinstance(value, str) and value and str(path) == value and not path.is_absolute()
            and ".." not in path.parts and "\\" not in value and ":" not in value
            and "\0" not in value and len(value) < 512, "unsafe relative path")
    return path


def git(repo, *arguments):
    return subprocess.check_output(["git", *arguments], cwd=repo, stderr=subprocess.PIPE,
                                   env={**os.environ, "GIT_NO_LAZY_FETCH": "1"}, timeout=60).decode().strip()


def clean_source(repo):
    head, dirty = git(repo, "rev-parse", "HEAD"), git(repo, "status", "--porcelain", "--untracked-files=all")
    require(head == SCIENCE and not dirty, "science HEAD or clean checkout differs")
    require(digest(repo / BASE / "v4/protocol.json") == PROTOCOL, "science protocol differs")
    return {"head": head, "clean": True, "protocol_sha256": PROTOCOL}


def restore(manifest_path, destination):
    """Reconstruct bounded raw chunks and extract only hashed regular members."""
    manifest_path, destination = Path(manifest_path), Path(destination)
    m = json.loads(manifest_path.read_text())
    require(m["schema"] == "hepta.v4.hosted-inputs.v1", "input schema")
    require(0 < m["zip"]["bytes"] <= 64 * 1024**2 and 0 < len(m["chunks"]) <= 128, "archive bounds")
    rows = {str(relative(row["path"])): row for row in m["files"]}
    require(0 < len(rows) == len(m["files"]) <= 256, "unique bounded member inventory")
    require(sum(row["bytes"] for row in rows.values()) == m["total_uncompressed_bytes"] <= 32 * 1024**2,
            "expanded size bound")
    require(all(type(row["bytes"]) is int and row["bytes"] >= 0 and row["unix_mode"] in (0o644, 0o755)
                for row in rows.values()), "member size or mode")
    destination.mkdir(mode=0o700)
    archive = destination / "reconstructed.zip"
    offset, chunk_names = 0, set()
    with archive.open("xb") as stream:
        for index, row in enumerate(m["chunks"]):
            name = str(relative(row["path"]))
            require(name not in chunk_names and row["index"] == index and row["offset"] == offset
                    and 0 < row["bytes"] <= 524288, "ordered unique chunks")
            chunk_names.add(name)
            source = manifest_path.parent / name
            require(source.is_file() and all(not (manifest_path.parent / PurePosixPath(name).parents[i]).is_symlink()
                    for i in range(len(PurePosixPath(name).parents))) and not source.is_symlink(), "regular chunk required")
            data = source.read_bytes()
            require(len(data) == row["bytes"] and hashlib.sha256(data).hexdigest() == row["sha256"]
                    and hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
                    == row["git_blob_sha1"], "chunk byte or Git blob mismatch")
            stream.write(data)
            offset += len(data)
    require(offset == m["zip"]["bytes"] and digest(archive) == m["zip"]["sha256"], "archive byte mismatch")
    extracted = destination / "extracted"
    extracted.mkdir(mode=0o700)
    with zipfile.ZipFile(archive) as source:
        infos = source.infolist()
        require(len(infos) == m["zip"]["member_count"] == len(rows)
                and {info.filename for info in infos} == set(rows), "exact ZIP inventory")
        for info in infos:
            row = rows[str(relative(info.filename))]
            require(not info.is_dir() and not info.flag_bits & 1 and info.create_system == 3
                    and stat.S_IFMT(info.external_attr >> 16) == stat.S_IFREG
                    and stat.S_IMODE(info.external_attr >> 16) == row["unix_mode"]
                    and info.file_size == row["bytes"], "regular unencrypted member metadata")
            target = extracted / info.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            size, hashed = 0, hashlib.sha256()
            with source.open(info) as reader, target.open("xb") as writer:
                while block := reader.read(1024 * 1024):
                    size += len(block)
                    require(size <= row["bytes"], "member exceeds declared size")
                    writer.write(block)
                    hashed.update(block)
            require(size == row["bytes"] and hashed.hexdigest() == row["sha256"], "member SHA256 mismatch")
            target.chmod(row["unix_mode"])
    return m, extracted


def execute(request_repo, science_repo, output):
    request_repo, science_repo, output = map(lambda p: Path(p).resolve(), (request_repo, science_repo, output))
    started, code = time.perf_counter(), 1
    receipt = {"schema": "hepta.v4.hosted-adapter.v1", "started_at_utc": datetime.now(timezone.utc).isoformat(),
               "stage": "context", "commands": [], "source_checks": [], "formal_integrity_passed": False,
               "mechanism_gate_passed": False, "primary_superiority_passed": False,
               "dedicated_runner_verified": False, "production_claim": False, "external_actions_assignment_verified": False}
    receipt_path = output / "adapter-receipt.json"
    require(output.is_dir() and not receipt_path.exists(), "new allocated evidence directory required")
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1",
           "PYTHONNOUSERSITE": "1", "PIP_CONFIG_FILE": os.devnull}

    def command(arguments, label, timeout):
        begin, status = time.perf_counter(), None
        try:
            with (output / (label + ".stdout.log")).open("xb") as stdout, (output / (label + ".stderr.log")).open("xb") as stderr:
                status = subprocess.run(list(map(str, arguments)), cwd=science_repo, env=env,
                                        stdout=stdout, stderr=stderr, timeout=timeout).returncode
            require(status == 0, label + " failed; original stdout/stderr retained")
        finally:
            receipt["commands"].append({"label": label, "argv": list(map(str, arguments)), "returncode": status,
                                        "wall_seconds": time.perf_counter() - begin})

    try:
        receipt["context"] = {key: os.environ.get(key) for key in
                              ("GITHUB_REPOSITORY", "GITHUB_REF", "GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT",
                               "GITHUB_JOB", "RUNNER_NAME", "RUNNER_ENVIRONMENT", "RUNNER_OS", "RUNNER_ARCH")}
        require(os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("GITHUB_EVENT_NAME") == "push"
                and os.environ.get("GITHUB_REPOSITORY") == "TrillionniumFoundation/hepta-private-ci"
                and os.environ.get("GITHUB_REF") == "refs/heads/research/ndu-feedback-generation-v3"
                and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
                and os.environ.get("RUNNER_OS") == "Linux" and os.environ.get("RUNNER_ARCH") == "X64"
                and sys.version_info[:2] == (3, 12), "registered hosted CPU context")
        require(git(request_repo, "rev-parse", "HEAD") == os.environ["GITHUB_SHA"]
                and not git(request_repo, "status", "--porcelain", "--untracked-files=all"), "request checkout binding")
        receipt["input_assets_git_commit"] = os.environ["GITHUB_SHA"]
        infra = request_repo / BASE / "v4_hosted"
        request_bytes = (infra / "RUN_REQUEST.json").read_bytes()
        (output / "request.json").write_bytes(request_bytes)
        request = json.loads(request_bytes)
        require(request["schema"] == "hepta.v4.hosted-confirmation.request.v1"
                and request["science_commit"] == SCIENCE and request["protocol_sha256"] == PROTOCOL
                and request["manifest_relative_path"] == "inputs/manifest.json"
                and request["inputs_manifest_sha256"] == INPUTS and request["development"] is False,
                "fixed full-confirmation request")
        manifest_path = infra / request["manifest_relative_path"]
        require(digest(manifest_path) == INPUTS, "pinned input manifest")
        (output / "input-manifest.json").write_bytes(manifest_path.read_bytes())
        receipt["adapter_sha256"] = digest(Path(__file__))
        receipt["source_checks"].append(clean_source(science_repo))
        receipt["stage"] = "input_verification"
        suffix = os.environ["GITHUB_RUN_ID"] + "-" + os.environ["GITHUB_RUN_ATTEMPT"]
        require(all(part.isdigit() for part in suffix.split("-")) and suffix.count("-") == 1, "numeric attempt identity")
        manifest, inputs = restore(manifest_path, Path(os.environ["RUNNER_TEMP"]) / ("ndu-v4-inputs-" + suffix))
        build_path = science_repo / BASE / "v4/evidence/native_build_final.json"
        require(manifest["science_commit"] == SCIENCE and manifest["protocol_sha256"] == PROTOCOL
                and manifest["native_build_receipt_sha256"] == digest(build_path)
                and manifest["zip"]["sha256"] == request["inputs_archive_sha256"], "scientific input binding")
        binary, source_run, fixture = inputs / "native/ndu-modality-portfolio", inputs / "source-run", inputs / "bridge-fixture"
        require(digest(binary) == json.loads(build_path.read_text())["binary"]["sha256"], "original native binary")
        protocol = json.loads((science_repo / BASE / "v4/protocol.json").read_text())
        for item in protocol["source_checkpoints"].values():
            path = source_run / item["path"]
            require(path.stat().st_size == item["bytes"] and digest(path) == item["sha256"], "original checkpoint")
        receipt["verified_inputs"] = {"manifest_sha256": INPUTS, "archive_sha256": manifest["zip"]["sha256"],
                                      "files": len(manifest["files"]), "chunks": len(manifest["chunks"])}
        receipt["stage"] = "dependencies"
        environment = Path(os.environ["RUNNER_TEMP"]) / ("ndu-v4-python-" + suffix)
        require(not environment.exists(), "new Python environment required")
        venv.EnvBuilder(with_pip=True).create(environment)
        python = environment / "bin/python"
        pip = [python, "-m", "pip", "--isolated", "install", "--no-input", "--no-cache-dir", "--disable-pip-version-check",
               "--only-binary=:all:", "--retries", "2", "--timeout", "30"]
        command([*pip, "--index-url", "https://pypi.org/simple", "--report", output / "numpy-install.json", "numpy==1.26.4"], "numpy-install", 600)
        command([*pip, "--index-url", "https://download.pytorch.org/whl/cpu", "--report", output / "torch-install.json", "torch==2.5.1+cpu"], "torch-install", 900)
        command([python, "-m", "pip", "freeze"], "pip-freeze", 60)
        receipt["stage"] = "formal_producer"
        receipt["source_checks"].append(clean_source(science_repo))
        command([python, science_repo / BASE / "v4/run.py", "--output", output / "producer",
                 "--source-run", source_run, "--native-binary", binary], "producer", 1800)
        receipt["source_checks"].append(clean_source(science_repo))
        receipt["stage"] = "independent_audit"
        command([python, science_repo / BASE / "v4/evidence/audit_confirmation.py", "--repo", science_repo,
                 "--run", output / "producer", "--source-run", source_run, "--native-binary", binary,
                 "--bridge-fixture", fixture, "--output", output / "independent-review.json"], "audit", 1800)
        review = json.loads((output / "independent-review.json").read_text())
        require(review["integrity_passed"] is True and review["development"] is False and review["confirmatory"] is True,
                "full confirmation integrity review required")
        receipt.update(formal_integrity_passed=True, mechanism_gate_passed=review["mechanism_gate_passed"],
                       primary_superiority_passed=review["primary_superiority_passed"], stage="complete")
        code = 0
    except Exception:
        receipt["traceback"] = traceback.format_exc()
    finally:
        try:
            receipt["source_checks"].append(clean_source(science_repo))
        except Exception:
            receipt["source_final_check_error"] = traceback.format_exc()
            receipt.update(formal_integrity_passed=False, mechanism_gate_passed=False, primary_superiority_passed=False)
            code = 1
        receipt["audit_execution"] = ("attempted" if any(item["label"] == "audit" for item in receipt["commands"])
                                      else "not_executed; see retained failure stage and traceback")
        receipt.update(status="completed" if code == 0 else "failed", exit_code=code,
                       wall_seconds=time.perf_counter() - started, finished_at_utc=datetime.now(timezone.utc).isoformat(),
                       execution_scope="GitHub-hosted CPU; frozen producer's internal local-cpu label is unchanged.")
        write(receipt_path, receipt)
        print(json.dumps({key: receipt[key] for key in ("status", "stage", "formal_integrity_passed", "mechanism_gate_passed", "primary_superiority_passed")}))
    return code


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("request-repo", "science-repo", "output"):
        parser.add_argument("--" + option, required=True, type=Path)
    args = parser.parse_args()
    sys.exit(execute(args.request_repo, args.science_repo, args.output))
