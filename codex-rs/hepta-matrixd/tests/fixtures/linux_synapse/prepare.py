"""Separate online preparation of a fixed builder archive, official tools and seed."""

import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil

from .contract import ENTRY, PLATFORM, RUST_BASE_ID, RUST_BASE_REF, SCHEMA, SYNAPSE_ID
from .contract import (
    SYNAPSE_REF,
    SYNAPSE_REVISION,
    SYNAPSE_VERSION,
    TARGET,
    load_contract,
    reject_compiler_overrides,
)
from .docker_control import DockerControl, mount, process_command
from .files import (
    checksum,
    copy_file,
    describe,
    inventory,
    physical,
    read_json,
    write_json,
)
from .orchestrate import bound, host_commands
from .prep_tools import prepare_tools
from .source import prepare_source


SNAPSHOT = "20261026T000000Z"
PACKAGES = (
    "binutils",
    "bubblewrap",
    "build-essential",
    "ca-certificates",
    "cmake",
    "curl",
    "file",
    "git",
    "libasound2-dev",
    "libcap-dev",
    "libssl-dev",
    "libudev-dev",
    "make",
    "perl",
    "pkg-config",
    "procps",
    "python3",
)
APT_CAPTURE = """import hashlib,json,pathlib,subprocess
def records(root):
    answer={}
    for p in sorted(pathlib.Path(root).rglob('*')):
        if p.is_file() and not p.is_symlink():
            answer[str(p)]={'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
    return answer
value={'schema':'hepta.synapse.linux.apt-materialization.v1',
       'installed_packages':subprocess.check_output(['dpkg-query','-W','-f=${Package}\\t${Version}\\t${Architecture}\\n']).decode(),
       'downloaded_debs':records('/var/cache/apt/archives'),
       'signed_repository_indexes':records('/var/lib/apt/lists'),
       'apt_sources':records('/etc/apt/sources.list.d'),
       'network_phase':'preparation only; no qualification yet'}
pathlib.Path('/hepta-prep-evidence/apt-materialization.json').write_text(json.dumps(value,indent=2,sort_keys=True)+'\\n')
"""
BOOTSTRAP_PROBE = """import hashlib,json,pathlib,sys
def identity(p):
 p=pathlib.Path(p).resolve(strict=True)
 return {'path':str(p),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
print(json.dumps({'git':identity('/usr/bin/git'),'python3':identity(sys.executable)}))
"""


def preparation(args):
    output = physical(Path(args.output).absolute())
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    record = {
        "schema": "hepta.synapse.linux.preparation.v1",
        "status": "started",
        "qualification_executed": False,
        "promotion_allowed": False,
        "online_preparation": True,
        "commands": [],
    }
    write_json(output / "STARTED.json", record)
    commands, control = None, None
    try:
        reject_compiler_overrides(os.environ)
        if (platform.system(), platform.machine()) != ("Linux", "aarch64"):
            raise ValueError(
                "Online preparation must run on the actual native ARM64 host"
            )
        commands = host_commands(args, output)
        for label, reference in (
            ("rust-base", RUST_BASE_REF),
            ("original-synapse", SYNAPSE_REF),
        ):
            commands.run(
                "docker",
                ["pull", "--platform", PLATFORM, reference],
                label="online-pull-" + label,
            )
        base = {
            "image": {
                "reference": RUST_BASE_REF,
                "config_id": RUST_BASE_ID,
                "os": "linux",
                "architecture": "arm64",
            },
            "synapse": {"version": SYNAPSE_VERSION, "revision": SYNAPSE_REVISION},
        }
        control = DockerControl(commands, output, base, args.docker_socket)
        control.preflight()
        source_dir = output / "source"
        source_dir.mkdir(mode=0o700)
        source = prepare_source(
            Path(args.restored_root).resolve(),
            Path(args.producer).resolve(),
            args.producer_result_sha256,
            args.source_commit,
            Path(args.worktree).absolute(),
            source_dir,
            commands,
        )
        checkout = Path(source["source_root"])
        bundle = prepare_tools(output)
        context = output / "builder-context"
        context.mkdir(mode=0o700)
        (context / "capture_apt.py").write_text(APT_CAPTURE)
        dockerfile = (
            f"FROM {RUST_BASE_REF}\n"
            "USER root\nCOPY capture_apt.py /hepta-prep-evidence/capture_apt.py\n"
            "RUN set -eu; rm -f /etc/apt/sources.list /etc/apt/sources.list.d/* /etc/apt/apt.conf.d/docker-clean; "
            f"printf '%s\\n' 'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/{SNAPSHOT}/ bookworm main' "
            f"'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian-security/{SNAPSHOT}/ bookworm-security main' "
            "> /etc/apt/sources.list.d/hepta-fixed-snapshot.list; "
            "dpkg-query -W > /hepta-prep-evidence/packages.before.txt; "
            "apt-get update; apt-get -y --no-install-recommends --allow-downgrades install "
            + " ".join(PACKAGES)
            + "; "
            "python3 /hepta-prep-evidence/capture_apt.py; apt-get clean\n"
        )
        (context / "Dockerfile").write_text(dockerfile)
        preparation_inputs = {
            "schema": "hepta.synapse.linux.builder-preparation-inputs.v1",
            "base_reference": RUST_BASE_REF,
            "base_config_id": RUST_BASE_ID,
            "debian_snapshot": SNAPSHOT,
            "packages": PACKAGES,
            "context": inventory(context),
            "apt_signature_validation": True,
            "historical_release_expiry_exception": "Only check-valid-until is disabled for the fixed historical snapshot; signature verification remains mandatory.",
            "source_commit": args.source_commit,
            "producer_result_sha256": args.producer_result_sha256,
        }
        write_json(output / "BUILDER_PREPARATION_INPUTS.json", preparation_inputs)
        image_id_path = output / "BUILDER_IMAGE_ID.txt"
        commands.run(
            "docker",
            [
                "build",
                "--no-cache",
                "--pull=false",
                "--platform",
                PLATFORM,
                "--network=default",
                "--iidfile",
                str(image_id_path),
                "--file",
                str(context / "Dockerfile"),
                str(context),
            ],
            label="online-fixed-builder-materialization",
        )
        image_id = image_id_path.read_text().strip()
        inspected = control.json(
            ["image", "inspect", image_id], "derived-builder-inspect"
        )
        if (
            len(inspected) != 1
            or inspected[0]["Id"] != image_id
            or (inspected[0]["Os"], inspected[0]["Architecture"]) != ("linux", "arm64")
        ):
            raise ValueError(
                "Derived builder identity/platform did not materialize correctly"
            )
        image_tar = output / "builder-image.tar"
        commands.run(
            "docker",
            ["image", "save", "--output", str(image_tar), image_id],
            label="save-complete-derived-builder",
        )
        tar_identity = describe(image_tar)
        image_archive = output / "builder-image.tar.gz"
        with image_tar.open("rb") as original, image_archive.open("xb") as compressed:
            with gzip.GzipFile(
                filename="", fileobj=compressed, mode="wb", compresslevel=6, mtime=0
            ) as stream:
                shutil.copyfileobj(original, stream, 1024 * 1024)
            compressed.flush()
            os.fsync(compressed.fileno())
        restored = hashlib.sha256()
        restored_size = 0
        with gzip.open(image_archive, "rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                restored.update(block)
                restored_size += len(block)
        if {"bytes": restored_size, "sha256": restored.hexdigest()} != tar_identity:
            raise ValueError(
                "Complete builder archive failed actual decompression/readback"
            )
        write_json(
            output / "BUILDER_ARCHIVE_READBACK.json",
            {
                "tar": tar_identity,
                "gzip": describe(image_archive),
                "all_uncompressed_bytes_reread": True,
                "docker_image_id": image_id,
                "note": "Derived local config ID plus complete archive; not an invented upstream RepoDigest.",
            },
        )
        image_tar.unlink()
        apt = control.create(
            "apt-evidence",
            ["--network", "none", "--entrypoint", "/usr/bin/cat"],
            image_id,
            ["/hepta-prep-evidence/apt-materialization.json"],
        )
        control.start(apt, attach=True)
        _, apt_log = commands.run("docker", ["logs", apt], label="actual-apt-inputs")
        copy_file(apt_log, output / "APT_MATERIALIZATION.json")
        read_json(output / "APT_MATERIALIZATION.json")
        bootstrap = control.create(
            "bootstrap-probe",
            ["--network", "none", "--entrypoint", "/usr/bin/python3"],
            image_id,
            ["-I", "-c", BOOTSTRAP_PROBE],
        )
        control.start(bootstrap, attach=True)
        _, probe_log = commands.run(
            "docker", ["logs", bootstrap], label="actual-bootstrap-tools"
        )
        bootstrap_tools = read_json(probe_log)
        plan = output / "plan"
        plan.mkdir(mode=0o700)
        copy_file(source_dir / "SOURCE_SEAL.json", plan / "SOURCE_SEAL.json")
        tool_output = output / "tool-probe"
        tool_output.mkdir(mode=0o700)
        probe_plan = {
            "schema": "hepta.synapse.linux.preparation-plan.v1",
            "source_seal": bound(
                plan / "SOURCE_SEAL.json", "/hepta-plan/SOURCE_SEAL.json"
            ),
            "bootstrap_git": bootstrap_tools["git"],
            "output": "/hepta-probe",
        }
        write_json(plan / "PROBE_PLAN.json", probe_plan)
        shared = [
            (checkout, str(checkout)),
            (Path(source["private_git_authority"]), source["private_git_authority"]),
            (
                Path(source["original_object_directory"]),
                source["original_object_directory"],
            ),
            (bundle, "/hepta-tools"),
            (plan, "/hepta-plan"),
        ]
        options = [argument for src, dst in shared for argument in mount(src, dst)]
        probe = control.create(
            "native-tool-probe",
            [
                "--network",
                "none",
                "--read-only",
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                *options,
                *mount(tool_output, "/hepta-probe", writable=True),
                "--entrypoint",
                bootstrap_tools["python3"]["path"],
            ],
            image_id,
            [
                "-I",
                str(checkout / ENTRY),
                "probe-inside",
                "--plan",
                "/hepta-plan/PROBE_PLAN.json",
                "--plan-sha256",
                checksum(plan / "PROBE_PLAN.json"),
            ],
        )
        control.start(probe, attach=True)
        observed = read_json(tool_output / "TOOL_PROBE.json")
        proxy_client = output / "proxy-control-tool"
        copy_file(
            Path(commands.tools["docker"]["path"]),
            proxy_client / "docker",
            executable=True,
        )
        client_probe = control.create(
            "proxy-client-compatibility",
            [
                "--network",
                "none",
                "--read-only",
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                *mount(proxy_client, "/hepta-control"),
                "--entrypoint",
                observed["tools"]["env"]["path"],
            ],
            image_id,
            [
                "-i",
                "LANG=C.UTF-8",
                "LC_ALL=C.UTF-8",
                "/hepta-control/docker",
                "--version",
            ],
        )
        control.start(client_probe, attach=True)
        actual_client = control.commands.text(
            "docker", ["logs", client_probe], label="actual-proxy-client-version"
        )
        host_client = control.commands.text(
            "docker", ["--version"], label="host-docker-client-version"
        )
        if (
            control.inspect(client_probe, "proxy-client-probe-exit")["State"][
                "ExitCode"
            ]
            != 0
            or actual_client != host_client
        ):
            raise ValueError(
                "The exact host Docker client did not execute in the fixed proxy image"
            )
        write_json(
            output / "PROXY_CLIENT_PROBE.json",
            {
                "actual_client": describe(proxy_client / "docker"),
                "version": actual_client,
                "image_config_id": image_id,
                "socket_mounted": False,
                "network_mode": "none",
                "native_execution_completed": True,
                "qualification_executed": False,
            },
        )
        contract = {
            "schema": SCHEMA,
            "image": {
                "reference": image_id,
                "config_id": image_id,
                "os": "linux",
                "architecture": "arm64",
                "archive": describe(image_archive),
                "base_reference": RUST_BASE_REF,
                "base_config_id": RUST_BASE_ID,
                "preparation_inputs_sha256": checksum(
                    output / "BUILDER_PREPARATION_INPUTS.json"
                ),
            },
            "target": TARGET,
            "rust_release": "1.96.0",
            "nextest_version": "0.9.103",
            "tools": observed["tools"],
            "tool_bundle": {"mount_path": "/hepta-tools", "files": inventory(bundle)},
            "control_docker": {
                "path": "/hepta-control/docker",
                **{key: commands.tools["docker"][key] for key in ("bytes", "sha256")},
            },
            "synapse": {
                "reference": SYNAPSE_REF,
                "config_id": SYNAPSE_ID,
                "version": SYNAPSE_VERSION,
                "revision": SYNAPSE_REVISION,
                "platform": PLATFORM,
            },
        }
        write_json(output / "BUILDER_SEAL.json", contract)
        load_contract(
            output / "BUILDER_SEAL.json", checksum(output / "BUILDER_SEAL.json")
        )
        copy_file(output / "BUILDER_SEAL.json", plan / "BUILDER_SEAL.json")
        fetch_plan = {
            "schema": "hepta.synapse.linux.prefetch-plan.v1",
            "source_seal": probe_plan["source_seal"],
            "builder_seal": bound(
                plan / "BUILDER_SEAL.json", "/hepta-plan/BUILDER_SEAL.json"
            ),
        }
        write_json(plan / "FETCH_PLAN.json", fetch_plan)
        fetch_output = output / "prefetch"
        fetch_output.mkdir(mode=0o700)
        fetch = control.create(
            "online-cargo-prefetch",
            [
                "--network",
                "bridge",
                "--read-only",
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                *options,
                *mount(fetch_output, "/hepta-prefetch", writable=True),
                "--entrypoint",
                contract["tools"]["env"]["path"],
            ],
            image_id,
            process_command(
                contract,
                checkout / ENTRY,
                [
                    "seed-inside",
                    "--plan",
                    "/hepta-plan/FETCH_PLAN.json",
                    "--plan-sha256",
                    checksum(plan / "FETCH_PLAN.json"),
                ],
            )[1:],
        )
        control.start(fetch, attach=True)
        result = read_json(fetch_output / "PREFETCH_RESULT.json")
        if result["status"] != "prepared_not_qualified":
            raise ValueError(
                "Online complete dependency seed did not freeze successfully"
            )
        record.update(
            status="prepared_pending_teardown",
            builder_seal=describe(output / "BUILDER_SEAL.json"),
            image_archive=describe(image_archive),
            seed_ledger=describe(fetch_output / "SEED_LEDGER.json"),
            source_candidate_tree=source["candidate_tree"],
            source_producer_result_sha256=args.producer_result_sha256,
            official_tools=describe(output / "TOOL_ARCHIVES.json"),
            actual_apt_inputs=describe(output / "APT_MATERIALIZATION.json"),
        )
    except BaseException as error:
        record.update(
            status="failed", error_type=type(error).__name__, error=str(error)
        )
        raise
    finally:
        if control is not None:
            teardown = control.cleanup()
            if (
                record["status"] == "prepared_pending_teardown"
                and teardown["all_owned_resources_absent"]
            ):
                record["status"] = "prepared_not_qualified"
            elif not teardown["all_owned_resources_absent"]:
                record.update(status="failed", teardown_failed=True)
        if commands is not None:
            record["commands"] = commands.records
        write_json(output / "PREPARATION_RESULT.json", record)
    if record["status"] != "prepared_not_qualified":
        raise RuntimeError(
            "Preparation did not complete all materialization and teardown gates"
        )
    return record
