# N256 independent uniformization provider source intent

Status: **HOLD / all_closed=false**.

This separately frozen stage supplies an independent, Python-standard-library source for `certified_sparse_uniformization_v1`. It implements canonical row-sparse subgenerator validation, a substochastic uniformized row action, modal Poisson-weight construction that does not begin with `exp(-lambda)`, a ratio-geometric tail upper bound, signed-L1 tail accounting, exact identity hooks for an external certificate, and fail-closed external admission.

It deliberately has no N256 runner and imports no candidate, oracle, inherited propagator, NumPy, SciPy, or Torch. Its five tests use only a two-state synthetic fixture and a source-level stiffness-scale Poisson window. That window is a source-behavior test, not an N256 operator execution or tail/rounding certificate.

The first assertions-enabled local fixture is retained as RED. The provider returned the mass-conserving two-state solution, but the test's hand-written expected second coordinate omitted the initial `-0.25` contribution and used the wrong analytic expression. The repair changes only that synthetic expected expression to `-0.25 + 1 - exp(-1)`. The RED made one small synthetic provider call and zero N256, candidate, oracle, model, optimizer, or training calls.

Before source freeze, a second static review found that the large-intensity tail path selected the modal temporary as the retained last weight when truncation ended one index below the mode. The retained weight array was correct, but the tail-bound recurrence started from the wrong variable. The repair starts from `weights[-1]` in every case and adds an analytic modal-tail equality check. This review executed zero N256 inputs or roster operators.

The stage binds #6337 exact head `7f0290bc29ab969029b95d8f78c27c481b03acee`, its exact stiffness contract, #6335 generator review, the authentic #6256 inputs, and #6294 roster/event identities. The current request forbids numerical execution, contains no idempotency key, and has no admission. Tail certificates admitted, N256 provider calls, candidate calls, oracle calls, model calls, optimizer calls, and training calls all remain zero.

This source freeze does not certify the six scientific claims required by #6337, admit any provider, execute any of the 45 roster segments, emit the 18,225,028-coordinate stream, compare candidate/oracle/provider, establish saved-state byte equality, or close runtime/host/cgroup/allocation/calendar, migration, fullnetwork/equal-budget benefit, asynchronous cost, C2 full replay, HPCA external custody, or production adoption. Historical RED/UNKNOWN and #6247 finite-domain failure remain unchanged.

