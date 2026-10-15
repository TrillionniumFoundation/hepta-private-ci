# E3 model-input byte-bound filetree fingerprint (research)

**2026-10-15. Draft / SHADOW_ONLY / DENY_ALL.** Parent #2325 at
`b5c732473b17ab9db1f5f928bcffe55bba5dc95b`.

The prior `tree_fingerprint` only hashed sorted file names. A
semantically equivalent JSON reserialization of an admitted receipt or
cohort passed source/schema checks and left that path-only fingerprint
unchanged. Separate source/fit/receipt checks provided some extra
protection, but the fingerprint's meaning was overstated.

`hepta.e3-path-byte-sha256.v2` binds every file's relative path and
actual SHA-256 bytes: four approved metadata files plus 192 original
images, sorted and serialized canonically. The independent reviewer
enforces profile, count, 64-hex digest, pre/post equality and both
model jobs' agreement. Two adversarial source-fixture tests rewrite
unchanged-semantics metadata and require the fingerprint to change.

The source owner and TEST-label isolation logic, original encoder
revisions, physical OCR/Gemma2 work, 769-parameter Head, 80-step
optimizer, blocking-ci, independent reviewer and all DENY_ALL gates
remain unchanged. This does not qualify original model efficacy,
publisher/host identity, secure cache deletion, true prospective
windows, or FinalUse. Exact-head Actions must pass before acceptance.

## Successor audit: second byte-identical source snapshot

On the source-validated research child `research/e3-race-resnapshot-20261015`,
`stable_again` re-reads every one of the 196 admitted paths immediately after
semantic source/fit validation. It rejects late file additions, removals,
replacements, changed bytes, symlink/hardlink substitutions and unregistered
folders when they occur after the first inventory. This narrows the inspection
race that content-bound *single* scans leave. Synthetic standalone source
mechanism tests (6 ordinary + 6 optimized) passed locally; full inherited
Hepta filetree tests and original pretrained physical CI remain pending.

A two-snapshot equality test cannot eliminate malicious race toggling or prove
an OS-level namespace sandbox, authentic original publisher, signed host,
secure cache deletion, independent label owner or neural model gain. Neither
queued Actions nor mutation-unit results authorize production model selection.
