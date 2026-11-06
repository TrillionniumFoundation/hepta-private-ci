# Original CUDA campaign: offline dependency recovery and observed gates

This append-only evidence records the recovery of the already-deployed campaign
`1a1acdd69f2-fc05-5757`. It does not launch or qualify another campaign. The
frozen candidate remains `f355cfe2ae96b2bc9a5409f8eeb857894f1b0c5b`, and the
original `full.json` SHA256 remains
`7fa3d05b8c04a918043afdfa1c266a17beccb814351258d0555a753baf13777a`.

At the final retained observation, **2026-11-06 08:13:28 UTC**, the same campaign
is running its `full` stage, which started at 08:08:57 UTC. Completed registered
identities remain **0/170** at this snapshot. The legacy diagnostic returned 0
after all 18 grid records. Policy 1 was admitted under the existing rules and
applies uniformly to all 20 B identities. See
[`cuda-gates-20261106-0813.json`](cuda-gates-20261106-0813.json) and
[`cuda-admission-20261106-0759.json`](cuda-admission-20261106-0759.json).

## Dependency failure and repair

The previous Torch v4 job downloaded all 25 pinned wheels but exited 1 because
its suffix-only METADATA selector found nested vendored distributions in the
setuptools wheel. The old status, source and terminal record remain unchanged.
The old Mamba waiter also exited 1 with zero installation attempts.

The separately reviewed v5 installer selects exactly one top-level distribution,
checks Name/Version and pinned directory identity, rejects unsafe or ambiguous
ZIP entries, and keeps complete wheel size/SHA validation. Both affected
selectors use the same helper. It can consume only complete local wheels or
verified local parts; no download fallback exists. An fsynced exclusive claim
binds the one allowed attempt to its exact source. All 43 helper tests passed.

| Stage | Durable result | Recorded wall time | Scope |
| --- | --- | ---: | --- |
| Torch v5 recovery | Exit 0, complete durable output | 158.213956164 s | 25 wheels / 3,918,339,031 bytes; 41 local parts reused; 0 new wire bytes |
| Original Mamba offline installer | Exit 0, complete durable output | 46.634363949 s | 17 artifacts / 706,688,727 bytes; zero download tasks; no emitted per-attempt wire counter |
| Previous failed Torch v4 | Exit 1, preserved | 7859.846566096 s | 2,974,688,904 received bytes in that attempt, not the full historical project cost |

The Mamba installer ran once in its original `--install-verified` mode only
after authoritative Torch exit 0 and the real READY receipt. The failed waiter
was not restarted. Installer imports did not instantiate or train Mamba2.

The actual runtime reports Torch 2.8.0+cu128, CUDA runtime 12.8, official
mamba-ssm 2.3.1 and causal-conv1d 1.5.4. The original controller then advanced
automatically from its existing wait. READY files and durable terminals are
separate evidence; installation alone is not a model qualification result.

## Campaign evidence and interpretation

The timestamped `cuda-gates-*.json` files are immutable observations, not an
eventually updated latest-result alias. They preserve the distinction among:

- the 95-check original and 109-check candidate **CPU** strict suites;
- actual full-shape CUDA forward/backward probes, including failed B OOM;
- CPU and CUDA rematerialization parity and both candidate B probes;
- the official Mamba2 full-shape probe;
- the original full-budget matrix and its separately counted B audits.

A successful single-step probe is not a completed 400-update training identity.
The original B OOM is retained even when the pre-registered rematerialized policy
passes its gates. The active controller alone selects one uniform B policy and
continues the original 170 identities; no failed training identity is
automatically retried.

Physical GPU energy/power counters report unsupported in the pinned device
queries; accessible CPU RAPL energy is also unavailable in the recorded probes.
Missing joules remain null. Neither installed packages, device TDP nor elapsed
time substitutes for a measured physical energy interval. Allocator memory
fractions are process allocator limits, not exclusive GPU reservations.

The newer content source in draft PRs #4941/#4942 is separate from this campaign.
The original delayed-recall/adding matrix cannot qualify its learned MQAR,
matched-parameter or real-media claims.

## Provenance and privacy

Each public JSON is a bounded selected-field view with the original raw receipt
SHA256 and relative path. Those hashes identify retained originals, not the
normalized public JSON. Full original installers, diffs, stage records and
durable process receipts are retained on the task host and in a private review
attachment. Public files omit host home paths, owner metadata, credentials,
signed URLs and unrelated process details.

`MANIFEST.json` records every public payload's SHA256/size, excluding itself.
Earlier evidence directories and the failed attempts are not overwritten.
Hosted exact-source CPU CI success is independently recorded in
[run 42078258351](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42078258351);
it is not a substitute for the desktop campaign results.
