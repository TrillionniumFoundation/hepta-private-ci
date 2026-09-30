# `learning.operator` implementation and evidence status

[STATUS.json](../../docs/modules/learning.operator/STATUS.json) is the canonical
implementation/acceptance state. Its schema is
[STATUS.schema.json](../../docs/modules/learning.operator/STATUS.schema.json).
The generic shadow coordinator is implemented, while its actual owner-port
adapters and default runtime caller remain uncomposed. The evaluated read-only
ranker and signed component protocol E2E are separate implemented surfaces.
Canonical wire adapters also remain repository work.

The repository distinguishes three evidence facts:

1. **Mapped source/test identity:** source or a test exists and is connected to a requirement.
2. **Candidate execution:** a literal command ran for an exact SHA/tree and ended in a recorded terminal state.
3. **External acceptance:** independent scientific efficacy, target-host capacity, operational acceptance, promotion, canary or release evidence.

An implementation map is navigation and source identity, not a passing execution
receipt. Missing artifacts, action-required runs with no jobs, cancelled attempts
and missing command records are missing evidence, not success. Results from
different candidates or workflow attempts cannot be combined.

The current authoritative repository workflow is
`Learning operator authoritative qualification`. It is called by protected
blocking CI and can be explicitly dispatched. Its artifact family is
`learning-operator-authoritative-<sha>` and contains per-stage `passed`, `failed`
or `not_run` receipts plus one readiness manifest binding exact source, base,
ordered-parent deterministic merge, workflow/run attempt, runner, toolchain,
lockfile, implementation projection and evidence-log hashes. Required non-passing
stages make merge readiness false; production qualification remains false.
The real main merge SHA must execute the same qualification again.

Historical `Learning operator exact-source diagnostics` artifacts retain their
original `status.json` format and
[gate-status schema](learning-operator-status.schema.json). Their
`learning-operator-source-<sha>`, `learning-operator-rust-<sha>` and
`learning-operator-merge-<sha>-<base>` families record commands, duration,
environment, terminal states and logs. They are diagnostic records, not the
canonical module status or a replacement for current authoritative qualification.

Three-observation regression profiles, immutable load tests and fixture-key
virtual-clock protocol E2E do not establish target-host tail latency or real
future-window benefit. Static selected models also do not observe later owner
revocation: each host final use refreshes current authority and registry witnesses.
Activation and release remain false.
