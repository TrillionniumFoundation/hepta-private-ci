# Caller manifest migration

Source baseline: PR #5089, commit
`9bbf4bb4d1b5466f62d75d6b70dad4d26ec75d55`.

The original verifier rejects the baseline manifest at `final_use_delivery_raw`:
`durable_store.rs` no longer performs that delivery. Claim admission remains in
that file; actual dispatch now enters `with_dispatch_boundary` from
`durable_dispatch.rs`. The corrected manifest records those exact caller sets.
It also records the existing `deployment_issuer_dependencies.rs` lease checks.

Existing source migrations are reflected throughout the manifest: pinned issuer
readback and writer/effect guards, pinned predecessor rotation, boxed physical
profiles and Notes observations, the boxed original seed, and the guarded
retirement write transaction. The writer/effect token checks remain required in
their owning helper. The transaction helper must retain its immediate writer
lock, publication acknowledgement, managed-owner refusal and final commit-gate
check. Existing ordering and forbidden-marker checks remain enforced.

The two verifier modules, Rust sources, authority table, source roots, ignored
path fragments and required boundary inventory are unchanged. There are still
160 boundaries; two additional protected-file entries cover the moved guards.

## Validation

The five new migration test groups reject the baseline manifest. They exercise
the actual verifier and source files, including a missing dispatch caller, a
stale delivery caller, a confused human-text lookup, stale definition/protected
markers, and removed writer/effect or retirement-transaction guards.

The original 52 caller QA tests plus those five groups pass. The complete
original B4 discovery command also includes the kernel authority and Root admin
tests: **72 passed, 0 skipped**. Its first run exposed the same two stale caller
sets in `KERNEL_AUTHORITY_BOUNDARIES.json`; those data entries are reconciled
without changing the independent checker or public-method classification.

The unchanged original verifier reports `PASS_HEPTA_CALLER_CLOSED_SET` after
scanning all **5,328 Rust files**, with 160 boundaries, 144 protected entries and
`authorityGranted=false`. `RESULTS.json` records the exact source/log hashes.
The original failure and development diagnostics remain in the evidence bundle.
Compressed logs preserve their original bytes; use `gzip -dc` to read them.

```sh
python3 -B scripts/verify_hepta_callers.py self-test
python3 -B scripts/verify_hepta_callers.py verify
python3 -B -m unittest discover -s qa/b4-no-bypass -p 'test_*.py' -v
```

## Related draft corrections

PR #5157's retained-human-text lookup pattern is already correct at this
baseline and remains unchanged. The definition marker corrections in #5162,
#5182 and #5187 agree with the inspected source. This patch also reconciles the
protected-file and ordering entries that those narrow corrections leave stale.
The new regression file is separate from their appended QA test classes.

These are source-proof results. They do not grant runtime authority, qualify a
Memory adoption, or substitute for the integrated candidate's required CI.
