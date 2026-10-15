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
