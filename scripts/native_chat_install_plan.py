"""One closed Linux gateway/bridge deployment, using the existing host policy."""

import json
from pathlib import Path
import re
import shlex
import uuid

from native_chat_install_io import canonical, digest, encode, unique_object


POLICY = Path("/etc/hepta-private-ci/local-host.json")
GATEWAY_UNIT = Path("/etc/systemd/system/hepta-private-ci-gateway.service")
GATEWAY_DROPIN = Path(
    "/etc/systemd/system/hepta-private-ci-gateway.service.d/40-native-chat.conf"
)
BRIDGE_UNIT = Path("/etc/systemd/system/hepta-private-ci-chat-bridge.service")
BRIDGE_CONFIG = Path("/etc/hepta-private-ci/native-chat-bridge.json")
CAPABILITY = Path("/etc/hepta-private-ci/native-gateway/chat.capability")
SOCKET = "/run/hepta-private-ci-chat-bridge/ctl"
INSTALL_ROOT = Path("/var/lib/hepta-private-ci/native-chat-installations")
GATEWAY_SERVICE = "hepta-private-ci-gateway.service"
BRIDGE_SERVICE = "hepta-private-ci-chat-bridge.service"
FIELDS = {
    "schema",
    "installation_id",
    "gateway",
    "bridge",
    "renderer",
    "renderer_manifest",
    "credential_helper",
    "fleetctl",
    "bridge_template",
    "desktop_config",
    "original_policy_sha256",
    "original_gateway_unit_sha256",
    "agents",
}
GATEWAY_FLAGS = {
    "--listen",
    "--state-root",
    "--auth-keyring-account",
    "--auth-capability-file",
    "--observer-socket",
    "--observer-owner-uid",
    "--controller-socket",
    "--controller-owner-uid",
    "--lifecycle-auth-keyring-account",
    "--lifecycle-capability-file",
}


def checked(request, policy_bytes, unit_bytes, desktop_bytes):
    if (
        set(request) != FIELDS
        or request["schema"] != "hepta.native-chat.install-request.v1"
    ):
        raise ValueError("unsupported install request")
    install_id = str(uuid.UUID(request["installation_id"]))
    if install_id != request["installation_id"]:
        raise ValueError("installation ID must be a canonical UUID")
    if (
        digest(policy_bytes) != request["original_policy_sha256"]
        or digest(unit_bytes) != request["original_gateway_unit_sha256"]
    ):
        raise ValueError("original host policy or gateway unit changed")
    if digest(desktop_bytes) != request["desktop_config"]["sha256"]:
        raise ValueError("original desktop config changed")
    policy = json.loads(policy_bytes, object_pairs_hook=unique_object)
    controller = policy.get("controller_principal")
    if not controller or (
        controller["uid"],
        controller["gid"],
        controller["desktop_uid"],
        controller["gateway_cgroup"],
    ) != (984, 973, 1000, "/system.slice/hepta-private-ci-gateway.service"):
        raise ValueError("original independent gateway/desktop enrollment is missing")
    desktop = json.loads(desktop_bytes, object_pairs_hook=unique_object)
    allowed_desktop = {
        "endpoint_manifest",
        "trusted_keys",
        "state_dir",
        "final_use_authority",
        "updater_helper",
        "font_file",
        "allowed_roots",
        "allow_clipboard",
        "allow_notifications",
        "lifecycle_keyring_account",
    }
    if set(desktop) - allowed_desktop:
        raise ValueError(
            "original desktop config is incompatible or already chat-enrolled"
        )
    if "chat_keyring_account" in desktop:
        raise ValueError(
            "desktop already has chat enrollment; reconcile its original deployment"
        )
    if "lifecycle_keyring_account" not in desktop:
        raise ValueError("original lifecycle account is missing")
    for name in ("endpoint_manifest", "trusted_keys", "state_dir"):
        if not isinstance(desktop.get(name), str):
            raise ValueError(
                "original desktop is missing a required source/state binding"
            )
        canonical(desktop[name])
    for name in ("final_use_authority", "updater_helper", "font_file"):
        if desktop.get(name) is not None:
            canonical(desktop[name])
    roots = desktop.get("allowed_roots", [])
    if not isinstance(roots, list) or len(roots) > 64:
        raise ValueError("original desktop roots exceed the admitted scope")
    for root in roots:
        canonical(root)
    for name in ("allow_clipboard", "allow_notifications"):
        if name in desktop and type(desktop[name]) is not bool:
            raise ValueError("original desktop options are not typed booleans")
    workload_uids = {
        policy["workload_uid"],
        *(policy.get("agent_workload_uids") or {}).values(),
    }
    if 1000 in workload_uids or 984 in workload_uids:
        raise ValueError("desktop/gateway and workload principals are not independent")
    desktop_path = canonical(request["desktop_config"]["path"])
    if desktop_path.name != "config.json" or desktop_path.parent.name != "hepta-native":
        raise ValueError("requires the original native desktop config")
    unit = unit_bytes.decode()
    settings = {}
    for line in unit.splitlines():
        if line and not line.startswith(("#", "[")) and "=" in line:
            key, value = line.split("=", 1)
            if key in settings:
                raise ValueError("duplicate gateway setting requires explicit review")
            settings[key] = value
    for key, expected in {
        "User": "984",
        "Group": "973",
        "NoNewPrivileges": "yes",
        "CapabilityBoundingSet": "",
        "AmbientCapabilities": "",
    }.items():
        if settings.get(key) != expected:
            raise ValueError("original gateway confinement differs")
    command = settings.get("ExecStart", "")
    if any(char in command for char in "\n\r%$\\\"'"):
        raise ValueError("unsupported gateway command escaping")
    args = shlex.split(command)
    if len(args) != 22 or args[1] != "--serve-ui" or set(args[2::2]) != GATEWAY_FLAGS:
        raise ValueError("original finite gateway flags differ")
    flags = dict(zip(args[2::2], args[3::2], strict=True))
    if (
        flags["--listen"] != "127.0.0.1:7374"
        or flags["--observer-owner-uid"] != "0"
        or flags["--controller-owner-uid"] != "0"
    ):
        raise ValueError("original loopback/owner binding differs")
    if (
        desktop["lifecycle_keyring_account"]
        != flags["--lifecycle-auth-keyring-account"]
    ):
        raise ValueError("desktop lifecycle purpose differs from the original gateway")
    agents = request["agents"]
    if not isinstance(agents, list) or not 1 <= len(agents) <= 16:
        raise ValueError("requires bounded original Agent scopes")
    seen = set()
    for agent in agents:
        if (
            set(agent) != {"agentId", "workspace", "managedProject"}
            or str(uuid.UUID(agent["agentId"])) != agent["agentId"]
            or agent["agentId"] in seen
        ):
            raise ValueError("invalid original Agent scope")
        seen.add(agent["agentId"])
        canonical(agent["workspace"])
        project = agent["managedProject"]
        if (
            set(project) != {"name", "idempotencyKey"}
            or project["idempotencyKey"]
            != f"hepta.native-chat.project.v1:{agent['agentId']}"
            or not 1 <= len(project["name"]) <= 256
        ):
            raise ValueError("requires the stable original ProjectCreate scope")
    for role in (
        "gateway",
        "bridge",
        "renderer",
        "renderer_manifest",
        "credential_helper",
        "fleetctl",
        "bridge_template",
        "desktop_config",
    ):
        pin = request[role]
        if set(pin) != {"path", "sha256"} or not re.fullmatch(
            "[0-9a-f]{64}", pin["sha256"]
        ):
            raise ValueError("invalid immutable input pin")
        canonical(pin["path"])
    admitted = policy.get("agent_workload_uids")
    if not admitted or not seen <= admitted.keys():
        raise ValueError("Chat selectors are not original workload enrollments")
    for role, name in {
        "gateway": "hepta-native-gateway",
        "bridge": "hepta-native-chat-bridge",
        "renderer": "hepta-robrix",
        "credential_helper": "hepta-native-credential",
        "fleetctl": "hepta-fleetctl",
    }.items():
        path = canonical(request[role]["path"])
        if path.name != name or not path.is_relative_to("/opt/hepta-private-ci"):
            raise ValueError("requires the reviewed immutable normal program role")
    if canonical(request["renderer_manifest"]["path"]).name != "bundle-manifest.json":
        raise ValueError("requires the original renderer manifest")
    # These are the actually qualified ordinary programs, not a generic Root
    # executor. Changing the admitted source requires a reviewed new stage.
    qualified = {
        "bridge_template": "ad76a41d57fb1ccfe127c8659d0a2d20b0d281c182a31cbc478252ccd7d240eb",
        "gateway": "b83ebaaaece7127d36c934454c93e43aed3882c8b8c8ed37ba9bd4a4ca1dbc23",
        "bridge": "a6b2ce0e1b4a212cb322158f6fb6c6f52b41d72f4471ecb39a9f7f07f7711e4f",
        "fleetctl": "2d20b1cb29d756cc434457539ee4a24e743f16f9606b16ea98584f80fa5096ed",
        "renderer": "fe142f1a05e242933ee3ef5df327a1e07d39ce7c85991c6cf0be32970709aaaa",
        "credential_helper": "2b81b86b2b919a775176dd7c01ff0db19569eda5e4048bda6c09feb74cd9db42",
        "renderer_manifest": "b59d1f0eb687285254b1c345f4455e9be6f6f161f7a09953aa7c44f2dd3db811",
    }
    if any(request[role]["sha256"] != expected for role, expected in qualified.items()):
        raise ValueError(
            "normal program source has not been qualified for this installation"
        )
    candidate = dict(policy)
    candidate["controller_principal"] = {
        **controller,
        "gateway_executable": request["gateway"]["path"],
    }
    target_policy = policy_bytes if candidate == policy else encode(candidate)
    return {
        "namespace": INSTALL_ROOT / install_id,
        "request": request,
        "original_args": args,
        "desktop": desktop,
        "target_policy": target_policy,
        "target_policy_sha256": digest(target_policy),
        "bridge_config": encode(
            {
                "schema": "hepta.native-chat-root.v1",
                "localHostPolicy": str(POLICY),
                "fleetRoot": "/var/lib/hepta-private-ci/fleet",
                "socket": SOCKET,
                "agents": agents,
            }
        ),
    }


def gateway_args(plan, account=None):
    args = [plan["request"]["gateway"]["path"], *plan["original_args"][2:]]
    if account:
        args += [
            "--chat-socket",
            SOCKET,
            "--chat-owner-uid",
            "0",
            "--chat-auth-keyring-account",
            account,
            "--chat-capability-file",
            str(CAPABILITY),
        ]
    if any(any(c.isspace() or c in "%$\\\"'" for c in arg) for arg in args):
        raise ValueError("unsupported systemd argument escaping")
    return args


def dropin(plan, account=None):
    return (
        "[Service]\nExecStart=\nExecStart="
        + " ".join(gateway_args(plan, account))
        + "\n"
    ).encode()
