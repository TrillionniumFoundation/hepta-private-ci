# ACT3 controlled operational skill contracts

**NoUpdate: retain the fixed skill library.** The code is published in
[#6113](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6113).
Local exact source is `796bfe11952bb7795947a3ef7c9b6e79b80979fa`, tree
`5b9812068a99e3f7826524ea532f7c195fae5355`; the complete local index tree
matches the published tree. Three separate code stages keep each change
reviewable. The following evidence commit adds records without changing code.

## Implemented and executed

The research adapter binds task, codec and goal parameters to a skill contract.
It checks pause and the original absolute monotonic deadline before each stage
and apply call. Pausing does not extend the deadline. The original FileOwner
still owns every actual effect; a selector proposal supplies no new authority.
ACK loss or an unclassified response keeps the original invocation unresolved.
Only an explicit precommit rejection permits a bounded retry with that identity.
A failed read clears prior completion knowledge. Expired or paused sessions can
still inspect original effects.

Eighteen behavioral tests passed: nine lifecycle, four metrics, two runner and
three original owner tests. The original owning formatter and check passed.
The final formatted source executed **1,536 episodes**: 16 reused generated
filesystem probes × four schedules × eight archived model seeds × three arms.
These are 64 controlled conditions, **zero new independent real tasks**. No new
training, optimizer calls or checkpoints were used. All arms share the same
termination guard; learned independent termination or repair is not qualified.

Every arm (fixed, linear head, GRU) obtained the same results:

| Schedule | Complete | UNKNOWN | Primitive calls | Repairs |
|---|---:|---:|---:|---:|
| Running | 96/128 | 32 | 1,600 | 32 |
| Pause/resume | 96/128 | 32 | 1,600 | 32 |
| Already expired | 0/128 | 0 | 128 | 0 |
| No precommit repair budget | 64/128 | 32 | 1,312 | 0 |

Observed false successes and duplicate effects are zero. The lower call count
without repair accompanies lower completion and does not establish efficiency.
An independent retained-byte audit checked all 1,536 owners and 3,456 actual
payloads, their intent/content hashes, exact invocation/task/version identities,
the full frozen grid, 384 expired rows with zero mutation events/effects, and
384 paused rows with an actual blocked attempt. This is an internal consistency
check within one trusted same-UID fixture, not independent execution attestation.

## Evidence and reproduction

`panel/` retains every trajectory, frozen input/source manifest, operational
result, execution record and original destination bytes. `validation/` retains
the test/formatter logs and independent audit. `SOURCE.json` binds published
source and tree; `SHA256SUMS.json` binds all retained files. The earlier runner
API error and its zero-episode partial artifacts remain in `development-failure/`
and `DEVELOPMENT_ATTEMPTS.json`; they are not qualified results.

```sh
for suite in test_skill_lifecycle.py test_operational_metrics.py test_qualify_operational.py test_file_family.py; do
  python -m unittest discover -s scripts/act2_learning -p "$suite" -v
done
python scripts/act2_learning/qualify_operational.py --archive qualification/act2-learning-20261110/run2 --output /tmp/new-act3-operational-panel
just fmt --base 154a90afbabeeff9eafa48f58d598a87fbef0bef --check
```

The new hosted workflow is independent. Source run
[43161721275](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43161721275)
was queued at this checkpoint; it is not represented as PASS. This does not
replace the successful original ACT3 push run 42829119090, which previously
executed its own filesystem/browser/composition panels on a different source.

## Remaining qualification

The deadline fences entry to new mutations. It cannot interrupt a call already
entered and does not prove the goal completed before a business deadline.
The clock/continuation is process-local; restart or host recovery is not covered.
The measured `end_to_end_ns` window includes owner initialization through final
score audit, but excludes model loading, close, campaign retention, training and
deployment. Missing measurements stay missing; oracle completion does not become
policy knowledge. No full lifetime cost or learning benefit is qualified.

Async waits, cross-process lifecycle recovery, production CellStateOwner/FinalUse
integration, independent real application families and full operational cost
remain open. Production adoption and learning promotion remain false.

## Later continuation

[Actual async waits and durable control recovery](continuation/README.md) add
17 new passing behavioral cases and retain an independently reproduced and
repaired original-invocation receipt defect. Their exact source and remaining
gates are separate in `continuation/BLOCKERS.json`. The original panel above
does not qualify their combined execution or production FinalUse.
