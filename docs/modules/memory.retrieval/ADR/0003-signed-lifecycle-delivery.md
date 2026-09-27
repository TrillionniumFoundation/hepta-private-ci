# ADR 0003: atomic signed lifecycle and host-fixed delivery

Status: source candidate; native qualification and independent rollout acceptance pending.

## Decision

Keep the signed, challenged-frontier provider from PR #1067. Selectively reuse
Agentd's existing atomic-acquisition, post-append/final-use revalidation and
four-mode routing from PR #1014 at d49099e9f547d9b3fc46130b070c4ab015e94e88.
Do not import that branch's legacy contradiction adapter, precomputed-vector
owner or unsigned in-memory lifecycle controller.

`CurrentMemoryRetrievalContext::acquire_context` returns the context, its
lifecycle binding and its lease deadline in one observation. The signed provider
copies all three while holding the same state mutex after verifying a fresh
challenged frontier. Its binding is the signed publication digest, covering
owner, body, authority epoch, sequence, interval and full context binding.
Re-signing identical context under a new sequence or interval invalidates the
old read. Reinstalling identical publication does not extend the monotonic lease.
The Agentd operation bounds its local deadline by that published lease.

Agentd binds the mode and versioned cohort policy into HNMF read identities.
`compatibility` does not attach a provider. `hnmf-shadow` executes observations
but delivers only compatibility results. `hnmf-canary` uses a stable, versioned
five-percent owner cohort; selected owners fail closed like `hnmf-required`.
Unselected owners use the shadow path. A request cannot select its own cohort.
The cohort is an implementation baseline, not independent permission to roll out.

Only the HNMF-delivered subset is recorded as HNMF context exposure. A failed
shadow computation or shadow ledger append cannot poison compatibility delivery.
A ledger append is preparation, not proof of native consumption. Owner/context
currentness is checked again after the append and after an awaited final-use
ranker check. No raw memory content or authority key is added to diagnostics.

## Compatibility and exclusions

The old `current` method remains for trusted legacy hosts. Its default atomic
adapter returns a payload-only binding and no product lease; this is not promoted
to signed evidence. Production composition must use an independently pinned,
leased provider. Existing response fields remain unchanged; HNMF read digests
change deliberately because their meaning now includes lifecycle and mode.

This increment does not provide a durable frontier signer, provision authority
keys, load real encoder weights, calibrate OOD, implement process publication
bootstrap, measure the nine-stage product SLO, or activate/release the module.
The source map records inspected objects; the external qualification receipt
must still bind the exact tested HEAD/tree/parents and report actual test results.
