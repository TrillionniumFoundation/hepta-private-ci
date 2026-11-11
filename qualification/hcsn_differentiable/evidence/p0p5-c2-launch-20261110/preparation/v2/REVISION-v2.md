# Candidate v2: terminal success evidence

The v1 source, 40-test receipt and handoff ZIP remain immutable. A pure-metadata reproduction extracted the actual v1 terminal branch by AST and confirmed that exit0 plus an absent result file was labelled completed. It did not start a model process, read a native checkpoint or perform any optimization.

V2 adds a terminal result gate. Exit0 requires a parseable object with the expected C2 schema, exact parent outer/report, seed, learning rate, construction configuration and successful state. A success must also bind unchanged source/common/physical state, the cumulative retained/replayed-work counters, inherited parent wall, complete epoch coverage, the resume-start checkpoint/receipt, last/best checkpoints, journal and selected development logits. Missing, malformed or mismatched artifacts become `failed_terminal_evidence`. A nonzero process cannot claim training adequacy.

Every rejection retains the measured per-PID wait4 CPU, full process wall, wrapper wall, logs, return code and timeout flags. The totals now distinguish terminal evidence completeness from cost accounting completeness: a missing model artifact is not permission to erase known CPU or wall costs or to invent unknown costs. `completed_attempt_roster` continues to mean every dispatched attempt has a terminal row, not that all fits succeeded or converged.

The eight new failure tests use explicitly opaque byte and metadata fixtures for the artifact gate. They are not model outputs or research evidence. The unchanged 21 boundary guards and 19 prior execution tests remain part of the final software validation. No real C2 optimization is started by this revision.
