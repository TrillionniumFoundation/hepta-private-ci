# Hepta

This repository contains Hepta's control, runtime and organ integration code, together with development specifications and qualification tooling.

## Development and technical documentation

- [Development plan and verification workflow](docs/DEVELOPMENT.md)
- [Module ownership and technical guides](docs/modules/README.md)
- [CNS and organ architecture](docs/cns/README.md)
- [Implementation readiness specifications](docs/readiness/README.md)
- [Adaptive learning specifications](docs/learning/README.md)
- [Repository contributor instructions](AGENTS.md)

The guides distinguish target designs from current native implementations. Documentation closure does not establish runtime readiness, device qualification or release approval; those require the corresponding exact-candidate execution evidence.

The readiness index describes coding-entry contracts and evidence boundaries. Documentation readiness does not imply source implementation, runtime activation, production authority, independent acceptance, or release.

## Implementation readiness records

The machine-readable records expose the closed-world specification registry,
status vocabulary, typed protocols and bounded gaps:

- [READINESS.json](docs/readiness/READINESS.json)
- [STATUS_MODEL.json](docs/readiness/STATUS_MODEL.json)
- [PROTOCOLS.json](docs/readiness/PROTOCOLS.json)
- [GAPS.json](docs/readiness/GAPS.json)
- [Generated status](docs/STATUS.md)

Verify these records from the repository root:

```sh
python3 scripts/hepta-readiness.py verify
```

This check validates the documentation registry and discovery links. It does
not certify deployed behavior, hardware performance, model efficacy or release
qualification.

## Verify the development documentation

Run from the repository root:

```sh
python3 scripts/hepta-docs.py verify --profile development
```

The development plan and module guides name the additional source, test and qualification checks required for each affected boundary.
