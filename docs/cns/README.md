# Hepta CNS and organ architecture

This directory defines the closed reference architecture that maps the existing forty Hepta modules into a distributed central nervous system, brainstem, peripheral nervous system and independently bounded organs. It extends, but does not replace, `docs/DEVELOPMENT.md`.

Read in this order:

1. [`CNS_ARCHITECTURE.json`](CNS_ARCHITECTURE.json) — closed-world anatomy, dependencies, lifecycle and authority posture.
2. [`ORGAN_PROTOCOLS.json`](ORGAN_PROTOCOLS.json) — typed organ, body, sensor, actuation, reflex, outcome, consolidation and human-override protocols.
3. [`TECHNICAL.md`](TECHNICAL.md) — detailed implementation, concurrency, learning, safety and migration semantics.
4. [`GAPS.json`](GAPS.json) — repository reference closure and separately named external capability gates.
5. [`STATUS.md`](STATUS.md) — deterministic generated status.
6. [`../../qualification/cns-organ-reference`](../../qualification/cns-organ-reference) — dependency-free reference and tests.

Validation:

```bash
python3 scripts/hepta-cns.py self-test
python3 scripts/hepta-cns.py generate-status --check
python3 scripts/hepta-cns.py verify
python3 scripts/hepta-paper-evidence.py self-test
python3 scripts/hepta-paper-evidence.py verify
```

Repository reference closure does not activate a physical body, grant effect authority, prove longitudinal improvement, establish biological equivalence or authorize selection, promotion or release.

## Coding-level embodiment and assimilation overlays

Implementation-level timing, sensor, body, reflex, actuator, hardware-in-loop and authorized external-system integration semantics are closed in [`../readiness/EMBODIED_RUNTIME_EXECUTION.md`](../readiness/EMBODIED_RUNTIME_EXECUTION.md) and [`../readiness/EXTERNAL_SYSTEM_ASSIMILATION.md`](../readiness/EXTERNAL_SYSTEM_ASSIMILATION.md).

The complete pre-coding readiness index, including all-module lane bindings, is [`../readiness/README.md`](../readiness/README.md).
