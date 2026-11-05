#!/usr/bin/python3
"""Shared identity, evidence and OCI checks for the isolated image workflow."""

import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import signal
import subprocess
import tarfile
import time
import traceback

REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
BRANCH = "refs/heads/codex/rbe-openssh-image-r2-20261105"
WORKFLOW = ".github/workflows/hepta-rbe-openssh-image.yml"
PACKAGE = ".github/rbe-openssh"
REGISTRY_REPOSITORY = "trillionniumfoundation/hepta-rbe-openssh"
BASES = {
    "amd64": "docker.io/mbolin491/codex-bazel@sha256:0a8e56bfaa3b2e5279db0d3bb2d62b44ba5e5d63a37d97eb8790f49da570af70",
    "arm64": "docker.io/mbolin491/codex-bazel@sha256:136487cc4b7cf6f1021816ca18ed00896daed98404ea91dc4d6dd9e9d1cf9564",
}
CONFIG_FIELDS = (
    "User",
    "Env",
    "Entrypoint",
    "Cmd",
    "WorkingDir",
    "ExposedPorts",
    "Volumes",
    "StopSignal",
    "Healthcheck",
    "OnBuild",
    "Shell",
)
SHA = re.compile(r"[0-9a-f]{64}")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha_file(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def json_write(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


class Evidence:
    def __init__(self, mode, architecture, seconds, deadline_unix_ns=None):
        self.started = time.monotonic()
        now_unix_ns = time.time_ns()
        if deadline_unix_ns is None:
            self.deadline_unix_ns = now_unix_ns + int(seconds * 1_000_000_000)
        else:
            self.deadline_unix_ns = deadline_unix_ns
            seconds = min(seconds, (deadline_unix_ns - now_unix_ns) / 1_000_000_000)
        self.deadline = self.started + seconds
        self.mode, self.arch = mode, architecture
        require(architecture in BASES, "unexpected architecture")
        require(
            platform.machine() == {"amd64": "x86_64", "arm64": "aarch64"}[architecture],
            "native matching architecture required",
        )
        temporary = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
        self.root = Path(os.environ["RBE_EVIDENCE"])
        require(
            self.root.is_absolute() and self.root.parent.resolve() == temporary,
            "evidence directory must be a direct owned runner temporary child",
        )
        self.root.mkdir(mode=0o700)
        self.logs, self.state = [], {"status": "in-progress", "mode": mode}
        try:

            def expired(signum, frame):
                raise TimeoutError("original image preparation deadline reached")

            signal.signal(signal.SIGALRM, expired)
            signal.setitimer(signal.ITIMER_REAL, self.remaining())
            self.identity = self.source_identity()
        except BaseException as error:
            self.finish(error)
            raise
        self.state.update(
            identity=self.identity,
            architecture=architecture,
            deadline_unix_ns=self.deadline_unix_ns,
        )

    def source_identity(self):
        require(os.environ["GITHUB_REPOSITORY"] == REPOSITORY, "repository mismatch")
        require(os.environ["GITHUB_REF"] == BRANCH, "reviewed branch mismatch")
        require(
            os.environ["GITHUB_EVENT_NAME"] in ("push", "workflow_dispatch"),
            "event mismatch",
        )
        commit = os.environ["GITHUB_SHA"]
        require(re.fullmatch(r"[0-9a-f]{40}", commit), "invalid source SHA")
        require(
            os.environ["GITHUB_WORKFLOW_REF"]
            == REPOSITORY + "/" + WORKFLOW + "@" + BRANCH,
            "workflow source mismatch",
        )
        for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"):
            require(
                re.fullmatch(r"[1-9][0-9]*", os.environ[key]), "invalid run identity"
            )
        if os.environ["GITHUB_EVENT_NAME"] == "workflow_dispatch":
            event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
            require(
                event["inputs"]["source_sha"] == commit, "dispatch source SHA mismatch"
            )
        require(
            self.command(["git", "rev-parse", "HEAD"]).decode().strip() == commit,
            "checkout source mismatch",
        )
        require(
            self.command(["git", "status", "--porcelain=v1"]) == b"", "source is dirty"
        )
        tree = self.command(["git", "rev-parse", "HEAD^{tree}"]).decode().strip()
        files = {}
        for name in (
            "image_prepare.py",
            "build_image.py",
            "publish_image.py",
            "common.py",
            "Dockerfile",
        ):
            path = Path(PACKAGE) / name
            require(
                path.is_file() and not path.is_symlink(),
                "source input must be a regular file",
            )
            files[str(path)] = {"bytes": path.stat().st_size, "sha256": sha_file(path)}
        files[WORKFLOW] = {
            "bytes": Path(WORKFLOW).stat().st_size,
            "sha256": sha_file(Path(WORKFLOW)),
        }
        return {
            "repository": REPOSITORY,
            "commit": commit,
            "tree": tree,
            "ref": BRANCH,
            "run_id": os.environ["GITHUB_RUN_ID"],
            "attempt": os.environ["GITHUB_RUN_ATTEMPT"],
            "source_files": files,
        }

    def remaining(self, cleanup=False):
        value = self.deadline - time.monotonic() - (0 if cleanup else 30)
        require(value > 0, "image workflow execution deadline exhausted")
        return value

    def command(
        self, argv, *, capture=True, environment=None, cleanup=False, success=True
    ):
        if cleanup:
            signal.setitimer(signal.ITIMER_REAL, self.remaining(cleanup=True))
        self.remaining(cleanup=cleanup)
        name = "command-%03d" % len(self.logs)
        out, err = self.root / (name + ".stdout"), self.root / (name + ".stderr")
        entry = {
            "argv": argv,
            "stdout": out.name,
            "stderr": err.name,
            "status": "requested",
        }
        self.logs.append(entry)
        env = os.environ.copy()
        for key in (
            "GH_TOKEN",
            "GITHUB_TOKEN",
            "ACTIONS_RUNTIME_TOKEN",
            "DOCKER_AUTH_CONFIG",
        ):
            env.pop(key, None)
        if environment:
            env.update(environment)
        started = time.monotonic()
        with out.open("xb") as stdout, err.open("xb") as stderr:
            process = subprocess.Popen(
                argv,
                stdout=stdout,
                stderr=stderr,
                env=env,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
            try:
                code = process.wait(timeout=self.remaining(cleanup=cleanup))
                entry.update(
                    status="completed",
                    exit_code=code,
                    capture_complete=True,
                    terminal_confirmed=True,
                )
            except BaseException as error:
                entry.update(
                    status="interrupted",
                    pid=process.pid,
                    exception_type=type(error).__name__,
                    capture_complete=False,
                    terminal_confirmed=False,
                )
                try:
                    observed = process.poll()
                    if observed is None:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            # A missing group is not a terminal observation.
                            pass
                        hard_remaining = self.deadline - time.monotonic()
                        require(
                            hard_remaining > 0,
                            "no original deadline remains for child termination",
                        )
                        signal.setitimer(signal.ITIMER_REAL, hard_remaining)
                        observed = process.wait(timeout=hard_remaining)
                    entry.update(exit_code=observed, terminal_confirmed=True)
                except BaseException as cleanup_error:
                    entry.update(
                        terminal_unknown=True,
                        cleanup_exception_type=type(cleanup_error).__name__,
                    )
                    self.state["terminal_unknown"] = True
                raise
            finally:
                stdout.flush()
                stderr.flush()
                os.fsync(stdout.fileno())
                os.fsync(stderr.fileno())
                entry["elapsed_seconds"] = time.monotonic() - started
        for file in (out, err):
            entry[file.suffix[1:] + "_bytes"] = file.stat().st_size
            entry[file.suffix[1:] + "_sha256"] = sha_file(file)
        if success:
            require(code == 0, "command failed; full evidence: " + name)
        if capture:
            require(
                out.stat().st_size <= 8 * 1024 * 1024,
                "captured command output exceeds bound",
            )
            return out.read_bytes()
        return code

    def finish(self, error=None):
        signal.setitimer(signal.ITIMER_REAL, 0)
        late = error is None and time.monotonic() >= self.deadline
        unknown = error is None and self.state.get("terminal_unknown", False)
        if late:
            error = TimeoutError(
                "original image preparation deadline exhausted at terminal receipt"
            )
        elif unknown:
            error = RuntimeError(
                "original child terminal state remains unknown; qualification is fenced"
            )
        self.state.update(
            status="failed-not-qualified" if error else self.state["status"],
            elapsed_seconds=time.monotonic() - self.started,
            commands=self.logs,
            original_tests_qualified=False,
        )
        if error:
            self.state["exception"] = {
                "type": type(error).__name__,
                "message": str(error),
                "traceback": traceback.format_exc(),
            }
        json_write(self.root / "receipt.json", self.state)
        print(
            json.dumps(
                {
                    "mode": self.mode,
                    "status": self.state["status"],
                    "evidence": str(self.root),
                }
            ),
            flush=True,
        )
        if late or unknown:
            raise error


def unpack_oci(archive, directory):
    require(archive.stat().st_size <= 4 * 1024**3, "OCI archive exceeds proposal bound")
    directory.mkdir(mode=0o700)
    total, seen = 0, set()
    with tarfile.open(archive, "r:") as bundle:
        for item in bundle:
            name = item.name.removeprefix("./").rstrip("/")
            require(name not in seen, "duplicate OCI archive member")
            seen.add(name)
            if item.isdir():
                require(name in ("", "blobs", "blobs/sha256"), "unknown OCI directory")
                continue
            require(
                item.isfile()
                and (
                    name in ("index.json", "oci-layout")
                    or re.fullmatch(r"blobs/sha256/[0-9a-f]{64}", name)
                ),
                "unsafe OCI member",
            )
            total += item.size
            require(
                item.size <= 1024**3 and total <= 4 * 1024**3,
                "OCI payload bound exceeded",
            )
            target = directory / name
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with bundle.extractfile(item) as source, target.open("xb") as destination:
                copied = 0
                for data in iter(lambda: source.read(1024 * 1024), b""):
                    destination.write(data)
                    copied += len(data)
            require(copied == item.size, "OCI member truncated")
            if name.startswith("blobs/"):
                require(
                    sha_file(target) == name.rsplit("/", 1)[1],
                    "OCI blob digest mismatch",
                )
    require(
        json.loads((directory / "oci-layout").read_text())
        == {"imageLayoutVersion": "1.0.0"},
        "unknown OCI layout",
    )
    index = json.loads((directory / "index.json").read_text())
    require(
        index.get("schemaVersion") == 2 and len(index.get("manifests", [])) == 1,
        "exactly one platform manifest required",
    )
    descriptor = index["manifests"][0]
    manifest_raw = descriptor_bytes(directory, descriptor)
    manifest = json.loads(manifest_raw)
    require(
        manifest.get("schemaVersion") == 2
        and manifest.get("mediaType") == "application/vnd.oci.image.manifest.v1+json",
        "unexpected OCI manifest media type",
    )
    config = json.loads(descriptor_bytes(directory, manifest["config"]))
    require(
        manifest["config"]["mediaType"] == "application/vnd.oci.image.config.v1+json",
        "unexpected OCI config media type",
    )
    for layer in manifest["layers"]:
        descriptor_path(directory, layer)
    return descriptor, manifest, manifest_raw, config


def descriptor_path(directory, descriptor):
    require(DIGEST.fullmatch(descriptor["digest"]) is not None, "invalid blob digest")
    path = directory / "blobs/sha256" / descriptor["digest"][7:]
    require(
        path.is_file() and path.stat().st_size == descriptor["size"],
        "blob size mismatch",
    )
    return path


def descriptor_bytes(directory, descriptor):
    path = descriptor_path(directory, descriptor)
    require(path.stat().st_size <= 8 * 1024 * 1024, "OCI JSON exceeds bound")
    return path.read_bytes()


def image_checks(identity, arch, config, baseline):
    require(
        config["architecture"] == arch and config["os"] == "linux",
        "image platform mismatch",
    )
    require(
        baseline["Architecture"] == arch and baseline["Os"] == "linux",
        "base platform mismatch",
    )
    original, derived = baseline["Config"], config["config"]
    for field in CONFIG_FIELDS:
        require(
            original.get(field) == derived.get(field),
            "baseline image config changed: " + field,
        )
    require(
        derived["User"] == "ubuntu" and derived["WorkingDir"] == "/workspace",
        "original image user/workdir required",
    )
    expected = {
        "org.opencontainers.image.source": "https://github.com/" + REPOSITORY,
        "org.opencontainers.image.revision": identity["commit"],
        "io.hepta.source.tree": identity["tree"],
        "io.hepta.source.run": identity["run_id"] + "-" + identity["attempt"],
    }
    for key, value in (original.get("Labels") or {}).items():
        require(
            key not in expected or expected[key] == value,
            "baseline reserved label conflicts",
        )
        expected[key] = value
    require(
        derived.get("Labels") == expected,
        "image labels differ from exact source identity",
    )
    old_layers = baseline["RootFS"]["Layers"]
    new_layers = config["rootfs"]["diff_ids"]
    require(
        config["rootfs"]["type"] == "layers"
        and old_layers
        and new_layers[: len(old_layers)] == old_layers
        and len(new_layers) > len(old_layers),
        "baseline rootfs diff-id prefix was replaced",
    )


def verify_diff_ids(directory, manifest, config):
    layers, expected = manifest["layers"], config["rootfs"]["diff_ids"]
    require(len(layers) == len(expected), "manifest layer count differs from rootfs")
    for descriptor, wanted in zip(layers, expected):
        path = descriptor_path(directory, descriptor)
        media = descriptor["mediaType"]
        require(
            media
            in (
                "application/vnd.oci.image.layer.v1.tar",
                "application/vnd.oci.image.layer.v1.tar+gzip",
            ),
            "unsupported layer compression",
        )
        opener = gzip.open if media.endswith("+gzip") else open
        h = hashlib.sha256()
        with opener(path, "rb") as stream:
            for data in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(data)
        require(
            "sha256:" + h.hexdigest() == wanted,
            "actual uncompressed layer differs from diff-id",
        )
