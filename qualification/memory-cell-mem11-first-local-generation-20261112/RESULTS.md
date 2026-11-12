# MEM11 first local generation v3 reconciliation

The original operation identity `mem11-first-local-generation-20261112-21bb-v3`
was reconciled read-only on ai395. No retry, cancellation or new generation was
issued. The previously unavailable `PREEXECUTION.json` and
`GENERATION_RESULT.json`, plus the admitted request, generation admission,
combined log and receipt, are now retained byte-for-byte in this directory.

The exact old source is commit
`fa3b62440f3dbe21e904dfbd390d346d03322b7e`, tree
`c9fbc24c924936a2aab0389fec68b7d9b9e7bc16`. Its five source pins match the
pre-execution and receipt. This is the unformatted tested provider source; the
result is not relabelled as the later formatted provider or the #6136 composed
source.

The receipt is terminal **RETURNED**: exit zero, no timeout, no output limit,
one physical model call, unchanged source, unchanged runtime inventory and all
six guest namespaces distinct from the host. The frozen request used
`store=false`, temperature zero and eight output tokens. It returned
`Hello!` with tokens `[19556, 17, 2]`. Observed resource fields are
2.344506 user CPU seconds, 0.228296 system CPU seconds, 1,202,028 KiB maximum
RSS and 4.257017993 seconds outer elapsed time.

This closes only the terminal outcome of this one first local-generation
operation. It is not a memory-on/off pair, not an A-to-C task, and has no causal
score. The receipt explicitly keeps `original_owner_authority=false`,
`observer_authenticated=false` and scientific acceptance **HOLD**. The
original MCP acknowledgement and durable process registry remain unresolved;
the terminal is established from the pinned result files, not from a recovered
job ID. V1/V2 retain their separate identities and UNKNOWN terminals.

The original production provider request, owner/current-cut authority,
independent FinalUse/outbox/destination evidence, source exposure/trust,
learned association, unseen-source benefit, full recovery, complete costs and
hosted required CI are not qualified. All ten adoption gates remain OPEN and
adoption remains **NoUpdate**.

[EVIDENCE.json](./EVIDENCE.json) records the read versions, hashes, exact source,
current asset re-hashes and explicit qualification boundary. Raw files are
under [raw](./raw).
