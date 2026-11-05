# V14 stage 2: durable actions and acquired content

`Session` serializes writes using SQLite transactions. A READ is charged once
when issued. The pure core transition, its content and completion receipt are
committed together. Repeated operation IDs must keep identical requests and
results. A crash before acceptance commits leaves the READ pending; its retry
does not duplicate the charge. External transports must reuse the read ID.

RESET clears the recurrent state, increments its epoch, cancels pending reads
and rejects their late responses. It preserves accepted content, the global
source frontier and per-source watermarks. The next neural delta starts at that
retained source frontier; RESET is not a continuous physical-time reset law.
It is separate from V13's internal threshold/refractory reset.
Restart requires identical input, model, execution, clock, session and budgets.
Changing host clocks or migrating models requires a separately verified adapter.

`query(address)` returns exact acquired text and source/time/content citations,
or an explicit unknown. This is exact addressed retrieval, not learned binding,
semantic retrieval, transcription, or free-form grounded generation. Content
and operation limits are enforced before commit. Full snapshots retain features
and operation history, so storage and transaction cost must be measured; this
prototype makes no production throughput or memory-compression claim.

Run: `python -m unittest experiments.hcsn_v14_causal_io_20261104.test_runtime`.
Tests include all four modalities, rejected future/wrong-source packets,
missing/failed states, bounded storage, an abrupt process exit immediately
before acceptance COMMIT, pending retry, RESET and 1,024 intervening reads.
They use synthetic fixtures and do not qualify real-world model performance.
