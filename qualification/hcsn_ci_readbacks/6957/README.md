# PR #6957 immutable hosted originals

Status: **HOLD / negative observation / all_closed=false**.

This directory preserves the exact ten direct lane artifacts and the exact
combined collector artifact from the only admitted run of source
`23980910e03fc62da839b11271a80241eaa21d9b` under key
`hcsn-n256-authentic-tailcheck537-hexfix-20261122-c6bc-001`.

Run `45005537845` completed preflight, ten lanes, and collector successfully.
The eleven original ZIPs are stored byte-for-byte inside one deterministic,
uncompressed tar stream, split only for Git storage. Concatenating the 106
numbered parts restores the 73,758,720-byte tar with SHA-256
`48faf3b7b73584488147a0bf42adc51091651112b833e53694a3e4d58a0a5970`.
Its collector member is the original 36,875,152-byte ZIP with SHA-256
`452e22f354928f88742d840d3287c160153b8e86d4ed5346b0d0628d0ddacbf4`;
the other ten members are the exact direct lane artifact ZIPs.

The recorded scientific result is negative: all ten lanes completed their
first possible index537 ratio-bound tail check, but 0/10 lanes and 0/2,585
coordinates were unique. Thus `first_tail_check_complete=true` while
`tail_termination_closed=false`. No rerun is authorized to pursue a positive
result.

`verify.py` is an independent standard-library, zero-model readback. It checks
outer artifact sizes, SHA-256 and CRC; restores the combined ZIP; proves every
direct lane member is byte-identical to its combined copy; validates every
checkpoint container's bounded XZ/SHA-256 envelope; reaggregates work, cost,
progress, and all 2,585 recorded non-unique rounding rows. It executes no
recurrence, tail calculation, provider, dynamic, exponential, Torch,
optimizer, model, or training work.

#6939 and #6950 remain RED. #6942 remains RED_TIMEOUT with completed actions
UNKNOWN, and #6901 remains UNKNOWN. Provider comparison, arbitrary-history
resume, N256 qualification, C2 full replay, HPCA external custody,
equal-budget benefit, asynchronous cost, and production adoption remain OPEN.

