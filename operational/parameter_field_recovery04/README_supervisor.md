# Execution04 supervisor and durable stage archives

This is a prospective, Linux/cgroup-specific operational adapter for
`execution04_durable_20261030`. It keeps the original scientific modules,
controller, analysis assembler, protocols, worker reservations and storage
checks unchanged. The existing `attempt02` fields remain legacy reader/schema
identifiers; the distinct execution episode is carried explicitly outside them.

These files prepare execution. They do not demonstrate that any real job,
upload, remote readback or finalization has succeeded.

## State transitions

The supervisor starts one original `controller_envelope_v2` through the
registered `cwd_runner.py`. Its actual queue initially contains only `A-17`,
with `finalize=false`. It appends one canonical definition at a time:

`A-17, A-29, A-43, C, B-17, B-29, B-43, W, R-17, R-29, R-43,
A_endpoint, B_endpoint, C_endpoint`.

Before each append, the immediately preceding job must have a successful
original controller result, its original completion seal and an empty worker
registry. Its closed files are archived and independently verified. The
supervisor then waits for an external upload/readback ACK and verifies every
item in that ACK. This invariant is also checked inside `activate`, not merely
assumed from the ordering of calls.

After the third A job is durable, `registration.py` creates canonical prefix 11
from the original prefix 4. After job 11 is durable it creates canonical prefix 14.
Previously accepted definitions cannot change. After the last endpoint ACK,
the supervisor changes only the actual queue's `finalize` flag and allows the
original controller to write its full fourteen-job `EXECUTION.json`.

The controller's closed artifacts are then saved and acknowledged. Registered
aggregate analysis requires the original 26 scientific seals; its completed
output is saved and acknowledged before finalization. The unchanged finalizer
requires 30 seals and performs its original literal restore/write/readback
verification. The supervisor checks the actual file, byte and logical-path
counts, saves all remaining raw bytes and stable operation metadata, and
requires the final ACK before publishing primary completion.

There is no mid-job scientific checkpoint/resume facility in this adapter.
An executor loss can lose at most the current job's unacknowledged work, plus
external work whose upload outcome was not yet known. A replacement executor
must not silently restart that job or infer completion from an archive name.

## Configuration contract

The root prepares the immutable JSON config and records its exact SHA256.
The top-level schema is `hepta.fullstudy.execution04.configuration.1`.
Required fields are:

| Field | Required value or meaning |
| --- | --- |
| `execution_episode` | `execution04_durable_20261030` |
| `source_root` | `/workspace/scratch/178ced6a501f/fullstudy_git` |
| `source_commit` | Real complete 40-hex commit containing the identical operational adapter sources; continuation metadata may have a later commit than initial freezes |
| `python` | `/workspace/scratch/178ced6a501f/runtime_recovery_20261030/venv/bin/python` |
| `ops_root` | `/workspace/scratch/178ced6a501f/fullstudy_execution04_ops` |
| `raw_root` | `/workspace/scratch/178ced6a501f/fullstudy_execution04_durable_raw` |
| `cas_root` | `/workspace/scratch/178ced6a501f/fullstudy_execution04_durable_raw_cas` |
| `empty_cwd` | Existing empty directory outside the source tree |
| `active_queue` | New or exactly matching initial actual queue path inside OPS |
| `job_order` | The exact fourteen IDs in the order above |
| `descriptors` | Map described below |
| `initial_metadata` | Optional ordered list of exact additional initial registration/input metadata descriptors |

Every descriptor is a complete `{path, bytes, sha256}` object with an absolute
file path. Required descriptor keys are `amendment`, `initial_queue`,
`controller_freeze`, `cwd_runner`, `cwd_policy`, `registration_driver`,
`registration_config`, `runtime_receipt`, `own_supervisor`, and
`durable_archive`. Add `wait4_launcher` when using the measured launcher.
Additional descriptors are verified and archived too.

Repository-backed files, including adapter code and the registered amendment,
are referenced by their exact config descriptors and real Git commit rather
than copied into Library archives. Root verifies their remote Git publication
before science. Non-repository configs, freezes, input metadata and all selected
raw bytes remain included; this does not omit any raw logical artifact.

The separate registration config follows `registration.py`'s own contract.
Its CLI is:

```text
<verified-venv-python> -B <source>/operational/parameter_field_recovery04/registration.py \
  --config <registration-config-path> \
  --expected-config-sha256 <registration-config-sha256> \
  --stage followups|endpoints|analysis|finalizer
```

The driver returns canonical queue and complete file descriptors without
activating a job. The supervisor verifies `bundle`, `canonical_queue`,
`registration_cost`, `driver_receipt`, `driver_cost`, and every `files` entry.
The entire closed `OPS/registrations` tree, including historical cost projection
receipts, is retained in the archive metadata.

The venv executable path is deliberately preserved literally. Resolving its
symlink to the base interpreter would bypass the recovered venv packages.
Source publication and input recovery must be completed by the root before an
actual launch; a local Git check alone is not a remote-publication claim.

## Admission, failures and process ownership

Initial admission requires three consecutive samples ten seconds apart with
effective cgroup available memory at least 1,879,048,192 B and actual output
volume `f_bavail * f_frsize` at least 2,415,919,104 B. Effective memory uses exactly
the original subtraction of clean inactive file pages. The same conservative
outer check is repeated before analysis and finalization; those repetitions
are additional supervisor checks, not requirements attributed to the original
modules.

The original contract is separately checked for 2 GiB logical raw, 256 MiB physical
reserve, 350 MiB C training evidence cap, 1 GiB memory margin, 768 MiB worker reservation
and the unchanged ceiling of two workers. The actual queue enforces scientific
concurrency one. Archival runs only with no scientific worker and checks the
original 1 GiB margin and physical reserve while streaming. No global cache drop,
cgroup setting change, process interference or hidden resource relaxation is
performed.

The outer wall window is twelve hours, including admission, archives and ACK
waits. A present but malformed, partial or uncertain ACK fails closed. A missing
ACK waits within that window. No upload is attempted by these scripts, and no
unknown upload outcome is automatically retried. Any science failure, controller
failure or new OOM stops the episode; this implementation does not automatically
resume even a controller admission exit 75. Existing evidence stays intact.

Each direct child starts its own session. The supervisor records PID,
`start_ticks`, group, session, exact argv, stdout and stderr, and reaps that exact
child using `wait4`. Failure handling signals only verified owned groups.
Successful already-reaped children are never signalled later. A failure while
recording a newly spawned child is handled inside its constructor so a missing
START receipt cannot lose the handle.

Actual launch also requires the syscall PID, group and session to match
`/proc/self/stat`. The current default sandbox can expose a host `/proc` with
different namespace-local PIDs. It is rejected before spawning: actual import
probes, the measured launcher and science must use the authorized host execution
surface. No original scientific PID behavior is changed to mask this mismatch.

## Archive format and stable file selection

`OPS/durable/NN_LABEL/REQUEST.json` is the handoff point. `STATUS.json` keeps the
same request and expected ACK path in `awaiting_durable` throughout the wait.
There are fourteen job requests, then controller, analysis and final-closure
requests. Archive names are evidence labels, not success claims.

Each gzip tar part contains at most 128 MiB of uncompressed file payload; tar
headers/padding and gzip framing are additional. A larger logical file is split
into ordered chunk members. `MANIFEST.json` maps the original logical path to
its ordered `{part, member, offset, bytes, sha256}` chunks and complete SHA256.
Empty files are retained. Parts and files are independently streamed and hashed;
no whole model, checkpoint or archive is loaded into memory. Source identities
are checked before and after reads. Exact large identity values are decimal
strings to avoid lossy JavaScript numeric serialization.

`VERIFIED.json` records independent decompression and recombined logical-file
hash verification. This is not the original finalizer's literal restore test;
both operations remain separately identified and charged. Restoration uses the
manifest's relative part names beside the manifest, verifies compressed hashes,
concatenates a file's chunks at their declared offsets into a new empty tree,
and verifies its final byte count and SHA256. The tar member paths are chunk
containers; extracting the parts directly does not recreate the original tree.

For each job, the archive contains its entire closed stage/seed subtree, stable
controller START/RESULT/log, operation START/COMPLETE, exact source/input metadata
and closed cwd launch receipts. B/C endpoint jobs additionally include their
stage-root `ENDPOINT_CHECKPOINTS.json` and the qualification/final access freeze.
Live progress, active controller output logs and active locks are not selected
during science. After all original processes stop, final closure includes the
now-stable remaining RAW artifacts, including the finalizer's own metadata,
controller/analysis logs and closed lock-file bytes. Restoring lock-file bytes
does not restore an OS lock.

All prior requests, ACKs, verified ACK records, archive manifests, verification
receipts and archive cost records are included in final closure. Existing
archive blobs and downloaded readback copies are not recursively archived;
their actual remote identities are already recorded by their ACKs.

## External Library upload and ACK

The root uses the current Library skill and its refreshed helper at
`/workspace/scratch/178ced6a501f/library_recovery_tools_20261030/library_upload.py`.
Do not inspect or replace the helper implementation. Submit the entire ordered
request `items` batch once using its documented stdin form:

```json
{"uploads": [{"local_path": "/absolute/path/from/request", "purpose": "create_library_file"}]}
```

The helper owns prepared upload, transfer and finalization. Check every per-item
success, preserve actual returned Library identities and versions, and obtain
actual remote readbacks through the supported Library tools. If an outcome is
unknown, reconcile it instead of retrying. The supervisor does none of those
remote operations on the root's behalf.

The root writes `ACK.json` atomically only after all returned items and actual
readback hashes are verified. The following is a schema example: bracketed
values are placeholders, not remote receipts or successful tool results.

```json
{
  "schema": "hepta.fullstudy.library-archive-ack.1",
  "status": "VERIFIED_REMOTE_READBACK",
  "unknown_upload_outcome": false,
  "request": {"path": "<REQUEST.json absolute path>", "bytes": 0, "sha256": "<actual SHA256>"},
  "binding": "<the exact REQUEST.binding object, not a string>",
  "items": [{
    "local": {"path": "<exact request item path>", "bytes": 0, "sha256": "<actual SHA256>"},
    "upload_item_success": true,
    "remote_readback_performed": true,
    "remote_identity": {"library_file_id": "<actual returned ID>", "version": "<actual returned version when available>"},
    "readback_remote_identity": {"library_file_id": "<same actual ID>", "version": "<same actual version>"},
    "upload_receipt": {"path": "<actual tool receipt>", "bytes": 0, "sha256": "<receipt SHA256>"},
    "readback_receipt": {"path": "<actual readback tool receipt>", "bytes": 0, "sha256": "<receipt SHA256>"},
    "readback": {"path": "<actual separately materialized readback>", "bytes": 0, "sha256": "<actual SHA256>"}
  }]
}
```

There must be one item in the same order for every requested part, manifest,
verification record and archive cost receipt. A readback must be a distinct file,
not the local source or a hardlink. The verifier hashes its actual bytes.
Remote-service identity is authenticated by the root's real tools and their
receipts; the stdlib verifier does not independently authenticate the service
or treat an ordinary local copy as proof that an upload occurred. Synthetic test
ACKs are explicitly test-only and must never be used for execution.

## Completion and costs

Only `OPS/COMPLETE.json` with schema `hepta.fullstudy.pipeline-completion.4` and
`complete=true` is the primary completion artifact. It exposes full descriptors
under `artifacts.verified`, `.manifest`, `.aggregate_results` and
`.finalizer_freeze`, as well as actual 14-job/30-seal and literal-restore counts.
The original raw `external_uploads=0` remains its original local component's
scope; verified external uploads are recorded separately by this supervisor.

Archive CPU is nested within supervisor CPU. Driver, analysis, controller and
finalizer costs are nested within the supervisor's wait4 child observations.
Do not add those detailed attribution ledgers again to the inclusive process
total. Historical failed-work projections belong to their own all-attempts
scientific ledger and must not be added a second time as operational overhead.
External upload/readback process CPU is outside this process tree and must be
recorded separately by the root, without inventing measurements.

`wait4_launcher.py` measures the full supervisor entry-to-exit and waited
descendants, including config validation and archival. Use its `--execute` only
after registration/publication review. Root may detach this measuring parent
using the authorized process-launch mechanism. With no `--execute`, both entry
points only verify/describe their inputs and start no worker or upload:

```text
<verified-venv-python> -B <source>/operational/parameter_field_recovery04/supervisor.py \
  --config <pipeline-config> --expected-config-sha256 <actual-sha256>
<verified-venv-python> -B <source>/operational/parameter_field_recovery04/wait4_launcher.py \
  --config <pipeline-config> --expected-config-sha256 <actual-sha256> --execute
```

The primary COMPLETE, last ACK verification record, final live supervisor log
tail and the outer `wait4_launcher/WAIT4_COMPLETE.json` can only close after the
last archive or supervisor exit. The root must persist these terminal small
artifacts once afterward. They are explicitly not claimed to contain their own
future upload acknowledgement. No science remains to advance at this point.

On failure, the wait4 receipt marks un-waited descendant costs as potentially
unknown. This is evidence of a failed episode, not a completed experiment.

## Scoped checks

`test_supervisor_semantics.py` uses only small temporary synthetic byte strings.
It verifies bounded chunk reconstruction/corruption detection, full ACK coverage
and independent readback requirements, refusal to activate without the prior
ACK, immutable accepted definitions and refusal to signal an old successful
child. It also injects a START receipt failure around a small synthetic sleeping
child and verifies that the child is terminated and reaped; this is not a
scientific worker. It imports no science, performs no network request and creates no actual
Library file. The root records its real exit status separately; this README
does not manufacture a test-pass claim.
