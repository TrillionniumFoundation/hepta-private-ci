# Read the separately frozen repaired pool

This read-only update preserves the original graph/call/token/transition accounting. For protocols with an adapter_precision_repair declaration, it additionally checks POOL_BINDING.json, WORKER_INTENT.json and the pool inventory against the frozen actual loader module and source SHA. Missing or mismatched evidence keeps the result INCOMPLETE and complete call/token totals unknown. It verifies the pool identity digest as well.

The prior failed attempt and diagnostic costs are retained in a separate protocol-bound history field. They are not added to this run's graph totals or confused with nested wall scopes. The original f0151a2b reader and its actual failed-attempt output remain preserved at their prior commit and remote paths; this update is a new standalone reader, outside the inference source freeze.

Three explicitly synthetic partial-evidence fixtures (matching binding, wrong source, missing binding) passed the expected binding checks while all remained INCOMPLETE with unknown complete totals. They contain no model execution. Original just fmt returned zero and preserved the reader AST; the three already frozen inference/control source files remained byte-identical. The new reader SHA256 is c11c3301b6926e3e0e89650897b8c1c1d2b4b44a1396063320d00ba6887cb5fa.
