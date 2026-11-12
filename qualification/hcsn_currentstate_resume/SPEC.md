# Saved-state continuation with complete raw — pre-execution SPEC

This is a new bounded continuation identity, not a reconstruction or relabeling of #6249 attempt001. That original's missing coarse vectors and separate cold final raw remain missing. The original source/receipts and #6247 negative spatial result are unchanged.

Load each persisted exact T=.201 packet state. Fork a warm schedule [.28,.36], a coarse schedule [.36], and a fresh-process warm schedule [.28,.36]. Retain input, every current-state snapshot and full M/H/R/A/Z/active/upper readout. Compare the two independent warm/cold final raw files directly, not only their hashes. Compare fine/coarse spatial vectors and all readouts at .36. Packet partitions may differ between schedules; no total-to-state inversion, merging or normalization is permitted.

The fixed packet core and all seven #6249 frozen source/spec/plan bytes are unchanged. The five immutable numerical inputs are the two resume states, two original warm final states and original ROWS reference artifact. References are read from the retained file, never reevaluated. There are zero initial-trajectory advances, old72 replays, Torch, optimizer and training calls.

Before execution freeze this driver, plan and SPEC plus all seven old frozen files and five input hashes in Git. Run exactly once under GNU `timeout -s KILL 45s`, OPENBLAS_NUM_THREADS=1 and OMP_NUM_THREADS=1. Each of six ledgers has100 exponentials; core segment cap20 gives fixed bounds600/120. Parent CPU20/21 seconds and two children5/6 bound CPU hard limit33 seconds. Each process RLIMIT_AS512MiB. Record parent and children ru_maxrss fields distinctly; neither is combined peak RSS. Parent import/setup is outside instrumented timer.

Use the unchanged1e-12 floor, null relative diagnostics below it, and the existing finite-control absolute tolerance2e-11. This supplies a newly observed .201→.36 finite continuation certificate only. It does not create the missing #6249 historical raw, certify arbitrary timelines or fix the continuum/lattice error. Overall HOLD_NO_GO / all_closed=false.
