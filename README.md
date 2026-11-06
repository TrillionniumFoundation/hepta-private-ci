# Hepta

Hepta is a modular, local-first agent system. The canonical development plan,
module ownership and implementation boundaries are documented in
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## Implementation readiness

Start with the canonical
[implementation-readiness index](docs/readiness/README.md). It explains the
closed-world specification registry, source/implementation evidence, external
gates and the limits of each status. Documentation closure is not runtime
activation, production acceptance or release authority.

The machine-readable readiness records are:

- [READINESS.json](docs/readiness/READINESS.json)
- [STATUS_MODEL.json](docs/readiness/STATUS_MODEL.json)
- [PROTOCOLS.json](docs/readiness/PROTOCOLS.json)
- [GAPS.json](docs/readiness/GAPS.json)
- [Generated status](docs/STATUS.md)

## Verify the readiness records

Run the repository verifier from the workspace root:

```sh
python3 scripts/hepta-readiness.py verify
```

The verifier checks the registered documents, module bindings, protocols,
gaps, generated status and required discovery links. A passing documentation
check does not certify deployed behavior, real-hardware performance, model
efficacy, safety approval or production qualification.
