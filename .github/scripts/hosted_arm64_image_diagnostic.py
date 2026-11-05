"""Run the unchanged native ARM image builder on a separate exact checkout."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import sys
import time


REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
BRANCH = "diagnostics/p1-arm64-image-20261105-ba4b"
DRIVER = ".github/scripts/hosted_arm64_image_diagnostic.py"
WORKFLOW = ".github/workflows/hepta-arm64-image-diagnostic.yml"
MANIFEST = ".github/fixtures/hosted-arm64-image-source.json"
INPUTS = {
    ".github/workflows/Dockerfile.bazel",
    ".github/scripts/build-bazel-image.sh",
    ".github/scripts/smoke-bazel-openssh.sh",
    ".github/scripts/bazel_image_identity.py",
}
SENTINEL = "PASS: default UID 1000; signature accepted; altered payload and wrong namespace rejected"
MINIMUM_FREE = 10 * 1024**3


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_record(path):
    with path.open("rb") as stream:
        value = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"bytes": path.stat().st_size, "sha256": value}


def git(source, *args):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_NO_REPLACE_OBJECTS="1", GIT_OPTIONAL_LOCKS="0")
    return subprocess.run(["git", "--no-replace-objects", "-c", "core.fsmonitor=false", "-C", str(source), *args],
                          env=env, check=True, capture_output=True, timeout=60).stdout


def blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def clean_checkout(source, head, tree, count):
    require(git(source, "rev-parse", "HEAD").decode().strip() == head, "Checkout HEAD differs")
    require(git(source, "rev-parse", "HEAD^{tree}").decode().strip() == tree, "Checkout tree differs")
    require(not git(source, "status", "--porcelain", "--untracked-files=all"), "Checkout is not clean")
    require(len(git(source, "ls-files", "-z").split(b"\0")) - 1 == count, "Complete tracked inventory differs")
    return {"head": head, "tree": tree, "tracked_files": count, "clean": True}


def source_snapshot(source, manifest):
    result = clean_checkout(source, manifest["source_sha"], manifest["source_tree"], manifest["tracked_files"])
    inputs = {}
    for name in sorted(INPUTS | set(manifest["locks"])):
        path = source / name
        require(path.is_file() and not path.is_symlink(), "Required source input is not a regular file")
        content = path.read_bytes()
        require(content == git(source, "show", "HEAD:" + name), "Source working bytes differ from Git: " + name)
        actual = {"blob": blob(content), "sha256": sha(content)}
        if name in INPUTS:
            require(actual == manifest["inputs"][name], "Original image input changed: " + name)
        else:
            require(actual["sha256"] == manifest["locks"][name], "Original lock or test input changed: " + name)
        inputs[name] = actual
    result["inputs"] = inputs
    return result


def orchestrator_snapshot(orchestrator, manifest):
    head = os.environ["GITHUB_SHA"]
    require(re.fullmatch(r"[0-9a-f]{40}", head) is not None, "Invalid actual event commit")
    tree = git(orchestrator, "rev-parse", "HEAD^{tree}").decode().strip()
    result = clean_checkout(orchestrator, head, tree, manifest["tracked_files"] + 3)
    require(git(orchestrator, "show", "-s", "--format=%P", "HEAD").decode().strip() == manifest["source_sha"],
            "Diagnostic commit must be the direct child of its actual source commit")
    delta = git(orchestrator, "diff-tree", "--no-commit-id", "--name-status", "-r", manifest["source_sha"], head)
    require(sorted(delta.decode().splitlines()) == ["A\t" + p for p in sorted((DRIVER, WORKFLOW, MANIFEST))],
            "Orchestrator commit changes more than the three diagnostic files")
    result["diagnostic_inputs"] = {}
    for name in (DRIVER, WORKFLOW, MANIFEST):
        content = (orchestrator / name).read_bytes()
        require(content == git(orchestrator, "show", "HEAD:" + name), "Diagnostic working bytes differ from Git")
        result["diagnostic_inputs"][name] = {"blob": blob(content), "sha256": sha(content)}
    return result


def signal_owned_group(process, signum):
    try:
        os.killpg(process.pid, signum)
        return True
    except ProcessLookupError:
        return False


def save(output, report):
    (output / "result.json").write_text(json.dumps(report, indent=2) + "\n")


def checked_command(command, env, output, report):
    records = report.setdefault("preflight_commands", [])
    number = len(records) + 1
    record = {"command": command, "started_unix": time.time(), "budget_seconds": 30,
              "exit_code": None, "timed_out": False}
    records.append(record)
    stdout = stderr = b""
    try:
        result = subprocess.run(command, env=env, capture_output=True, timeout=30)
        stdout, stderr = result.stdout, result.stderr
        record["exit_code"] = result.returncode
    except subprocess.TimeoutExpired as error:
        stdout, stderr = error.output or b"", error.stderr or b""
        record["timed_out"] = True
    finally:
        for name, content in (("stdout", stdout), ("stderr", stderr)):
            path = output / f"preflight-{number:02d}.{name}"
            path.write_bytes(content)
            record[name] = {"file": path.name, "bytes": len(content), "sha256": sha(content)}
        record["finished_unix"] = time.time()
        save(output, report)
    require(record["exit_code"] == 0 and not record["timed_out"],
            "Preflight command failed; original output retained: " + command[0] + " " + command[1])
    return stdout.decode("utf-8", errors="replace").strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    orchestrator = Path(__file__).resolve().parents[2]
    temporary = Path(os.environ["RUNNER_TEMP"]).resolve()
    require(output.is_relative_to(temporary) and output != temporary
            and not output.is_relative_to(source) and not output.is_relative_to(orchestrator),
            "Evidence must remain outside both checkouts in its task directory")
    os.umask(0o077)
    output.mkdir(exist_ok=False)
    report = {"schema": "hepta-native-arm64-original-image-builder-actions-v1", "success": False,
              "started_unix": time.time(), "stage": "admission", "original_builder_executed": False,
              "registry_publication": False, "rbe_qualified": False, "rbe_pin_changed": False,
              "original_builder_budget_seconds": 1800, "publisher_preparation_budget_seconds": 120,
              "workflow_environment": {key: os.environ.get(key) for key in (
                  "GITHUB_SHA", "GITHUB_WORKFLOW_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT",
                  "GITHUB_REPOSITORY", "GITHUB_REF", "RUNNER_OS", "RUNNER_ARCH", "RUNNER_ENVIRONMENT",
                  "ImageOS", "ImageVersion")}}
    save(output, report)
    source_before = orchestrator_before = None
    try:
        require(os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("GITHUB_EVENT_NAME") == "push"
                and os.environ.get("GITHUB_REPOSITORY") == REPOSITORY
                and os.environ.get("GITHUB_REF") == "refs/heads/" + BRANCH,
                "Requires the actual isolated repository Actions event")
        require(platform.system() == "Linux" and platform.machine() == "aarch64"
                and os.environ.get("RUNNER_OS") == "Linux" and os.environ.get("RUNNER_ARCH") == "ARM64",
                "Actual native Linux ARM64 is required")
        require(os.environ.get("GITHUB_WORKFLOW_SHA") == os.environ.get("GITHUB_SHA"),
                "Actual workflow commit differs from its push event")
        forbidden = ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "DOCKER_AUTH_CONFIG", "DOCKER_TLS_VERIFY",
                     "DOCKER_CERT_PATH", "DOCKER_TLS_CERTDIR", "BUILDX_BUILDER", "BUILDX_CONFIG", "BUILDKIT_HOST",
                     "GITHUB_TOKEN", "GH_TOKEN", "GHCR_PUBLISH_TOKEN", "BASH_ENV", "ENV", "PYTHONPATH", "PYTHONHOME",
                     "PYTHONOPTIMIZE", "LD_PRELOAD", "LD_LIBRARY_PATH", "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE",
                     "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS")
        require(not any(key in os.environ for key in forbidden), "Unexpected inherited execution or registry override")
        require(args.manifest.resolve() == orchestrator / MANIFEST and source == orchestrator.parent / "candidate",
                "Source and orchestrator must use their independently checked-out directories")
        manifest = json.loads(args.manifest.read_text())
        require(manifest["repository"] == REPOSITORY and manifest["tracked_files"] == 10774
                and set(manifest["inputs"]) == INPUTS and len(manifest["locks"]) == 18
                and re.fullmatch(r"[0-9a-f]{40}", manifest["source_sha"]) is not None
                and re.fullmatch(r"[0-9a-f]{40}", manifest["source_tree"]) is not None,
                "Reviewed source manifest differs from the complete input contract")
        report["source_manifest"] = manifest
        report["stage"] = "source_identity"
        orchestrator_before = orchestrator_snapshot(orchestrator, manifest)
        source_before = source_snapshot(source, manifest)
        report.update(orchestrator_before=orchestrator_before, source_before=source_before)
        git(source, "fsck", "--full", "--strict", "--no-reflogs")
        report["source_fsck_passed"] = True
        save(output, report)

        work = temporary / "hepta-arm64-image-work"
        work.mkdir(mode=0o700, exist_ok=False)
        config = work / "docker-config"
        config.mkdir(mode=0o700)
        auth = b'{"auths": {}}\n'
        (config / "config.json").write_bytes(auth)
        image_evidence = output / "image"
        image_evidence.mkdir()
        environment = dict(os.environ, DOCKER_CONFIG=str(config), SOURCE_SHA=manifest["source_sha"],
                           IMAGE_ARCH="arm64", IMAGE_EVIDENCE_DIR=str(image_evidence),
                           PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1")
        report["stage"] = "native_docker_and_disk_preflight"
        report["machine"] = {"system": platform.system(), "machine": platform.machine(), "cpu_count": os.cpu_count()}
        endpoint = checked_command(["docker", "context", "inspect", "default", "--format", "{{json .Endpoints.docker.Host}}"], environment, output, report)
        require(json.loads(endpoint) == "unix:///var/run/docker.sock", "Docker endpoint is not the local Unix daemon")
        report["docker_endpoint"] = json.loads(endpoint)
        info = checked_command(["docker", "info", "--format",
            "{{json .ID}}\n{{json .Architecture}}\n{{json .OSType}}\n{{json .ServerVersion}}\n{{json .DockerRootDir}}"], environment, output, report)
        fields = [json.loads(line) for line in info.splitlines()]
        require(len(fields) == 5 and fields[0] and fields[1] in ("aarch64", "arm64") and fields[2] == "linux",
                "Local Docker daemon is not native Linux ARM64")
        report["daemon"] = dict(zip(("id", "architecture", "os", "version", "root_directory"), fields))
        report["tool_versions"] = {"docker": checked_command(["docker", "version", "--format", "{{json .}}"], environment, output, report),
                                   "buildx": checked_command(["docker", "buildx", "version"], environment, output, report),
                                   "git": checked_command(["git", "--version"], environment, output, report),
                                   "bash": checked_command(["bash", "--version"], environment, output, report).splitlines()[0],
                                   "python": sys.version}
        report["tool_paths"] = {name: shutil.which(name) for name in ("docker", "git", "bash", "sha256sum", "python3")}
        require(all(report["tool_paths"].values()), "An original builder tool is missing")
        report["minimum_free_bytes"] = MINIMUM_FREE
        report["free_bytes_before"] = {"docker": shutil.disk_usage(fields[4]).free, "task": shutil.disk_usage(work).free}
        require(min(report["free_bytes_before"].values()) >= MINIMUM_FREE, "Actual runner free space is below the 10 GiB image-build floor")
        save(output, report)

        report["stage"] = "original_publisher_18_tests"
        command = ["python3", "-m", "unittest", "discover", "-s", ".github/scripts", "-p", "test_publish_bazel_image.py"]
        tests = {"command": command, "budget_seconds": 120, "started_unix": time.time(), "timed_out": False}
        report["publisher_tests"] = tests
        save(output, report)
        stdout = stderr = b""
        try:
            completed = subprocess.run(command, cwd=source, env=environment, capture_output=True, timeout=120)
            stdout, stderr = completed.stdout, completed.stderr
            tests["exit_code"] = completed.returncode
        except subprocess.TimeoutExpired as error:
            stdout, stderr = error.output or b"", error.stderr or b""
            tests.update(timed_out=True, exit_code=None)
            raise RuntimeError("Original publisher tests exceeded their separate preparation budget") from error
        finally:
            (output / "publisher-tests.stdout").write_bytes(stdout)
            (output / "publisher-tests.stderr").write_bytes(stderr)
            tests.update(finished_unix=time.time(), stdout_sha256=sha(stdout), stderr_sha256=sha(stderr))
        count = re.search(r"Ran (\d+) tests? in ", stderr.decode())
        tests["test_count"] = int(count.group(1)) if count else None
        require(tests["exit_code"] == 0 and tests["test_count"] == 18 and stderr.decode().rstrip().endswith("\nOK"),
                "Original publisher 18 tests did not all pass")

        image = "ghcr.io/trillionniumfoundation/hepta-bazel:sha-" + manifest["source_sha"] + "-arm64"
        absence = {"command": ["docker", "image", "inspect", image], "budget_seconds": 30,
                   "started_unix": time.time(), "exit_code": None, "timed_out": False}
        report["candidate_tag_absence"] = absence
        stdout = stderr = b""
        try:
            inspected = subprocess.run(absence["command"], env=environment, capture_output=True, timeout=30)
            stdout, stderr = inspected.stdout, inspected.stderr
            absence["exit_code"] = inspected.returncode
        except subprocess.TimeoutExpired as error:
            stdout, stderr = error.output or b"", error.stderr or b""
            absence["timed_out"] = True
        finally:
            for name, content in (("stdout", stdout), ("stderr", stderr)):
                path = output / ("candidate-tag-absence." + name)
                path.write_bytes(content)
                absence[name] = {"file": path.name, "bytes": len(content), "sha256": sha(content)}
            absence["finished_unix"] = time.time()
            save(output, report)
        require(absence["exit_code"] == 1 and not absence["timed_out"] and b"no such image" in stderr.lower(),
                "Candidate ARM image tag is not proven absent; actual probe output retained")
        require(source_snapshot(source, manifest) == source_before, "Candidate changed during preparation")
        report.update(stage="original_builder", image_tag=image, builder_command=["bash", ".github/scripts/build-bazel-image.sh"],
                      preparation_finished_unix=time.time(), builder_started_unix=time.time(),
                      original_builder_executed=None)
        save(output, report)
        log = image_evidence / "builder-command.log"
        with log.open("xb") as stream:
            process = subprocess.Popen(report["builder_command"], cwd=source, env=environment,
                                       stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
            report["original_builder_executed"] = True
            try:
                report["builder_exit_code"] = process.wait(timeout=1800)
            except subprocess.TimeoutExpired:
                report["builder_timed_out"] = True
                report["builder_term_sent"] = signal_owned_group(process, signal.SIGTERM)
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    report["builder_kill_sent"] = signal_owned_group(process, signal.SIGKILL)
                    process.wait(timeout=15)
                raise RuntimeError("Original builder exceeded its unchanged 1800 second budget")
            finally:
                report.update(builder_finished_unix=time.time(), builder_exit_code=process.poll(),
                              builder_terminal_observed=process.returncode is not None, builder_log=file_record(log))
        require(report["builder_exit_code"] == 0, "Original builder failed; raw command log retained")
        bound = json.loads((image_evidence / "source.json").read_text())
        require(bound["source_sha"] == manifest["source_sha"] and bound["source_tree"] == manifest["source_tree"]
                and bound["repository"] == REPOSITORY and bound["architecture"] == "arm64"
                and bound["dockerfile_sha256"] == manifest["inputs"][".github/workflows/Dockerfile.bazel"]["sha256"]
                and bound["workflow_sha"] == os.environ["GITHUB_WORKFLOW_SHA"]
                and bound["run_id"] == os.environ["GITHUB_RUN_ID"] and bound["run_attempt"] == os.environ["GITHUB_RUN_ATTEMPT"],
                "Builder source and actual workflow attribution differ")
        require((image_evidence / "verified-image-tag.txt").read_text().strip() == image, "Verified ARM tag is missing")
        require(SENTINEL in (image_evidence / "openssh-smoke.log").read_text().splitlines(), "Original smoke did not finish its positive and negative checks")
        spec = importlib.util.spec_from_file_location("checked_bazel_image_identity", source / ".github/scripts/bazel_image_identity.py")
        require(spec is not None and spec.loader is not None, "Original OCI identity helper is unavailable")
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        report["verified_identity"] = helper.verified_local_identity(image_evidence)
        require(report["verified_identity"]["architecture"] == "arm64", "Verified OCI identity has the wrong architecture")
        require(not any((image_evidence / "context").iterdir()), "Original build context was not empty")
        require((config / "config.json").read_bytes() == auth, "Task Docker auth configuration changed")
        report["original_positive_and_negative_smoke_passed"] = True
        report["success"] = True
    except Exception as error:
        report["success"] = False
        report["error"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        for name, before, check in (
            ("source", source_before, lambda: source_snapshot(source, manifest)),
            ("orchestrator", orchestrator_before, lambda: orchestrator_snapshot(orchestrator, manifest)),
        ):
            if before is not None:
                try:
                    report[name + "_after"] = check()
                    report[name + "_unchanged"] = report[name + "_after"] == before
                except Exception as error:
                    report[name + "_after_error"] = {"type": type(error).__name__, "message": str(error)}
                    report[name + "_unchanged"] = False
                report["success"] = report["success"] and report[name + "_unchanged"]
        report["finished_unix"] = time.time()
        try:
            report["free_bytes_after"] = shutil.disk_usage(temporary).free
        except OSError as error:
            report["resource_observation_error"] = type(error).__name__
        save(output, report)
        artifacts = {str(path.relative_to(output)): file_record(path) for path in sorted(output.rglob("*")) if path.is_file()}
        (output / "artifact-manifest.json").write_text(json.dumps({"files": artifacts}, indent=2) + "\n")
        print(json.dumps(report, indent=2), flush=True)
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
