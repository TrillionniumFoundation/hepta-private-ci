# Hepta / Codex

See [development guidance](docs/DEVELOPMENT.md) for the repository's architecture
and contribution requirements.

## Implementation readiness

The [implementation-readiness index](docs/readiness/README.md) links the registered
module contracts, protocols, gap dispositions, execution plans, and validation
commands. Specification status and executed implementation evidence are tracked
separately there.

Run the readiness verifier from the repository root:

```bash
python3 scripts/hepta-readiness.py verify
```

## Native HIA components

The [HIA migration guide](hia/README.md) records the pinned compiler, native build
instructions, production caller integration, differential tests, and remaining
migration work.
