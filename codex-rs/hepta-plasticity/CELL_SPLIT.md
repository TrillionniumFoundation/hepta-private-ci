# Offline Cell split candidate

`cell_split.rs` turns a measured specialization hypothesis into a bounded,
content-addressed record. It requires:

* an exact successor generation and nonzero parent/window/review digests;
* separate residual, conflict and split-trigger evidence;
* independent evaluation and a retained-task utility floor;
* a resource review and security review; and
* an explicit source-to-child state and optimizer-state mapping.

`propose_cell_split_candidate_v1` sorts and validates the mapping, computes a
deterministic candidate/proposal digest and returns
`RequiresIndependentAcceptance` with `AuthorityPosture::DENY_ALL`. It does not
copy state, mutate a live graph, select a child or activate a successor. The
runtime owner may later bind this record to the existing governed topology and
state-migration gates.

The no-change candidate should remain in the surrounding topology proposal, so
an offline split is compared against retention, resource and latency baselines.
