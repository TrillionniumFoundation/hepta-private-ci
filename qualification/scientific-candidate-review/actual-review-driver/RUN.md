# Actual V4 native rejection receipt

The completed, frozen V4 report and both actual 12-fit research parameter bundles
were supplied to the compiled native qualification driver on 2026-10-25.
Execution exited successfully with **`GateFailed(task)`**. The rejection happened
inside the actual `ScientificCandidatePublisherV1`, using an explicitly
non-production, ephemeral research reviewer identity.

| Required gate | Independently aggregated measured result | Frozen requirement | Result |
| --- | --- | --- | --- |
| Future task improvement | Worst one-sided upper bound `0.002178625835057478` | Strictly below `-0.001` | Reject |
| Old-task retention | Worst one-sided upper bound `0.0368832032888788` | At most `0` | Reject |
| Controller CPU | Maximum measured ratio `13.065057839712304` | At most `3` | Reject |

The task/retention counts are the minimum source-component counts across all
required contrasts: 112 and 32 respectively. CPU cost uses three paired timed
runs per task/head ratio. The CPU number is a measurement, not a confidence
bound. The retention aggregate point estimate is `-0.04620405251217948`; its
positive upper bound means the preregistered non-regression evidence gate did
not pass. It does not establish worse mean retention.

All ten existing owner files stayed byte-for-byte unchanged. The before and
after registry head was
`31fbe6b29c49810b1ccb0613a87887dfbfe06bfa95350651a355a5dc04a4da41`.
The immutable all-12 warmup predecessor remained present; the all-12 candidate
was absent and unpublished. No selector, serving state or production authority
was changed. The native call returns the first failed gate; later measurements
were retained without replacing any of them with artificial passing values.

The complete receipt is [native-rejection.json](native-rejection.json), SHA256
`d0b94580cbdb5a1831b3ff65fc9402b7d089a6152958b1652d5841c4238599dc`.
It retains the canonical signed review bytes, the public ephemeral reviewer
key, all owner-file hashes, policy/report/input digests and compile-time source
hashes. This is a real-measurement rejection qualification. It is not scientific
acceptance or production authentication.

Input identities:

- Actual candidate bundle: `3b88671eb6d88abaa3717c2252e4d80092e09931c5e0c0a85d338aa0fcfdaf52`.
- Actual warmup predecessor: `9737384bb5fef3a684709e8da06216b56fe22e8a122febd063eca935a830725a`.
- Evaluation report: `8ecf4f030ae71d217aedcea80fab596df6dc676ab79044c57c0e4f8d9ee3d2e4`.
- Gate adapter: `b3303f532f04f81a5c268ca4420bd140aa67f8a8303a4c27eae1fb2eca1cf8f9`.
- Frozen protocol: `30880ddaae978f622cf6a99cf3888771daa954777e6f9ce2a75c25f01f166280`.

The trained tensors remain an opaque `research-numpy-float64-bundle.v1` artifact.
This execution makes no claim about native Q24 schema compatibility or serving
inference. The standalone driver build and independent source-review receipt
are in [build-qualification.json](build-qualification.json).
