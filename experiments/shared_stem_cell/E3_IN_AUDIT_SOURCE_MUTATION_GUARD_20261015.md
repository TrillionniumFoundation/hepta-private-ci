# E3 model-entry time-of-check/time-of-use resnapshot

**Draft / SHADOW_ONLY / DENY_ALL.** Parent: #2332 @ `7ad2a8106d70b8270c3cb431d660748bc598cd3a`.

The byte-bound first scan of 196 permitted files is followed by source/case
validation that re-opens admitted metadata. Files added or rewritten between
the two operations could be absent from the first tree fingerprint. An
independent, pure-stdlib second directory snapshot now checks exact path set,
file type/link count, bounded sizes and observed SHA-256 for all 196 inputs.
Any difference becomes a fail-closed `ModelEntryDenied`.

A new source-level unit fixture tests semantic-equivalent receipt rewriting
and a late TEST-label file *after initial inventory*, using a deliberate
document-read interception. Six additional minimal filetree tests ran locally
with 192 generated file stand-ins: **6/6 standard** and **6/6 `python -O`**.
These validate the small exact source helper (Git blob pinned). The full
combined contract and physical pipeline is still awaiting exact-HEAD Actions.

This is a bounded TOCTOU hardening measure, not a filesystem sandbox, a
publisher/ground-truth signature, proof that arbitrary third-party processes
cannot mutate data between reads, or a production Stem/NDU/FinalUse benefit.
Existing original ScienceQA source, model pins, TEST redaction, pre/post
cross-producer evidence and all DENY_ALL rules stay unchanged.
