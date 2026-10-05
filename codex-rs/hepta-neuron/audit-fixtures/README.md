# Owner receipt target probes

`owner-receipt-goal-probes.patch` is retained adversarial audit evidence, not an
implemented feature or a passing test suite. It adds three positive probes for
RDY-NEU section 4 and NEU-GV-002 to the actual runtime test fixture. On the
fifth-round baseline `f31847ffe1b42d1ee87a1b89694942c156d858ea`, all three failed:
acknowledged duplicate and restart duplicate returned `Sequence`; a changed
request reused the original tick ID and was accepted. No extra inference was
needed for either rejected duplicate.

Apply only in a disposable checkout from the repository root, then run from
`codex-rs` using the repository runner:

```sh
git apply --check codex-rs/hepta-neuron/audit-fixtures/owner-receipt-goal-probes.patch
git apply codex-rs/hepta-neuron/audit-fixtures/owner-receipt-goal-probes.patch
cd codex-rs
HEPTA_NEXTTEST_FULL_METADATA=1 just test --locked -p codex-hepta-neuron -E 'test(execution_target_)'
```

The recorded result is exit 100, 3 selected failures and 167 filtered tests.
Nextest retries failed cases. The applied probes were removed byte-for-byte from
the implementation test source before final validation; they are not ignored or
reported as passing. Keep the execution targets unchanged until a separately
reviewed bounded durable owner-output/idempotency protocol satisfies them.
