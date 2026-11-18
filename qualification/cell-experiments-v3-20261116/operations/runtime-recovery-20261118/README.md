# Original runtime recovered for E2/E4, 2026-11-18

The retained desktop environment is usable again. All **19,079 files and
7,111,800,439 bytes** covered by the original installation manifests match their
original SHA-256 values. Missing and differing file lists are empty. Exact
package imports and a tiny CUDA matrix multiplication passed in a fresh process.

| Runtime item | Observed result |
| --- | --- |
| PyTorch | 2.9.1+cu128 |
| Transformers | 4.57.3 |
| PEFT | 0.18.0 |
| NumPy | 1.26.4 |
| Device / CUDA | NVIDIA GeForce RTX 4060 / 12.8 |
| CUDA check | 32 × 32 all-ones matrix product; sum 32768.0 |

This closes a runtime prerequisite. It does not establish a learning gain,
Circuit gain, independent source, new teacher, authenticated user or adoption.
The recovery executed zero model experiments. The original E2/E4 numerical
preparation gates and experiment runners still determine their own outcomes.

## What was repaired

Twenty shared libraries, totaling 5,637,504,148 bytes across twelve pinned
distributions, were absent. Their original installed-file hashes and wheel
pins were present in `operations/recovery-03`. The cause of their absence was
not established by this recovery.

- Stage A restored eight files from retained original wheels and one from a
  newly downloaded pinned cuRAND wheel.
- Stage B copied six CUDA library files from another local environment only
  after their sizes and hashes matched the original installed-file manifests.
- Stage C restored the remaining five torch, Triton and NVSHMEM libraries from
  three complete wheels whose original SHA-256 values were verified on ai395
  and again after transfer to desktop.

The alternate local environment's PyTorch was not installed. Original package
versions, model bytes and adapter bytes were not changed by these scripts.
Each restored library was written to an exclusive temporary file, checked,
then published with a create-only hard link. Existing target files were never
overwritten. The final pass checked every file in the original manifests.

## Evidence and preserved failed work

`AUDIT.json` reconciles all twenty original missing paths with the three stages.
`raw/` contains the original compact JSON/text receipts, copied without changing
their bytes. `RECEIPTS.jsonl` binds their remote paths, lengths and SHA-256 values;
it also binds the retained range-download logs. `SOURCES.jsonl` binds all nine
executed operation sources in the persistent desktop source archive. The three
actual restoration sources are also included verbatim in `source/`.

Four slow download processes owned by this operation were stopped with observed
exit code -15. Their completed restorations, partial wheel files and range
receipts remain preserved. A temporary whitelist HTTP transfer timed out before
transferring a wheel; its server was stopped. No network setting was changed.
Existing authenticated SSH connections then transferred all three wheels
(1,196,009,000 bytes) in 14.08 seconds. Destination hashes were checked separately.

The failed and stopped work was paid work. Complete network wire-byte, energy
and full-system cost totals remain unknown; successful transfer size is not
reported as total recovery cost. No failed receipt was rewritten as success.

The scripts in `source/` are an archive of these one-time operations, not a
general installer or an instruction to rerun them. They preserve the original
operation names and create-only guards. The final script refuses a missing-file
set other than the observed five. Required repository formatting was invoked
on the archival snapshot; its scope excludes these qualification sources, so
the executed bytes remain intact. The formatter receipt is in `FORMAT.json`.

The restored environment was handed back to the E2 owner before any E4 GPU job.
The retained experiment implementation remains pinned to
`eb56c51e4e73b0d466795b257a547ab93a0baa63`; this delivery changes no runner,
training protocol, data, comparison freeze or scientific eligibility rule.
