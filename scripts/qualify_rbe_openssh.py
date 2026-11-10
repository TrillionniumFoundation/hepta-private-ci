"""Measure one native amd64 RBE image without publishing or activating it."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import uuid
from urllib.parse import parse_qs, urlsplit


ARCHIVE_LIMIT = 512 * 1024 * 1024
ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ".github/workflows/Dockerfile.bazel"
PROBE = r"""set -eu
umask 077
test "$(uname -m)" = x86_64
test -x /usr/bin/ssh-keygen
readlink -f /usr/bin/ssh-keygen
sha256sum /usr/bin/ssh-keygen
dpkg-query -W openssh-client libc6
ssh -V
ldd /usr/bin/ssh-keygen > /tmp/keygen-ldd.txt
cat /tmp/keygen-ldd.txt
if grep -F 'not found' /tmp/keygen-ldd.txt; then exit 1; fi
mkdir /tmp/state
cd /tmp/state
/usr/bin/ssh-keygen -q -t ed25519 -N '' -f key
printf 'qualification ' > allowed_signers
cat key.pub >> allowed_signers
printf 'hepta-rbe-image-qualification-v1\n' > message
/usr/bin/ssh-keygen -Y sign -f key -n hepta-rbe-image message
/usr/bin/ssh-keygen -Y verify -f allowed_signers -I qualification -n hepta-rbe-image -s message.sig < message
printf 'changed-message\n' > tampered
set +e
/usr/bin/ssh-keygen -Y verify -f allowed_signers -I qualification -n hepta-rbe-image -s message.sig < tampered
rejected=$?
set -e
test "$rejected" -ne 0
printf 'TAMPER_REFUSAL_EXIT=%s\nRBE_OPENSSH_PROBE_PASS\n' "$rejected"
"""


def file_identity(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def validate_build(metadata, image, iid):
    """Require exact local image identity and a resolved amd64 Ubuntu material."""
    identity = image["Id"]
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", identity):
        raise ValueError("invalid local image identity")
    if (image["Os"], image["Architecture"]) != ("linux", "amd64"):
        raise ValueError("not a native Linux amd64 image")
    if iid != identity or metadata["containerimage.config.digest"] != identity:
        raise ValueError("build metadata and tested local image differ")
    provenance = metadata["buildx.build.provenance"]
    materials = provenance.get(
        "materials", provenance.get("predicate", {}).get("materials", [])
    )
    matches = []
    for material in materials:
        uri = material.get("uri", "")
        parsed = urlsplit(uri)
        if (
            uri.startswith("pkg:docker/")
            and parsed.path.split("/")[-1] == "ubuntu@24.04"
            and parse_qs(parsed.query).get("platform") == ["linux/amd64"]
        ):
            digest = material.get("digest", {}).get("sha256", "")
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("invalid resolved Ubuntu digest")
            matches.append(material)
    if len(matches) != 1:
        raise ValueError("one resolved Ubuntu linux/amd64 material is required")
    return {
        "local_image_id": identity,
        "resolved_base_material": matches[0],
        "build_output_digest": metadata.get("containerimage.digest"),
        "registry_publication_digest": None,
    }


def qualify(output, expected):
    output = output.resolve()
    if output.is_relative_to(ROOT):
        raise ValueError("output must be outside the reviewed checkout")
    output.mkdir(parents=True, exist_ok=False)
    result = {
        "schema": "hepta.rbe.openssh-image-qualification.v1",
        "status": "RUNNING",
        "operation_id": str(uuid.uuid4()),
        "expected_source_commit": expected,
        "registry_publication_performed": False,
        "image_pin_changed": False,
        "operator_acceptance_blocker_closed": False,
        "scientific_admission": "HOLD",
        "production_authority": "NONE",
        "archive": {"status": "NOT_BUILT"},
    }

    def save_result():
        (output / "RESULT.json").write_text(json.dumps(result, indent=2) + "\n")

    def run(name, args, *, stdin=None, timeout=60, env=None):
        receipt = {
            "args": args,
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "timeout_seconds": timeout,
            "status": "RUNNING",
        }
        receipt_path = output / (name + ".receipt.json")
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
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
                    env=env,
                    check=False,
                )
            receipt.update(status="EXITED", exit_code=process.returncode)
            if process.returncode:
                raise RuntimeError(f"{name} exited {process.returncode}")
        except BaseException as error:
            receipt.update(error=repr(error))
            if receipt["status"] == "RUNNING":
                receipt["status"] = "INTERRUPTED_OR_NOT_STARTED"
            raise
        finally:
            receipt["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
            receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
        return (output / (name + ".stdout")).read_text()

    save_result()
    try:
        if platform.system() != "Linux" or platform.machine() not in (
            "x86_64",
            "amd64",
        ):
            raise RuntimeError("this profile requires a native Linux amd64 host")
        commit = run("source-commit", ["git", "rev-parse", "HEAD"]).strip()
        if commit != expected or not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise RuntimeError("reviewed source mismatch")
        if run("source-clean-before", ["git", "status", "--porcelain"]).strip():
            raise RuntimeError("reviewed checkout is not clean")
        result["source_tree"] = run(
            "source-tree", ["git", "rev-parse", "HEAD^{tree}"]
        ).strip()
        result["dockerfile_git_blob"] = run(
            "dockerfile-blob", ["git", "rev-parse", "HEAD:" + DOCKERFILE]
        ).strip()
        source = output / "source"
        for name in (
            DOCKERFILE,
            "scripts/qualify_rbe_openssh.py",
            "scripts/test_qualify_rbe_openssh.py",
            ".github/workflows/hepta-rbe-openssh-image.yml",
        ):
            target = source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / name).read_bytes())
        if [
            line
            for line in (ROOT / DOCKERFILE).read_text().splitlines()
            if line.startswith("FROM ")
        ] != ["FROM ubuntu:24.04"]:
            raise RuntimeError("unsupported base-image recipe")
        run("docker-version", ["docker", "version"])
        run("buildx-version", ["docker", "buildx", "version"])
        env = dict(
            os.environ, BUILDX_METADATA_PROVENANCE="max", BUILDX_METADATA_WARNINGS="1"
        )
        tag = "hepta-rbe-openssh-qualification:" + result["operation_id"]
        run(
            "build",
            [
                "docker",
                "buildx",
                "build",
                "--load",
                "--platform",
                "linux/amd64",
                "--pull",
                "--no-cache",
                "--progress",
                "plain",
                "--metadata-file",
                str(output / "build-metadata.json"),
                "--iidfile",
                str(output / "image.iid"),
                "--tag",
                tag,
                "--file",
                DOCKERFILE,
                ".",
            ],
            timeout=720,
            env=env,
        )
        image = json.loads(run("image-inspect", ["docker", "image", "inspect", tag]))[0]
        metadata = json.loads((output / "build-metadata.json").read_text())
        result.update(
            validate_build(metadata, image, (output / "image.iid").read_text().strip())
        )
        save_result()
        (output / "probe.sh").write_text(PROBE)
        container = "rbe-openssh-" + result["operation_id"]
        try:
            run(
                "probe",
                [
                    "docker",
                    "run",
                    "--rm",
                    "--name",
                    container,
                    "--network",
                    "none",
                    "--read-only",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges",
                    "--tmpfs",
                    "/tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777",
                    "--workdir",
                    "/tmp",
                    "--entrypoint",
                    "/bin/sh",
                    image["Id"],
                    "-s",
                ],
                stdin=PROBE.encode(),
                timeout=90,
            )
        except subprocess.TimeoutExpired:
            run("owned-container-stop", ["docker", "rm", "--force", container])
            raise
        if (
            not (output / "probe.stdout")
            .read_text()
            .endswith("RBE_OPENSSH_PROBE_PASS\n")
        ):
            raise RuntimeError("probe completion marker missing")
        result["probe_passed"] = True
        result["archive"] = {"status": "NOT_EXPORTED", "limit_bytes": ARCHIVE_LIMIT}
        if image["Size"] <= ARCHIVE_LIMIT:
            import resource

            def limit_archive():
                resource.setrlimit(
                    resource.RLIMIT_FSIZE, (ARCHIVE_LIMIT, ARCHIVE_LIMIT)
                )

            archive = output / "tested-image.tar.partial"
            command = ["docker", "image", "save", image["Id"]]
            with (
                archive.open("wb") as stdout,
                (output / "save-image.stderr").open("wb") as stderr,
            ):
                process = subprocess.run(
                    command,
                    stdout=stdout,
                    stderr=stderr,
                    timeout=120,
                    check=False,
                    preexec_fn=limit_archive,
                )
            result["archive"].update(
                command=command,
                exit_code=process.returncode,
                partial_or_complete_identity=file_identity(archive),
            )
            if process.returncode == 0:
                archive.rename(output / "tested-image.tar")
                result["archive"]["status"] = "RETAINED_COMPLETE"
            else:
                archive.unlink()
                raise RuntimeError(
                    "bounded image export failed; inspect original stderr"
                )
        else:
            result["archive"]["status"] = "OMITTED_IMAGE_SIZE_EXCEEDS_BOUND"
        if run("source-clean-after", ["git", "status", "--porcelain"]).strip():
            raise RuntimeError("reviewed source changed")
        result["status"] = "IMAGE_PROBE_PASS_OPERATOR_ACCEPTANCE_OPEN"
    except BaseException as error:
        result.update(status="FAILED", error=repr(error))
        raise
    finally:
        save_result()
        manifest = {
            str(path.relative_to(output)): file_identity(path)
            for path in sorted(output.rglob("*"))
            if path.is_file()
        }
        (output / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--expected-source", required=True)
    arguments = parser.parse_args()
    qualify(arguments.output, arguments.expected_source)
