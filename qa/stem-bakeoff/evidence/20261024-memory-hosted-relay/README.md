# Hosted parameter-cell relay: recovered execution evidence

Two independently provisioned GitHub Actions runner environments completed the
registered checkpoint transfer and withdrawal experiment. The real adapter
answered the three retained synthetic facts on both sides; disabling or shuffling
the adapter answered none. Withdrawal and restart replay were rejected before
another model callback. This closes the narrow hosted relay mechanism exercise.
It does not close the general distributed-memory or production qualification.

## Immutable execution identity

| Item | Value |
|---|---|
| Repository | `TrillionniumFoundation/hepta-private-ci` |
| Executed commit | `c11a9f7fe85f1bbc5e008ac02b5639e1e8502a92` |
| Run | [40102776848](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40102776848) |
| Source job | `120898163723`, `source-owner`, success |
| Target job | `120898163902`, `target-worker`, success |
| Runner image | Ubuntu 22.04, version `20261012.322.1` |
| Base | SmolLM2-135M-Instruct, publisher revision `12fd25f77366fa6b3b4b768ec3050bf629380bac` |
| Base six-file identity | `46b83e37620f8bb1ae57754856718886c6aa1b12d267b5b0993e779f9596f96f` |
| Checkpoint lineage digest | `9f943be3b30b80b34448940b71dc6e8e25411d6862fa6ba1dc15c2bee3b574ab` |
| Adapter safetensors SHA-256 | `0041e196985d945e02b0ae7f96a85337a6202e950c223e58913a06fdc1cf36c1` |

The source and target runner names are `GitHub Actions 1000224052` and
`GitHub Actions 1000224054`. Their boot-ID digests differ. Both report hostname
`runnervmwhx2h`; that shared hostname is not a machine-identity proof.
The job logs additionally report distinct worker IDs and provisioning regions.
These observations establish separate runner environments. They do not provide
independent physical-hardware attestation; the protocol and report explicitly
retain `physical_hardware_attested=false`.

## Main experiment: actual work and outcomes

The frozen protocol uses seed 2718, rank 8, learning rate 0.001, and three random
color assignments made after checking out the frozen source. It performs one
256-update source-local fit. The same adapter, configuration and lineage bytes
are copied to the target. The source database is not part of the target package.
Decoder input journals report no fact input, retrieved evidence or answer lexicon.

| Measurement | Actual result |
|---|---:|
| Decoder optimizer updates / model forwards | 256 / 256 |
| Training input / supervised tokens | 17,345 / 512 |
| Trainable adapter values / tensor bytes | 460,800 / 1,843,200 |
| Source adapter exact answers | 3/3 |
| Source base-only exact answers | 0/3 |
| Source shuffled-adapter exact answers | 0/3 |
| Target first fresh-process exact answers | 3/3 |
| Target repeated cold requests | 32/32 |
| Main decoder rows | 44 = 9 source + 3 target initial + 32 load |
| Main decoder input / generated tokens | 3,168 / 172 |
| Main model child receipts | 37 = one training + 36 decoder processes |
| Main child exits | All 37 exit 0 |

Every main decoder request enters a fresh child process. Source and target
first-read text, token IDs and prompt identities match. The 32 load queries
repeat the same three facts; they are not 32 independent future tasks.
The successful three-fact transfer does not establish broad recall quality.

### Additional preflight work

Before the main source fit, the source runner executed 16 distributed-stack tests
in 33.902 seconds; all passed. One is an actual tiny-decoder composition test
with mocked delivery and identities. Its exact source specifies 12 additional
updates, nine source decoder rows, three target initial rows and two load rows:
14 tiny decoder rows in total. Tiny-base fixture creation performs no fit.

These 12 updates and 14 rows are additional work; they are not included in the
main 256/44 counts. Their temporary model receipts were deleted by the fixture
and were not uploaded. The count is derived from the pinned source and the
successful test log, not from a retained per-call cost ledger. The workflow
installation, dependency acquisition and this preflight are outside the main
phase resource meters. No complete workflow bill is claimed.

## Admission and source boundaries

The source hands its worker the new target placement (`worker-b`, generation 1)
and durably records that frontier before uploading the offer. Reads attempted
on `source-a` are refused twice, with callback count remaining 3. The trial does
not explicitly replay a generation-0 `source-a` placement after the handoff;
the refusal is not evidence for that unexecuted case.

The target completes 33 decoder callbacks, receives the withdrawal, and refuses
another read with the count still 33. A fresh owner then refuses the older
signed source frontier, also without another callback. Durable owner/fence
databases are retained. The experiment does not restore an entire older volume,
simulate physical power loss, elect a replacement authority, or test Byzantine
source behavior.

The target requested one explicitly granted source root. The source serialized
174 evidence bytes, then withdrew the source before delivery. The target received
those remote bytes but recorded `current_support_accepted=false`. This is an
actual delayed-evidence rejection. It does not include a successful current
remote-evidence read. No `sources.sqlite` exists under the registered target
evidence tree; this is a package/tree boundary, not whole-VM forensic attestation.

The transport is authenticated, same-run GitHub artifact delivery with signed
bounded envelopes. It uses a single source signer and asynchronous cuts. The
trial does not exercise cross-host online mTLS, quorum authority, immediate
revocation before delivery, partition healing, or continuous availability.
Local preflight quorum/TLS tests remain separate from this cross-runner result.

## Latency, transfer and storage accounting

| Measured cold-load quantity | Value |
|---|---:|
| Arrival model / concurrency | Serial closed loop / 1 |
| Completed requests | 32 |
| Total load wall time | 222.768862488 s |
| Sum of measured request intervals | 222.746039660 s |
| Coordinator overhead between requests | 0.022822828 s |
| p50, registered lower-middle observation | 6.956435145 s |
| p95, registered nearest rank | 7.011685334 s |
| Throughput | 0.143646646 requests/s |

This is short cold-process throughput over three facts, without competing
arrivals or online authority requests. It is not a sustained service capacity.

| Main phase | Wall seconds | CPU seconds |
|---|---:|---:|
| Source prepare | 136.680018 | 248.420252 |
| Source await/withdraw | 257.526307 | 1.855800 |
| Target await/read/load | 415.055541 | 251.168249 |
| Target withdrawal | 16.407253 | 1.796686 |
| Target restart replay | 0.025785 | 1.765023 |

The phase wall intervals overlap between runners and include artifact waiting.
They must not be summed as elapsed end-to-end latency. CPU counters are phase
process-family observations. Maximum observed source and target child RSS are
1,256,960,000 and 1,143,627,776 bytes; simultaneous aggregate peak RSS was not
measured. No cost dimension becomes zero merely because it was unmeasured.

Four transfer receipts record 1,843,458 compressed ZIP bytes, 2,556,658 JSON
payload bytes and 35 polls. The 28,500 listing-response bytes are a JSON
reserialization estimate; TLS/network-packet bytes were not measured.
Both runners retain their own base. The six pinned model files total 271,170,520
bytes per base; the observed prepared directories total 271,171,147 and
271,171,150 bytes including their download-cache metadata. Main source and
target evidence inventories at their recorded cutoffs total 6,543,437 and
4,775,743 bytes. Later report, inventory and archive files have separate sizes.

These inventories include duplicated checkpoints and transport payloads where
physically present. Base/runtime acquisition, full runtime and OS dependencies,
transient file byte-time, aggregate peak memory, network overhead and provider
fees are incomplete. No net-compression ratio or equal-quality cost advantage
over source retrieval follows from this trial.

## Recovery package and independent byte audit

This package recovers the original hosted result after a local session checkpoint
became unavailable. It is not a new experiment or a replay of model inference.
Six original artifact ZIPs were downloaded again, matched to their GitHub SHA-256
digests and lengths, and safely checked across all 168 file members. All original
ZIP bytes, both job logs, API metadata and 41 pinned source/context files are
retained. Large base/runtime installations are external dependencies.

The standard-library audit completes 952 comparisons with zero failures and
zero new model/router calls. They are byte/count comparisons, not 952 tests.
Two earlier audit attempts are retained: one incorrectly equated total load
wall time with the sum of request intervals, and one assumed the usual averaged
median instead of the registered lower-middle observation. Correcting these
audit assumptions did not change the experiment, its source or raw results.

`parts.json` identifies the ordered binary archive parts. Run `reassemble.py`
beside those files to check part sizes, SHA-256 and Git blob IDs, then the full
archive digest. Extraction yields `memory-hosted-relay-20261024/`. Its manifest
maps every payload path to its digest; `audit-run-003/result.json` contains the
count audit. To audit again without running a model, extract the original ZIP
members under their corresponding `artifacts/<id>/files/` directories, then run
the included audit script with a new output path. Keep original evidence intact.

The full distributed-memory and production acceptance flags remain false.
