# Historical training-cache TCP qualification: prospective protocol

This new engineering experiment connects the nine already verified #7200 fixed-feature parents to the real peer transport from #7202. It does not rerun the four synthetic transport controls, train a model, reopen an E1–E6 budget, select data, or read development/final tests.

## Frozen dependencies and inputs

The base is `84f843c6dceb32216e7d83d2ac3063d0d7e9afc4`, whose transport was executed before formatting at `00eab31c926463c2f442e0814ef94f58e9d57338`. The transport protocol is `fc8d36ec020e44e4571fd4ca709c700cbc54b996`. The new runner will be committed before its first execution; exact imported source hashes will be retained.

`INPUTS.json` binds 63 existing files across the fixed grid `n8/n32/n64 × seeds 17011/27011/37011`: the 36 original train shards, nine original manifests, nine archived `SOLUTIONS.npz` files and nine #7200 forward candidates. Input-manifest SHA-256 is `ba2becd642d8a09bd71381e65146b0e25b4ceb2f118b89fafda56faeb09a2d75`; its source evidence archive is `f82a4f8d93ee940dff82c2c06a5c9492348bf6f589ae594d538aa40d42f79b28`. No substitutes or extra parents are allowed.

## Four independent owners

For each parent, spawn four OS processes, each with its own new SQLite store and exactly one original shard. Each child verifies its own shard hash and constructs the same contract-bound `shard-i` contribution and declared sample IDs used in #7200. It receives the contract and its own shard identity, not a reference weight or another peer's data.

Give each peer only the next peer's actual loopback address, forming a directed cycle. Peers perform incremental inventory/offer exchanges using the unmodified transport. Each peer solves its own candidate from its local ledger. The coordinator sends neighbor addresses and stop commands and collects observations; it does not send sufficient statistics, weights or a pooled solution.

A child that has all four batches reports its full candidate but keeps serving and synchronizing until all peers finish or the deadline expires. The expected candidate and old full solution are comparison references only; they never enter a child update.

## Fixed endpoints and accounting

Every parent must produce four distinct child PIDs, zero normal exit codes, four-batch revision and 192 declared rows. Every peer's full candidate object must equal the previously sealed #7200 candidate. Also compare all weights with the original archived `full` solution at unchanged `rtol=atol=1e-7`. A mismatch is failure; never repair or choose a candidate using the reference.

Retain each peer's source/shard/packet hashes, listening address, completed synchronization rounds, offers, refused requests, unknown-delivery events, candidate and final exit code. Record actual application-frame bytes accepted by successful `sendall` calls, bytes returned by `recv`, and failed sends whose partial byte count is unknown. These are TCP application-stream observations, excluding kernel retransmissions and TCP/IP headers. Counting wrappers delegate to the frozen transport and socket operations; they do not alter transport rules or root modules. Metrics and their cost are part of this experiment.

The transport keeps its 8 MiB frame limit and two-second absolute frame-read deadline. This experiment does not claim support for every ledger dimension allowed by the general contract. All work uses one BLAS thread and the existing NumPy environment.

## Budgets and immutable outcomes

Each parent has a cumulative 60-second allowance across attempts, and the entire qualification has a cumulative 600-second allowance. Charge preparation, peer startup, exchange, solve, shutdown, verification and result writes. Reserve cleanup time within each allowance. A persistent budget journal records a case before launching its processes; an interrupted case without a final receipt consumes its reserved allowance.

Stop after the first failed parent. Retain its raw log, source hashes, process evidence and partial observations, with later parents marked not run. A further attempt requires a source correction, a new output directory and a new frozen source identity; it consumes the same remaining budget. Never overwrite an earlier result or restart the allowance. The coordinator may terminate only the child processes created by this runner.

No mandatory iteration or candidate search follows success. Format only after the final execution, retain executed bytes and before/after AST comparison, and do not rerun tests after formatting.

## Interpretation

Passing establishes that these historical synthetic-source training objects survive real multi-process TCP propagation and independent persistent solves. It provides no evidence of user growth, new generalization, learned Circuit quality, representation learning, authenticated work, permission to imitate a provider, or Chain adoption/payment eligibility. Old scientific outcomes and receipts remain unchanged.
