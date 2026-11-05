"""Test-only Fleet publication fixtures with one physical type identity.

Cargo enables Fleet's qualification helpers through dev-dependencies. Bazel
keeps a separate test closure so the ordinary product libraries and binaries
do not acquire that feature. Agent protocol carries Fleet's AgentLifecycle,
so it belongs to this closure as well as the process owners. Worker Host also
exposes Agentd configuration and neural pin types across its public API.
"""

FLEET_RELEASE_TEST_DEPENDENCIES = {
    "//codex-rs/hepta-fleet": "//codex-rs/hepta-fleet:hepta-fleet-test-lib",
    "//codex-rs/hepta-agent-protocol": "//codex-rs/hepta-agent-protocol:hepta-agent-protocol-test-lib",
    "//codex-rs/hepta-supervisor": "//codex-rs/hepta-supervisor:hepta-supervisor-test-lib",
    "//codex-rs/hepta-agentd": "//codex-rs/hepta-agentd:hepta-agentd-fleet-test-lib",
    "//codex-rs/hepta-infer-worker-host": "//codex-rs/hepta-infer-worker-host:hepta-infer-worker-host-fleet-test-lib",
    "//codex-rs/hepta-matrixd": "//codex-rs/hepta-matrixd:hepta-matrixd-test-lib",
}
