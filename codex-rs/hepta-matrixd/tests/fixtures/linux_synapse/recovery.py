"""Always-step recovery of only this invocation's labelled test infrastructure."""

from pathlib import Path
import re
import uuid

from .docker_control import DockerControl
from .files import describe, physical, read_json, write_json
from .orchestrate import host_commands


def recover(args):
    root = physical(Path(args.output).absolute())
    output = root / ("teardown-recovery-" + uuid.uuid4().hex)
    output.mkdir(mode=0o700)
    commands = host_commands(args, output)
    record = {
        "schema": "hepta.synapse.linux.recovery.v1",
        "status": "started",
        "qualification_executed": False,
        "promotion_allowed": False,
        "owners": [],
    }
    write_json(output / "STARTED.json", record)
    try:
        for phase in ("preparation", "qualification"):
            owner_path = root / phase / "RESOURCE_OWNER.json"
            if not owner_path.exists():
                continue
            owner = read_json(owner_path)
            if owner[
                "schema"
            ] != "hepta.synapse.linux.resource-owner.v1" or not re.fullmatch(
                r"hepta-linux-[0-9a-f]{32}", owner["prefix"]
            ):
                raise ValueError(
                    "Recovery resource owner is not a generated qualification identity"
                )
            socket = Path(args.docker_socket).resolve(strict=True)
            if (
                owner["label"] != "hepta.linux.qualification=" + owner["prefix"]
                or owner["docker_socket"] != str(socket)
                or owner["docker_tool"] != commands.tools["docker"]
            ):
                raise ValueError(
                    "Recovery would use a different label, socket or actual Docker tool"
                )
            phase_output = output / phase
            phase_output.mkdir(mode=0o700)
            # Recovery has no image/build or production authority. It can only
            # call the same label-verifying bounded teardown implementation.
            control = object.__new__(DockerControl)
            control.commands, control.output, control.contract = (
                commands,
                phase_output,
                None,
            )
            control.socket, control.prefix, control.label = (
                socket,
                owner["prefix"],
                owner["label"],
            )
            control.containers, control.networks, control.volumes = [], [], []
            receipt = control.cleanup()
            record["owners"].append(
                {
                    "phase": phase,
                    "owner": describe(owner_path),
                    "all_owned_resources_absent": receipt["all_owned_resources_absent"],
                    "teardown": describe(phase_output / "TEARDOWN.json"),
                }
            )
        if not all(item["all_owned_resources_absent"] for item in record["owners"]):
            raise ValueError("Recovery did not remove every owned fixture resource")
        record["status"] = "teardown_only_not_qualified"
    except BaseException as error:
        record.update(
            status="failed", error_type=type(error).__name__, error=str(error)
        )
        raise
    finally:
        record["commands"] = commands.records
        write_json(output / "RESULT.json", record)
    return record
