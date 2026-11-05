#!/usr/bin/python3
"""Build and inspect one native platform, without any registry write authority."""

import hashlib
import json
import os
from pathlib import Path
import sys
import tarfile

from common import (
    BASES,
    Evidence,
    PACKAGE,
    descriptor_path,
    image_checks,
    json_write,
    require,
    sha_file,
    unpack_oci,
    verify_diff_ids,
)


def retained_files(directory, manifest):
    wanted = {
        "usr/local/lib/hepta-rbe-openssh/image_prepare.py",
        "usr/local/share/hepta-rbe-openssh/install.json",
        "usr/local/share/hepta-rbe-openssh/tool-test.json",
    }
    tracked = set(wanted)
    for name in wanted:
        parent = name.rpartition("/")[0]
        while parent:
            tracked.add(parent)
            parent = parent.rpartition("/")[0]
    nodes = {}
    for layer in manifest["layers"]:
        media = layer["mediaType"]
        require(
            media
            in (
                "application/vnd.oci.image.layer.v1.tar",
                "application/vnd.oci.image.layer.v1.tar+gzip",
            ),
            "unsupported layer media",
        )
        entries, removals, opaque = {}, set(), set()
        with tarfile.open(descriptor_path(directory, layer), "r|*") as archive:
            for item in archive:
                name = item.name.removeprefix("./").rstrip("/")
                require(
                    not name.startswith("/")
                    and "//" not in name
                    and not any(part in (".", "..") for part in name.split("/")),
                    "noncanonical OCI layer path",
                )
                parent, _, leaf = name.rpartition("/")
                if leaf == ".wh..wh..opq":
                    if not parent or parent in tracked:
                        opaque.add(parent)
                elif leaf.startswith(".wh."):
                    removed = (parent + "/" if parent else "") + leaf[4:]
                    if removed in tracked:
                        removals.add(removed)
                elif name in tracked:
                    require(name not in entries, "duplicate tracked OCI entry")
                    if item.isdir():
                        entries[name] = ("directory", None)
                    elif item.isfile():
                        value = None
                        if name in wanted:
                            require(
                                item.size <= 32 * 1024 * 1024,
                                "retained image evidence exceeds its bound",
                            )
                            raw = archive.extractfile(item).read()
                            require(
                                len(raw) == item.size,
                                "retained image evidence truncated",
                            )
                            value = (
                                raw,
                                {"uid": item.uid, "gid": item.gid, "mode": item.mode},
                            )
                        entries[name] = ("file", value)
                    else:
                        entries[name] = ("non-directory", None)
        # Whiteouts affect only lower layers, regardless of their archive order.
        for path in list(nodes):
            if any(
                path == removed or path.startswith(removed + "/")
                for removed in removals
            ):
                del nodes[path]
            elif any(not parent or path.startswith(parent + "/") for parent in opaque):
                del nodes[path]
        # Apply ancestors first. A file or symlink replacing an ancestor hides all
        # old descendants; a later child cannot silently traverse that object.
        for name in sorted(entries, key=lambda path: (path.count("/"), path)):
            parts = name.split("/")
            for length in range(1, len(parts)):
                parent = "/".join(parts[:length])
                if parent in nodes:
                    require(
                        nodes[parent][0] == "directory",
                        "OCI evidence ancestor is not a directory",
                    )
                else:
                    nodes[parent] = ("directory", None)
            if entries[name][0] != "directory":
                for path in list(nodes):
                    if path.startswith(name + "/"):
                        del nodes[path]
            nodes[name] = entries[name]
    require(
        all(
            name in nodes and nodes[name][0] == "file" and nodes[name][1] is not None
            for name in wanted
        ),
        "effective retained image evidence is missing or nonregular",
    )
    for name in wanted:
        parts = name.split("/")
        require(
            all(
                nodes.get("/".join(parts[:length]), (None,))[0] == "directory"
                for length in range(1, len(parts))
            ),
            "effective retained image evidence is obscured by an ancestor",
        )
    return {name: nodes[name][1] for name in wanted}


def build(evidence):
    arch, identity = evidence.arch, evidence.identity
    baseline_ref = BASES[arch]
    evidence.command(["docker", "version"])
    evidence.command(["docker", "buildx", "version"])
    evidence.command(
        ["docker", "pull", "--platform", "linux/" + arch, baseline_ref], capture=False
    )
    baseline_raw = evidence.command(["docker", "image", "inspect", baseline_ref])
    baseline = json.loads(baseline_raw)
    require(len(baseline) == 1, "expected one exact base image")
    baseline = baseline[0]
    require(
        any(
            x.endswith("@" + baseline_ref.split("@", 1)[1])
            for x in baseline.get("RepoDigests", [])
        ),
        "base manifest digest not retained",
    )
    json_write(evidence.root / "baseline-image.json", baseline)
    builder = "hepta-rbe-" + identity["run_id"] + "-" + identity["attempt"] + "-" + arch
    created = False
    try:
        # This is a dedicated builder. No global daemon or original RBE policy changes.
        evidence.command(
            [
                "docker",
                "buildx",
                "create",
                "--name",
                builder,
                "--driver",
                "docker-container",
                "--driver-opt",
                "env.BUILDKIT_STEP_LOG_MAX_SIZE=-1",
                "--driver-opt",
                "env.BUILDKIT_STEP_LOG_MAX_SPEED=-1",
                "--driver-opt",
                "memory=2g",
                "--driver-opt",
                "memory-swap=2g",
                "--driver-opt",
                "cpu-period=100000",
                "--driver-opt",
                "cpu-quota=200000",
            ]
        )
        created = True
        evidence.command(["docker", "buildx", "inspect", "--bootstrap", builder])
        builder_container = "buildx_buildkit_" + builder + "0"
        inspect = json.loads(evidence.command(["docker", "inspect", builder_container]))
        require(len(inspect) == 1, "builder container identity is not unique")
        container = inspect[0]
        require(
            container["HostConfig"]["Memory"] == 2 * 1024**3
            and container["HostConfig"]["MemorySwap"] == 2 * 1024**3
            and container["HostConfig"]["CpuQuota"] == 200000
            and container["HostConfig"]["CpuPeriod"] == 100000,
            "builder limits differ",
        )
        environment = container["Config"].get("Env", [])
        require(
            "BUILDKIT_STEP_LOG_MAX_SIZE=-1" in environment
            and "BUILDKIT_STEP_LOG_MAX_SPEED=-1" in environment,
            "builder can clip failure evidence",
        )
        json_write(evidence.root / "builder-container.json", container)
        builder_image = json.loads(
            evidence.command(["docker", "image", "inspect", container["Image"]])
        )
        json_write(evidence.root / "builder-image.json", builder_image)
        archive = evidence.root / "image.oci.tar"
        labels = [
            "org.opencontainers.image.source=https://github.com/"
            + identity["repository"],
            "org.opencontainers.image.revision=" + identity["commit"],
            "io.hepta.source.tree=" + identity["tree"],
            "io.hepta.source.run=" + identity["run_id"] + "-" + identity["attempt"],
        ]
        args = [
            "docker",
            "buildx",
            "build",
            "--builder",
            builder,
            "--progress",
            "plain",
            "--platform",
            "linux/" + arch,
            "--no-cache",
            "--provenance=false",
            "--sbom=false",
            "--output",
            "type=oci,dest=" + str(archive),
            "--file",
            PACKAGE + "/Dockerfile",
        ]
        for label in labels:
            args.extend(["--label", label])
        args.append(PACKAGE)
        evidence.command(args, capture=False)
        for entry in evidence.logs:
            for stream in ("stdout", "stderr"):
                path = evidence.root / entry[stream]
                with path.open("rb") as handle:
                    previous = b""
                    for data in iter(lambda: handle.read(1024 * 1024), b""):
                        require(
                            b"[output clipped" not in previous + data,
                            "BuildKit evidence was clipped",
                        )
                        previous = data[-64:]
        directory = evidence.root / "oci"
        descriptor, manifest, raw_manifest, config = unpack_oci(archive, directory)
        image_checks(identity, arch, config, baseline)
        verify_diff_ids(directory, manifest, config)
        retained = retained_files(directory, manifest)
        script, script_mode = retained[
            "usr/local/lib/hepta-rbe-openssh/image_prepare.py"
        ]
        require(
            script == (Path(PACKAGE) / "image_prepare.py").read_bytes()
            and script_mode == {"uid": 0, "gid": 0, "mode": 0o444},
            "image installer source changed",
        )
        installed_raw, installed_mode = retained[
            "usr/local/share/hepta-rbe-openssh/install.json"
        ]
        smoke_raw, smoke_mode = retained[
            "usr/local/share/hepta-rbe-openssh/tool-test.json"
        ]
        require(
            installed_mode["uid"] == 0
            and installed_mode["gid"] == 0
            and installed_mode["mode"] == 0o644
            and smoke_mode == {"uid": 0, "gid": 0, "mode": 0o444},
            "image receipts are not protected",
        )
        installed, smoke = json.loads(installed_raw), json.loads(smoke_raw)
        require(
            installed["schema"] == "hepta.rbe-openssh-image.install.v1"
            and installed["architecture"] == arch
            and installed["uid"] == installed["gid"] == 1000,
            "installer receipt identity mismatch",
        )
        require(
            all(
                installed["after_packages"].get(k) == v
                for k, v in installed["before_packages"].items()
            ),
            "baseline installed package changed",
        )
        require(
            installed["before_critical_files"] == installed["after_critical_files"],
            "baseline critical file changed",
        )
        require(
            smoke["schema"] == "hepta.rbe-openssh-image.tool-smoke.v1"
            and smoke["architecture"] == arch
            and smoke["uid"] == smoke["gid"] == 1000
            and smoke["executable"] == installed["openssh_executable"],
            "smoke identity mismatch",
        )
        expected = [
            (algorithm, namespace, accepted)
            for algorithm in ("sha256", "sha512")
            for namespace, accepted in (
                ("hepta-rbe-tool-smoke", True),
                ("wrong-namespace", False),
                ("hepta-rbe-tool-smoke", False),
            )
        ]
        require(
            [
                (x["hash_algorithm"], x["namespace"], x["accepted"])
                for x in smoke["cases"]
            ]
            == expected
            and all(
                (x["actual_exit_code"] == 0) == x["accepted"] for x in smoke["cases"]
            ),
            "real SSHSIG smoke cases differ",
        )
        (evidence.root / "install.json").write_bytes(installed_raw)
        (evidence.root / "tool-test.json").write_bytes(smoke_raw)
        json_write(evidence.root / "image-config.json", config)
        (evidence.root / "platform-manifest.json").write_bytes(raw_manifest)
        qualification = {
            "schema": "hepta.rbe-openssh.build.v1",
            "status": "image-only-qualified",
            "identity": identity,
            "architecture": arch,
            "base": baseline_ref,
            "deadline_unix_ns": evidence.deadline_unix_ns,
            "oci_archive": {
                "file": archive.name,
                "bytes": archive.stat().st_size,
                "sha256": sha_file(archive),
            },
            "platform_manifest": descriptor,
            "image_config_digest": manifest["config"]["digest"],
            "baseline_file_sha256": sha_file(evidence.root / "baseline-image.json"),
            "install_sha256": hashlib.sha256(installed_raw).hexdigest(),
            "smoke_sha256": hashlib.sha256(smoke_raw).hexdigest(),
            "original_operator_tests_run": False,
            "registry_write_attempted": False,
        }
        evidence.remaining()
        json_write(evidence.root / "qualification.json", qualification)
        evidence.state.update(
            status="image-only-qualified", qualification=qualification
        )
    finally:
        if created:
            # The final 30 seconds are reserved within the same 1200-second deadline.
            evidence.command(
                ["docker", "buildx", "rm", "--force", builder],
                capture=False,
                cleanup=True,
            )


def main():
    evidence = Evidence("build", sys.argv[1], 1200)
    try:
        build(evidence)
    except BaseException as error:
        evidence.finish(error)
        raise
    else:
        evidence.finish()


if __name__ == "__main__":
    main()
