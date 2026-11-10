"""Observe the published amd64 image requested by the retained failed RBE spawn."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import uuid


ROOT = Path(__file__).resolve().parents[1]
IMAGE = "docker.io/mbolin491/codex-bazel@sha256:0a8e56bfaa3b2e5279db0d3bb2d62b44ba5e5d63a37d97eb8790f49da570af70"
RBE_BLOB = "57e301ac776d9c7196e9c854bc6e27ce2718d886"
SPAWN_PATH = "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
PROBE = r"""set -eu
umask 077
printf 'IMAGE_DEFAULT_USER\n'
id
uname -a
printf 'PATH=%s\n' "$PATH"
for candidate in /usr/local/bin/ssh-keygen /usr/bin/ssh-keygen /bin/ssh-keygen /usr/sbin/ssh-keygen /sbin/ssh-keygen; do
    if test -e "$candidate"; then
        ls -ld "$candidate"
        readlink -f "$candidate"
    else
        printf 'MISSING=%s\n' "$candidate"
    fi
done
if command -v dpkg-query; then
    dpkg-query -W openssh-client libc6 || printf 'PACKAGE_QUERY_NONZERO=%s\n' "$?"
fi
resolved=$(command -v ssh-keygen || true)
printf 'RESOLVED_SSH_KEYGEN=%s\n' "$resolved"
if test -z "$resolved"; then
    printf 'PINNED_IMAGE_TOOL_MISSING\n'
    exit 20
fi
test -x "$resolved"
sha256sum "$resolved"
ldd "$resolved" > /tmp/keygen-ldd.txt
cat /tmp/keygen-ldd.txt
if grep -F 'not found' /tmp/keygen-ldd.txt; then exit 21; fi
mkdir /tmp/state
cd /tmp/state
"$resolved" -q -t ed25519 -N '' -f key
printf 'qualification ' > allowed_signers
cat key.pub >> allowed_signers
printf 'hepta-pinned-rbe-tool-observation-v1\n' > message
"$resolved" -Y sign -f key -n hepta-pinned-rbe message
"$resolved" -Y verify -f allowed_signers -I qualification -n hepta-pinned-rbe -s message.sig < message
printf 'changed-message\n' > changed
set +e
"$resolved" -Y verify -f allowed_signers -I qualification -n hepta-pinned-rbe -s message.sig < changed
refused=$?
set -e
test "$refused" -ne 0
printf 'CHANGED_MESSAGE_REFUSAL=%s\nPINNED_IMAGE_FIXTURE_PASS\n' "$refused"
"""


def validate_image(image):
    """Bind the inspected local image to the requested published manifest."""
    identities = [value.removeprefix("docker.io/") for value in image["RepoDigests"]]
    if IMAGE.removeprefix("docker.io/") not in identities:
        raise ValueError("requested immutable manifest missing from inspected image")
    if (image["Os"], image["Architecture"]) != ("linux", "amd64"):
        raise ValueError("this observation requires native Linux amd64")
    identity = image["Id"]
    if len(identity) != 71 or not identity.startswith("sha256:"):
        raise ValueError("invalid local image config identity")
    int(identity[7:], 16)
    return identity


def observe(output, expected_source):
    output = output.resolve()
    if output.is_relative_to(ROOT):
        raise ValueError("records must be outside the reviewed checkout")
    output.mkdir(parents=True, exist_ok=False)
    result = {
        "schema": "hepta.pinned-rbe-openssh-observation.v1",
        "operation_id": str(uuid.uuid4()),
        "expected_source": expected_source,
        "requested_image": IMAGE,
        "status": "RUNNING",
        "fixture_probe_passed": None,
        "actual_remote_executor_observed": False,
        "original_operator_target_passed": None,
        "image_pin_changed": False,
        "physical_cost_complete": False,
        "net_utility": None,
        "scientific_admission": "HOLD",
        "production_authority": "NONE",
    }

    def save():
        (output / "RESULT.json").write_text(json.dumps(result, indent=2) + "\n")

    def run(name, args, *, timeout=60, stdin=None):
        receipt = {"args": args, "timeout_seconds": timeout, "status": "STARTING"}
        receipt["started_utc"] = datetime.now(timezone.utc).isoformat()

        def bound_files():
            import resource

            resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024**2, 8 * 1024**2))

        try:
            with (
                (output / (name + ".stdout")).open("wb") as stdout,
                (output / (name + ".stderr")).open("wb") as stderr,
            ):
                process = subprocess.run(
                    args,
                    cwd=ROOT,
                    input=stdin,
                    stdout=stdout,
                    stderr=stderr,
                    timeout=timeout,
                    check=False,
                    preexec_fn=bound_files,
                )
            receipt.update(status="EXITED", exit_code=process.returncode)
            if process.returncode:
                raise RuntimeError(f"{name} exited {process.returncode}")
            return (output / (name + ".stdout")).read_text()
        except BaseException as error:
            receipt["error"] = repr(error)
            if receipt["status"] == "STARTING":
                receipt["status"] = "NOT_COMPLETED"
            raise
        finally:
            receipt["finished_utc"] = datetime.now(timezone.utc).isoformat()
            (output / (name + ".receipt.json")).write_text(
                json.dumps(receipt, indent=2) + "\n"
            )

    save()
    try:
        if (platform.system(), platform.machine()) != ("Linux", "x86_64"):
            raise RuntimeError("requires a native Linux x86_64 host")
        if run("source", ["git", "rev-parse", "HEAD"]).strip() != expected_source:
            raise RuntimeError("reviewed source mismatch")
        if run("clean-before", ["git", "status", "--porcelain"]).strip():
            raise RuntimeError("checkout is not clean")
        blob = run("rbe-blob", ["git", "rev-parse", "HEAD:rbe.bzl"]).strip()
        if blob != RBE_BLOB:
            raise RuntimeError("RBE definition differs from the retained failed spawn")
        result["rbe_git_blob"] = blob
        result["source_tree"] = run("tree", ["git", "rev-parse", "HEAD^{tree}"]).strip()
        for path in (
            "rbe.bzl",
            "scripts/observe_pinned_rbe_openssh.py",
            "scripts/test_observe_pinned_rbe_openssh.py",
            ".github/workflows/hepta-pinned-rbe-openssh.yml",
        ):
            target = output / "source" / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / path).read_bytes())
        run("docker-version", ["docker", "version"])
        run(
            "pull-pinned",
            ["docker", "pull", "--platform", "linux/amd64", IMAGE],
            timeout=240,
        )
        image = json.loads(run("inspect", ["docker", "image", "inspect", IMAGE]))[0]
        result["local_image_config_id"] = validate_image(image)
        save()
        (output / "probe.sh").write_text(PROBE)
        container = "hepta-pinned-rbe-" + result["operation_id"]
        primary_error = None
        try:
            run(
                "probe",
                [
                    "docker",
                    "run",
                    "--name",
                    container,
                    "--network",
                    "none",
                    "--read-only",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges",
                    "--cpus",
                    "1",
                    "--memory",
                    "256m",
                    "--pids-limit",
                    "64",
                    "--tmpfs",
                    "/tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777",
                    "--env",
                    "PATH=" + SPAWN_PATH,
                    "--workdir",
                    "/tmp",
                    "--entrypoint",
                    "/bin/sh",
                    result["local_image_config_id"],
                    "-s",
                ],
                timeout=90,
                stdin=PROBE.encode(),
            )
        except BaseException as error:
            primary_error = error
            raise
        finally:
            # This unique container belongs solely to this operation. Retain cleanup failure.
            try:
                run("remove-owned-container", ["docker", "rm", "--force", container])
            except BaseException as error:
                result["cleanup_error"] = repr(error)
                if primary_error is None:
                    raise
        if (
            not (output / "probe.stdout")
            .read_text()
            .endswith("PINNED_IMAGE_FIXTURE_PASS\n")
        ):
            raise RuntimeError("fixture completion marker missing")
        result["fixture_probe_passed"] = True
        if run("clean-after", ["git", "status", "--porcelain"]).strip():
            raise RuntimeError("reviewed source changed")
        result["status"] = "PUBLISHED_IMAGE_PROBE_PASS_REMOTE_TARGET_OPEN"
    except BaseException as error:
        result.update(status="FAILED", error=repr(error))
        receipt = output / "probe.receipt.json"
        stdout = output / "probe.stdout"
        if (
            receipt.exists()
            and stdout.exists()
            and json.loads(receipt.read_text()).get("exit_code") == 20
            and stdout.read_text().endswith("PINNED_IMAGE_TOOL_MISSING\n")
        ):
            result.update(
                status="TOOL_MISSING_IN_PUBLISHED_IMAGE", fixture_probe_passed=False
            )
        raise
    finally:
        save()
        manifest = {
            str(path.relative_to(output)): {
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in sorted(output.rglob("*"))
            if path.is_file()
        }
        (output / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-source", required=True)
    arguments = parser.parse_args()
    observe(arguments.output, arguments.expected_source)
