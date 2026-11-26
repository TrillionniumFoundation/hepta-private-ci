# Fixed-coordinate first-order engineering check

This stage depends on the sibling `native_profile_v4` adapter. The registered
protocol fixes six coordinates, four ticks, two trajectories and two FD steps.
The actual run completed 26 forwards, two scalar VJPs and four known quadratic
checks. AD agreed with both central differences. The raw_cost[4] one-sided gap
stayed near 14.773 at both steps, so the classical differentiability gate FAILED.
Its blocked real-J solve/export path did not run. No coordinate or threshold was
changed to obtain a pass. The nonsmooth follow-up is a separate admitted scope.

The raw parent profile tests passed four methods, including complete physical
continuation. The containing H job failed because the later derivative gate failed.
The complete original root receipt and FAILED result remain byte-for-byte intact.
Use the frozen protocol and exact materials when inspecting the CLI; this package
does not authorize a rerun of the exhausted historical training matrix.

Files ending in `.bytes.json` contain original bytes encoded as base64, with size
and SHA-256. Decode `data_base64` and verify both fields before reading the original.
