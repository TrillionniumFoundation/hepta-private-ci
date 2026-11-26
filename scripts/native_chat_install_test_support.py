"""Public source-only installer fixture, never a Root request or credential."""

import native_chat_install_io as io

AGENT = "3ad2bb64-09ba-4811-b892-466c5fd952df"


def fixture():
    policy = io.encode(
        {
            "version": 1,
            "workload_uid": 986,
            "agent_workload_uids": {AGENT: 986},
            "controller_principal": {
                "uid": 984,
                "gid": 973,
                "desktop_uid": 1000,
                "gateway_cgroup": "/system.slice/hepta-private-ci-gateway.service",
                "gateway_executable": "/opt/hepta-private-ci/old/bin/hepta",
            },
        }
    )
    unit = b"[Service]\nUser=984\nGroup=973\nNoNewPrivileges=yes\nCapabilityBoundingSet=\nAmbientCapabilities=\nExecStart=/opt/hepta-private-ci/old/bin/hepta --serve-ui --listen 127.0.0.1:7374 --state-root /var/lib/hepta-private-ci-gateway --auth-keyring-account original-read --auth-capability-file /etc/hepta-private-ci/native-gateway/read.capability --observer-socket /var/lib/hepta-private-ci/fleet/run/observer/ctl --observer-owner-uid 0 --controller-socket /var/lib/hepta-private-ci/fleet/run/controller/ctl --controller-owner-uid 0 --lifecycle-auth-keyring-account original-write --lifecycle-capability-file /etc/hepta-private-ci/native-gateway/lifecycle.capability\n"
    desktop = io.encode(
        {
            "endpoint_manifest": "/home/user/.config/hepta-native/endpoint.json",
            "trusted_keys": "/home/user/.config/hepta-native/trust.json",
            "state_dir": "/home/user/.local/state/hepta-native",
            "lifecycle_keyring_account": "original-write",
        }
    )
    pins = {
        "gateway": (
            "hepta-native-gateway",
            "b83ebaaaece7127d36c934454c93e43aed3882c8b8c8ed37ba9bd4a4ca1dbc23",
        ),
        "bridge": (
            "hepta-native-chat-bridge",
            "a6b2ce0e1b4a212cb322158f6fb6c6f52b41d72f4471ecb39a9f7f07f7711e4f",
        ),
        "fleetctl": (
            "hepta-fleetctl",
            "2d20b1cb29d756cc434457539ee4a24e743f16f9606b16ea98584f80fa5096ed",
        ),
        "renderer": (
            "hepta-robrix",
            "fe142f1a05e242933ee3ef5df327a1e07d39ce7c85991c6cf0be32970709aaaa",
        ),
        "credential_helper": (
            "hepta-native-credential",
            "2b81b86b2b919a775176dd7c01ff0db19569eda5e4048bda6c09feb74cd9db42",
        ),
        "renderer_manifest": (
            "bundle-manifest.json",
            "b59d1f0eb687285254b1c345f4455e9be6f6f161f7a09953aa7c44f2dd3db811",
        ),
    }
    request = {
        "schema": "hepta.native-chat.install-request.v1",
        "installation_id": "45053344-0236-4846-9a85-f5c59e3d77c2",
        **{
            role: {"path": f"/opt/hepta-private-ci/new/{name}", "sha256": sha}
            for role, (name, sha) in pins.items()
        },
        "bridge_template": {
            "path": "/opt/hepta-private-ci/new/bridge.service.in",
            "sha256": "ad76a41d57fb1ccfe127c8659d0a2d20b0d281c182a31cbc478252ccd7d240eb",
        },
        "desktop_config": {
            "path": "/home/user/.config/hepta-native/config.json",
            "sha256": io.digest(desktop),
        },
        "original_policy_sha256": io.digest(policy),
        "original_gateway_unit_sha256": io.digest(unit),
        "agents": [
            {
                "agentId": AGENT,
                "workspace": "/home/user/project",
                "managedProject": {
                    "name": "Original Agent",
                    "idempotencyKey": f"hepta.native-chat.project.v1:{AGENT}",
                },
            }
        ],
    }
    return request, policy, unit, desktop
