# Independent component review

Reviewer: the separate `execution_scheduler` agent. Review was read-only and preceded the final amortization-key fix; no reviewer-authored test replaced the actual process receipts.

The reviewer checked the outer wait4 boundary, disjoint adopted subtrees, process identity handshakes, unavailable memory/energy treatment, and output clocks. It found the enclosing CPU accounting consistent: nested process costs must not be added to the enclosing wait4 result. The family-memory result remains unavailable in this runtime and the energy result remains null.

One substantive issue was found: a caller could supply `setup["execution"]` to `amortized_cpu`; the merged mapping replaced this entry when detecting unknown costs, while its numeric value could still enter setup totals. This could hide an unavailable input or count the same category twice. The final function rejects that reserved key. Both null and numeric reserved inputs are covered by the targeted regression in `validation/reserved_key_fix`; its complete process receipt is retained. This change does not alter worker supervision or the earlier process-tree measurements.

The review also requested clearer wording: `task_success` means process completion and collection, not admission of every latency marker. Each marker retains its own `bounds_valid` result; invalid clocks remain null. This distinction is explicit in the README.

The reviewer independently read the actual scheduler probe output: all seven declared behavioral checks hold, the normal episode charged and accepted three reads with unchanged cache across WAIT, and the late episode charged one read but accepted none. The late output was slightly after the fixture's 0.2-second deadline, so `timely=false` and the deadline penalty applies. This result does not establish a real-model quality or cost gain.
