# Codec environment engineering follow-up

The unchanged historical codec tests reproduce a false green with an empty
`PATH`: the process exits zero while all 21 tests are skipped. With existing
FFmpeg, ffprobe and OpenSSL available, the same original 21 tests execute and
pass with zero skips. This separate environment replay earns no A/B task-repair
or model-benefit credit.

## Actual recorded outcomes

| Environment | Process exit | Discovered | Passed | Skipped | Process wall time |
|---|---:|---:|---:|---:|---:|
| `PATH=""` | 0 | 21 | 0 | 21 | 0.116491 s |
| `PATH="/usr/bin:/bin"` | 0 | 21 | 21 | 0 | 11.383619 s |

Both executions report zero failures, errors, expected failures and unexpected
successes, without a timeout. The negative arm meets its registered environment
observation; it is not successful test coverage. The positive unittest log
reports 11.305 seconds; process wall time also includes startup and coordinator
timing. Neither measure is a general performance result.

The same absolute Python executable, test argv, source directory and 300-second
per-command ceiling were specified before replay. Each arm ran once without an
automatic retry. The discovery pattern `test_*media*.py` covers eight decoded
media tests, six media-type tests and seven signed-media bridge tests. The
unchanged source invokes real codec and OpenSSL subprocesses and uses generated
signal fixtures. Those fixtures are not neural model outputs.

## Exact original source and protocol

- Source commit: `a88f2832f2a1a4d3734c1c88f76977dcc9b98ff1`.
- Source tree: `a536ad588592851225003384121aac243097e0bb`.
- Source closure: 25 files, 220,039 bytes, including original fixture helpers.
- Source-manifest SHA256: `c880266b1f27eee68e0e7ff7a2b47def718070b5b8caa8727a591446d77e22b3`.
- Frozen protocol SHA256: `a17a78785482c1e06220d3f973cd9bf73ea5460235f9cdb0d1fa126bc20f00b9`.
- Actual result SHA256: `e36e79c4f6b34f9ce76bf56236aa80d21437f7b17cd07352deb730af3042cb94`.

The original manifest, protocol, driver, source-before/source-after records,
command/PID/start receipts, stdout, stderr and result files are preserved
byte-for-byte. Current source matches all 25 original Git blob SHA1 and SHA256
values, and both execution-time source inventories match that manifest. The
launch receipt binds the exact driver and frozen protocol.

The original CI observation is
[run 39964510679, job 120450755349](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39964510679/job/120450755349).
This local replay does not qualify that hosted workflow's installation process
or transfer a pass to any queued or unrelated CI run. No package installation
was part of this replay; it exposed tools already available on this host.

## Evidence and packaging audit

Download [codec-engineering-followup.tar.gz](codec-engineering-followup.tar.gz)
and verify its SHA256 against [evidence-manifest.json](evidence-manifest.json)
before extraction. The archive root is `codec-engineering-followup-20261024/`. `raw/` contains every
original file. `MANIFEST.json` records member hashes and original path mappings;
[members.jsonl](members.jsonl) gives one record per payload member.

[audit.json](audit.json) records 115 successful read-only comparisons, including
exact test names/statuses from both raw stderr logs, command/PID bindings,
source/driver identities and unchanged A/B result hashes. These are artifact
comparisons, not newly executed tests. Packaging did not import test/model
modules, run discovery, invoke codec tools or call a model. Every archive
member was then byte-verified with normalized tar/gzip metadata.

The three tool hashes at packaging agree with preparation. The original driver
does not retain separate exec-time hash/PID traces for each FFmpeg, ffprobe or
OpenSSL subprocess. Installed binaries and their complete dynamic runtime are
external dependencies; the archive contains source and receipts.

## Scope preserved

A/B protocols, source seals, budgets, predictions, success metrics and original
gate coverage remain unchanged. This follow-up is not a learned repair, new
prospective task, strong retrieval baseline or equal-budget comparison. It
establishes the two declared local environment observations. Model calls are
zero and memory-repair credit is false. The source manifest's preparation flags
remain historical observations; `raw/run-001/result.json` is the later completed
execution record. The replay occurred after the frozen B model execution and
is excluded from the B cost ledger and all A/B outcome denominators.
