# Independent review of supplemental confirmation execution

## Scope and reviewed identities

This review concerns `supplement.py` and `SUPPLEMENT_PROTOCOL.json`, before
publication and before generating any namespace-4 confirmation world. It does
not inspect original confirmation performance means or certify unobserved
remote publication. The original failed campaign remains an incomplete
campaign, and the new campaign is an openly amended independent confirmation.

| File | Reviewed SHA-256 |
| --- | --- |
| `supplement.py` | `2a77361b98597b0ede9ce023b454be766ecaa949e20865d37bdc217871eabf0a` |
| `SUPPLEMENT_PROTOCOL.json` | `38c22a588a8afa46c72e0aa25844dcfcf31d0119b9d2f5ce0f666adef77fa05c` |

The original source identity is
`7d634a293500982db5beb37fa1d494a75b540a91`; the original fitted-model freeze is
`8aa146bdb9dc7fae8748393cf718e24a7a9db2d3`. No original Python source, protocol,
manifest, fitted model, selected controller or training archive was edited by
this reviewer. The supplemental statistics implementation has a separate owner
and review; this document does not claim to have audited its final contents.

## Narrow exception handling

The wrapper calls the unchanged `run_episode` function. A failure is isolated
only when all of the following match: the arm name is `mean_value`; the error is
a `ValueError` with the exact message `Impossible observation`; the traceback
contains exactly one `observe` frame in the frozen `planner.py` and one
`run_episode` frame in the frozen `execution.py`; the actual belief projection
is `mean`; and its observation likelihood is exactly zero. Negative mass,
other exception messages, other call sites and other arms remain fatal.

The invalid result has null reward, utility, fee and all-queries-correct fields.
It retains its seed, world fingerprint, failure query/key/time/token, prior
checkpoint, already completed queries, previous actions, exception traceback
and spent CPU. It neither floors probabilities nor substitutes STOP, a reset,
an answer or a zero reward. The incurred-fee fields distinguish the active-time
and earlier-action fees already added by execution from the observation fee
whose addition follows the failing update in the original code. Their sum is
the cost actually incurred in the current query, not a valid completed-episode
utility. Earlier completed-query fees remain available in the saved records.

The support diagnosis is specific to this approximation. The mean projection
retains only two neighboring phase indices; it can remove all recovery mass
while the real observation kernel can emit a recovery-only erasure. This is a
support defect of the registered projection, not evidence that all mean models
fail or that the HX parameterization has exclusive predictive value.

## Pairing, attempts and frozen behavior

Every new episode creates one scorer-owned world and attempts all 13 arms, with
the original deterministic rotation of arm order. A caught mean failure ends
only that mean episode. The next independent episode starts with the original
initialization, and the other arms continue on the same world without altered
random draws or observations. Any undeclared exception still aborts the worker.
The D and same-matrix HMM arms retain complete-query equality checks.

The new seed is the original confirmation seed plus exactly `10^12`, giving
the declared namespace 4. The eight fit seeds, two domains and 128 episodes per
fit/domain are unchanged. The code reads original training archives, not old
confirmation trajectories or their mean performance. Its law, action, price,
observation, write and deadline behavior comes from the frozen original modules.

The protocol requires all 128 mean attempts for coverage, nullifies every
D-minus-mean claim if any mean attempt fails, and rejects survivor-only
performance aggregates. The twelve other arms must retain the original full
fit-level design. Their designated primary comparison remains D minus selected
B; having twelve evaluated arms does not create twelve primary endpoints.

## Publication and model-reference checks

Before a claim or a new confirmation world, the runner checks the original
source manifest, supplemental file manifest, publication receipt and exact
supplemental freeze bytes. A focused review finding was resolved by adding a
link back to the original model-freeze chain: the original receipt must identify
the registered freeze commit and match its exact bytes; its source identities
must match the protocol; the new freeze's complete training hash map must equal
the original map; and the selected training archive must match its hash and its
own seed, non-development and source provenance fields.

The runner rechecks supplemental and original source identities at successful
completion. As before, actual GitHub readback is the independent evidence for a
publication receipt; a local Boolean flag alone is not such evidence. This
review precedes that publication step and does not assert it has occurred.

## Durable evidence and costs

Another focused finding was resolved by replacing the initial open gzip stream
with plain JSONL. Each complete paired episode, including scorer-owned world
paths and all 13 arm records, is written as one line, flushed and file-fsynced.
Completed lines do not depend on a future gzip trailer. An interrupted final
line must be rejected; this is evidence preservation, not a complete owner
crash-resume implementation or a claim about power-loss directory durability.

The existing supervisor is selected through its public `MODULE` variable; its
source is unchanged. Child commands execute the supplemental module with the
same single-thread environment and POSIX wait4 whole-worker CPU accounting.
Arm inference, preparation/checkpoint I/O, world generation and progress-journal
work retain separate measurements. Inner measurements must not be added again
to their enclosing process total.

The protocol explicitly preserves the original deployment-account formula:
whole training-search worker CPU plus one preparation/checkpoint and N online
episodes, with the registered online and N=1000 D/B cost gates. All original
confirmation workers, including the five failures and eleven completions,
remain in the separate cumulative research-expense ledger. Old results are
excluded from new effect estimates, not erased from provenance or expenditure.

## Handwritten exception-isolation probe

A small development-only probe used a handwritten single-query object, fixed
READ policy and forced erasure token. It generated no stochastic confirmation
world and used no namespace-4 seed or old confirmation result. The real frozen
execution/filter call chain produced zero likelihood and was isolated only
under the mean arm. The same failure under the D name propagated as fatal; an
identically worded exception raised from a different observation provider also
propagated. Invalid outcome fields were null and no target was requested.

For this fixture, the active-time fee was 0.00075 and the publicly determined
READ fee was 0.05, yielding 0.05075 incurred fee. This checks fee preservation,
not scientific performance. Probe inner CPU was 0.009401394 seconds; this timer
excludes interpreter startup and imports and is not a whole-worker cost claim.
Subsequent cleanup removed only an unused gzip import and a redundant `if True`
block; the final exception and fee logic was source-reviewed as identified above.

The execution-level findings requested during this review are resolved. Formal
outcomes, complete statistical admission, remote publication and result audits
remain later evidence and are not inferred from this source review.
