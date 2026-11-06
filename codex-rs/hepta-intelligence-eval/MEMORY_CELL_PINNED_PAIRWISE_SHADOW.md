# Pinned native pairwise Shadow Head: exact-result audit

This research-only audit consumes the completed **original real pretrained**
native matrix at
[run 38266549880](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38266549880),
commit `6235ccfb3ffc495c45284ff13f1e98b1644e31c2`, source Git
tree `fcb329b7416b75d49624e500d4079f076fc86286`, and
artifact `11756269634` (transport SHA-256:
`694401ca61859bd11a24ae212c0edb4c3b493182581e07d373cc73f4fd0aeae1`).
It never executes another model.

The original experiment completed all 576 unchanged production-*ineligible*
six-arm policy attempts. Five original learning arms had no improvement in
source-accuracy or Reader token F1 versus the frozen model; none emitted a
structural citation marker. This is not a proof of equivalence on unobserved
tasks. Original independent-citation and production checks remain **false/null**.

The separate **pairwise weak-source training objective** is a useful hypothesis:
it asks whether source rankings move when training linear/gated frozen-Encoder
Heads on positive versus weak-unlabelled negative windows *without* modifying
null/abstention weights. The archived stem experiment recorded **12
persisted/reloaded Shadow Head fits** (3 stages × 2 Cell routes × 2 designs),
and **192 label-blind Shadow decisions** (3 stages × 4 phases × 8 questions ×
2 designs) outside the original six-arm matrix.

`stem_pairwise_pinned_disposition.py` checks: exact ZIP transport and complete
internal SHA256SUMS, generating commit/tree, the original 576 policies and
registered families/routes, all 12 fitted model byte hashes and consecutive
checkpoint lineage, exact 192 choice identities, no new Reader calls or
held-out gold in choice generation, direct per-question match to unchanged
frozen candidates/Head snapshots, and the post-answer weak source-support
aggregate census. Failed attempts stay in the denominator.

**Important distinction:** a source-only Shadow Head can change a chosen
window, and post hoc *native document* labels can suggest improvement, without
the same unchanged Reader producing a better answer or an independently
reviewed excerpt entailing the answer. Any gains reported by this audit
remain research opportunity rather than learned-model qualification.
No test/transfer labels may tune its margin, Head, route or selection.
`production_accepted=false`, `scale_out_permitted=false`.

CI: `.github/workflows/hepta-memory-stem-pairwise-pinned-audit.yml`
runs read-only synthetic anti-forgery tests, fetches the exact historical
artifact and publishes its complete machine-readable disposition with source
hashes and failure logs. It is not a CI waiver or promotion gate bypass.
