# Lane B runtime closure

This directory is the canonical Lane B projection for the eleven registered runtime modules. It closes repository-internal documentation, native-source mapping, branch-trigger and CI-evidence blockers without converting those facts into product-runtime or release authority.

## Read order

1. `LANE_B_CLOSURE.json` — lifecycle states, current capability, target capability, exact source mappings, remaining bridges and evidence boundaries.
2. `STATUS.md` — generated closure projection.
3. `../modules/<module>/TECHNICAL.md` — stable module guide with the generated Lane B current/target/bridge section.
4. `../../qualification/module-execution-dossiers/NATIVE_BINDINGS.json` — exact blob and symbol observations.
5. `../../.github/workflows/hepta-lane-b-closure.yml` — read-only exact-source, focused package and deterministic-merge gate.

## Interpretation

`source_mapped` means that current source paths and exported symbols have been inspected and bound to the design surface. It does not mean that the full target operation, product caller, provider, remote effect, deployment, operator acceptance, promotion or release has been proved.

Repository-internal blockers may be closed by exact candidate documents and CI. The nine `RDY-EXT-*` gates remain external and non-self-certifiable.

## Validation

```bash
python3 scripts/hepta-lane-b-closure.py self-test
python3 scripts/hepta-lane-b-closure.py generate-status --check
python3 scripts/hepta-lane-b-closure.py verify
python3 scripts/hepta_module_doc_metadata.py
python3 scripts/hepta-module-docs.py verify
python3 qualification/module-execution-dossiers/implementation_contracts.py verify-repository
```
