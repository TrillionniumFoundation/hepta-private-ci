# control_engineering_v2

Lane G owns durable local engineering coordination, authenticated multidimensional
work orchestration, bounded candidate qualification and authenticated review eligibility. Run from the repository root:

```sh
PYTHONPATH=tools/hepta-engineering-control python3 -m control_engineering_v2 --help
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s tools/hepta-engineering-control -p 'test_*.py'
```

Installing `tools/hepta-engineering-control` also provides `hepta-engineering`.
Commands are `schedule`, `candidates`, `sandbox` and `production-readiness`; all
accept bounded JSON inputs. The CLI is a local compatibility surface. New product
callers use `issue_verified_work_envelope`, signed `WorkCompletionReceipt` values,
`plan_engineering_work`/`persist_orchestration_generation`, candidate bundles and
the v2 evidence/seal path.
The implementation guide, component map and security profile live in
[`docs/modules/control.engineering/`](../../../docs/modules/control.engineering/IMPLEMENTATION.md).
`SCHEMA.sql` is the sole executable schema, version 5. No import-time patches or
registry-count validators are required. Linux strong isolation must pass the actual
Bubblewrap probe; portable fixture success cannot become strong review evidence.
The named repository caller is `engineering-product-gate-v2`; it is read-only and
never imports the legacy boolean-only integration module. Test/evaluator paths are
unconditionally candidate-immutable. Host strong-sandbox parallelism is capped at
eight and infrastructure retries at two. Multi-host writes, audit anchoring and
production verifier keys require fresh external signed receipts. Review eligibility,
merge-queue proposals and dormant proposals do not merge, activate or deploy changes.
