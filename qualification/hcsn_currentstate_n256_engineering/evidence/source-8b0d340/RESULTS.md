# N256 sparse-operator resource pre-admission result

Status: **RED_RESOURCE_CAP_HOLD / HOLD_NO_NUMERICAL_EXECUTION / all_closed=false**.

The exact frozen source `8b0d34034902a699b7a437a4076fbe76ad032368`
materialized one static N256 sparse-operator topology against the exact new-export
input bundle and #6294 roster. It matched 14 capsules, 185 packet tuples,
18,225,028 conceptual FP64 coordinates and 45 transition segments.

The four unique sparse operators contain 3,058 nonzeros and occupy 44,912 bytes
in the declared CSR accounting. This does not make the full state small: the
largest capsule is 27,553,312 bytes and candidate plus dense independent oracle
is 291,600,448 bytes. Both exceed the retained N128 comparison caps
(8,388,608 and 201,326,592 bytes). No cap was changed; the result remains RED.

The unique execution was host job `1a1d39c7d23-392-188`, exit 0, 0.29 s wall,
0.28 s CPU and 23,724 KiB maximum RSS. An independent zero-execution review job
`1a1d39d3100-392-18b` verified frozen hashes, the negative arithmetic and all
zero-work fields.

No dynamic state propagation, matrix exponential, numeric oracle, full-state
numeric serializer, Torch, backward, optimizer or training ran. No N256
numerical allocation, full-state oracle, large-grid qualification or production
adoption is conferred. Historical N256 bytes remain absent; this is still the
new-export-only lineage.
