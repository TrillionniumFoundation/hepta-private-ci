# Live-shell status and organ qualification

`hepta --serve-ui` opens and verifies the existing schema-v5 stores before serving.
`GET /api/hepta/runtime` calls `HeptaRuntime::status_json`, which observes the
host-owned `RuntimeStateAdapter` once and serializes `RuntimeStatus` directly.
The existing JSON schema, route inventory, 64 KiB response bound and all eight
closed-effect flags are unchanged. Store integrity, private-path validation,
empty-WAL admission and read-only opening are not bypassed.

A fixed two-node graph is not needed to observe an already-open state adapter.
The product path therefore does not initialize a CNS hierarchy, allocate organ
handlers or acquire a graph-dispatch mutex. Concurrent calls rely on the
adapter's existing `Send + Sync` contract. Trusted status adapters must return
promptly and must not create, migrate or mutate stores while being observed.
`/healthz` remains process liveness, not evidence of learning or effect readiness.

`src/organs.rs` is retained under `cfg(test)` as a qualification-only consumer of
the existing control-plane graph. Its generation, route, size, quarantine,
shutdown and no-direct-fallback checks remain exercised by `organs_tests.rs`.
It is not a production caller, arbitrary plugin loader or sandbox. Actual
control-plane product use remains the Agentd cognitive-context planner; removing
this status wrapper does not remove the planning or organ lifecycle APIs.

`status_tests.rs` covers the product adapter observation, unchanged serialization,
no state creation, response-size rejection and concurrent requests. Existing
native-gateway and open-existing tests retain HTTP and verified-store coverage.
Run `just test --locked -p codex-hepta-runtime -p codex-hepta-control-plane
-p codex-hepta-native-gateway` from `codex-rs` (as one command).
Tests do not establish deployment, physical embodiment or longitudinal efficacy.
