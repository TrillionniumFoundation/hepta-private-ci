# N256 authentic-input lineage admission results

Status: **PASS_AUTHENTIC_NEW_EXPORT_LINEAGE_HOLD_DYNAMIC**.

The one precommitted stdlib verifier decoded the exact NPZ, compared all 1,542
FP64 coordinates to the JSON representation, checked all 8 phase supports, and
bound the five authentic input hashes to bundle
`17086fb6ba83211e8626c7ac9c22183f6c9c9a7dc615772b5a32d2c14ecb8e95`.
The roster, engineering audit, and streaming plan all bind that bundle to
coordinate identity
`e289c20d6595cb6d92dd3e2585bc7cb40fb0d5a408725c5edc14a9fb7f328fe2`,
14 capsules, 185 packets, 45 segments, and 18,225,028 conceptual FP64
coordinates.

This closes only the authentic **new-export input lineage**. It does not recover
the absent historical N256 export. The historical negative statement and the
existing `RED_RESOURCE_CAP_HOLD` are preserved.

The first independent reviewer attempt failed before publishing a review because
it treated a recorded SHA as a relative path. Its complete stderr and failure
receipt are retained. The minimal path-roster amendment was separately frozen and
pushed; `review002` then passed without rerunning the main verifier.

Known counts: one verifier, two review attempts, 0 dynamic runs, 0 matrix
exponentials, 0 oracle/serializer numerical calls, 0 Torch/backward/optimizer/
training calls. Verifier cost was 13,208,008 ns wall, 10,580,759 ns CPU, and
19,676 KiB max RSS.

Still OPEN: N256 numerical candidate, independent numerical oracle, actual
expm/RSS/cgroup profile, canonical serializer/cold loader execution, resource and
calendar allocation, and warm/cold byte equality on the actual N256 state.

`largegrid_qualification=false`, `global_HOLD=true`, `all_closed=false`.
