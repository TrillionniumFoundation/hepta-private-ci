# V13 new-content-head control adapter

This layer executes the V13 jointly trained **content classifier**, not the old
frozen V3 head or the V10 future reader. Every accepted READ calls the new
model's persistent `step` and actual `classify`; its hidden, membrane and
refractory state and actual output probabilities are retained. All families use
the same accepted-history schema, information and control rules.

The future reader is a separately trained 354→32→1 MLP. Offline, actual TRAIN
recordings generate every legal A1-first prefix-tree node and each one/two-READ
descendant. Each unique node invokes the new model once; descendant references
are targets, not independent objects or repeated model-forward claims. Inputs
contain accepted history, current class probabilities and exact ordered READ
identities. Object IDs, labels, unread arrays and future states are excluded.

Historical VAL fits two fixed five-bin correctness calibrators: current STOP
correctness and future-reader correctness. This is correlated development data,
not an independent calibration or quality certificate. No threshold, bin rule,
checkpoint or optimizer parameter is selected using historical TEST results.

`planned_outcome` uses only public logical time, source release and the declared
0.001-second prepared service duration. It is shared by the forecast and service
estimator. A late issued READ is charged but excluded from the accepted future
path; READs after a WAIT reaches the deadline are not issued. With no accepted
READ, the forecast exactly returns current STOP correctness. Actual timeout
work drains only after the output is frozen, using the unchanged V8 executor.
WAIT alone does not advance the model's source-clock state.

The initial adapter review found that the first draft omitted WAIT when
predicting content but did not first truncate late READs. `source001/` preserves
that draft and its limited 38-control check. No formal reader fit or TEST
evaluation used it. The revision adds actual executor counterexamples: WAIT
reaches deadline before READ, an issued READ times out, and only the first of
two issued READs is accepted. `check002/` passes 49 controls, including the
original prefix/state/future-payload controls. The original run's cost remains.

Publication has two explicit gates. Before `value_fit prepare` can load any
VAL bytes, complete content candidates and control source must belong to the
verified current local tree corresponding to a published remote commit. After
the original training-source and TRAIN archive hashes pass, every task's TRAIN
warehouse identity must also match before the first VAL loader is called. After
TRAIN fits and VAL calibration, `campaign freeze` seals all 36 readers. TEST
execution again requires the verified published tree and all exact model,
normalization, reader, metadata and input bytes. The remote SHA is recorded;
it is not assumed to be a locally available Git object.

Use fresh output directories and one enclosing waited worker per fit and
evaluation. Commands are `value_fit prepare --models ... --run ...
--publication ...`, `value_fit fit --run ... --task ... --family ... --seed ...`,
`campaign freeze --run ...`, and finally `campaign evaluate --run ...
--publication ...`. `PROTOCOL.json` fixes 36 reader fits, 128 updates, batch64,
the exact model roster and fixed/light/value policies. This directory presently
provides implementation and TRAIN-only contract evidence. Formal fits and
historical evaluation require the parent workflow's publication gates.

These controls do not establish strong-frontend admission, complete financial
parameter learning, continuous within-interval reset, net utility improvement,
physical energy or production adoption. The prepared service actually selects
and copies historical arrays; its logical release clock is not live-media or
measured end-to-end service latency.
