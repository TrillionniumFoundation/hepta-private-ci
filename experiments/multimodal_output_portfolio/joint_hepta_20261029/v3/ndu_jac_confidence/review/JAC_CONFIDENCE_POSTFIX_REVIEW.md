# JAC confidence correction: independent follow-up

**Disposition: all three previously reported acceptance defects are repaired in the reviewed source. No new high-impact finding was identified in this scoped follow-up.**

Reviewed `confidence.py` SHA-256:
`bacd459260fb0cab1685458c1f1fbdba0db3729ea9b0fab894a5fc3d94da4b0c`.
The confidence/study/test hashes match `protocol.corrected.json` and were unchanged after this review. I read `CORRECTION.md`, the corrected protocol and corrected implementation, and actually replayed the original counterexamples. I did not modify target source, rerun the 20-bank study, add banks, sample observations or invoke a model.

| Original issue | Independent corrected observation |
| --- | --- |
| Empty-string successor silently treated as terminal in propagation | The exact original input raises `ValueError: Invalid bounded outcome or successor` |
| Candidate probabilities `(2,-1)` accepted as a policy | The exact original input raises `ValueError: Finite nonnegative policy probabilities required` |
| Baseline mass `1-5e-13` plus common payoff `1e12` invented gain `.5` | Both the inherited evaluator's true gain and the reported gain are now exactly `0.0`; update is rejected, returned policy mass is `1.0`, and the spent `.01` fee remains charged |

The same high-continuation mechanism was also exercised with a valid nonempty child name, so rejecting malformed names was not the only check. Its true proposal gain computed with 80-digit Decimal arithmetic is

`8.911034055331969418327627025112770087899880118182610304179198378276822750759988e-10`.

The corrected reported gain is `8.911034055331968e-10`, approximately `1.202e-25` below that value. The reported tilted mass is `2.0611536181902033e-9`, consistent with the high-precision reference `exp(-20)/(1+exp(-20))`. The `.01` paid update is correctly rejected and the returned net lower value is `-.01`. This resolves the original false positive of about `.283109585`.

All **13 targeted assertions pass** in `JAC_CONFIDENCE_POSTFIX_REVIEW.json`. These are deterministic implementation checks, not independent statistical replications. They do not change the earlier mathematical review: the simultaneous finite-support CP event and real-arithmetic risk-tilt propagation argument are sound under their declared fixed-sample contract. SciPy quantiles and floating exponential/logarithm calculations are still not a formally outward-rounded interval implementation. No independent-task, full lifecycle or new-RL superiority gate is closed by this repair.

## Scope check of the finite-deadline report

I read the existing accepted frontier receipt, README and BINARY_DEADLINE.md without rerunning their experiments. The reported 31 LP cells, 31 analytic binary rows, 30 exact zero-gap LP intervals, remaining gap below `1.8e-7`, and joint unlimited-resource error sequence `.5,.32,.2255,.068,.05` agree with those receipts. The 22/23 macro boundary is correctly stated as the minimum hard cap for a shared randomized uniformly 5%-correct rule, under the complete-macro known-law contract. It does not claim 23 samples are always consumed or minimize expected acquisition cost. The reported 69 is model time, not measured seconds. The report explicitly preserves expected-versus-pathwise resource distinctions, the nonoptimal early wrapper, prior negative lifecycle results, and no-new-RL/no-real-LLM limits.

One small wording clarification would improve the frozen-protocol interpretation: `protocol.deadline` says “STOP mandatory at exhausted budget.” This should be read as exhausted time or launch cap, not pathwise exhaustion of the *expected* resource limit B. README already states the correct distinction. This is a wording ambiguity, not a detected computational or theorem failure.
