# Ordinary Cell host v2

This candidate adds the complete declared Cell byte plan to the existing
`hepta-neural-agentd` route. It does not issue product qualification, install a
model, change CURRENT, or mint FinalUse. The source baseline is Hepta
`3a81000aae08c658276958d678874aca4db5eedd` (#4491); this patch does not merge or
qualify the separate #4368 PQ branch.

## Explicit format and original owners

The existing command accepts `--host-format cell-v2` alongside its independently
authorized `--host-config` and `--host-config-sha256`. Its default `owner-v1`
retains the original host file. Unknown and duplicate format arguments fail.
The two formats use distinct strict schemas; an old host-v1 JSON file cannot
satisfy Cell-v2 admission.

An explicitly selected Cell-v2 daemon must have a current executable path that
can be reopened to the same device/inode as `/proc/self/exe`. This narrow check
runs after original helper dispatch but before dotenv, PATH aliases, qualification
or any model owner. The original `owner-v1` and helper dispatch behavior stays
unchanged. It grants no new process or sandbox permission.

Anonymous sealed ELF execution does not currently meet this requirement: its
`current_exe()` path cannot supply the original aliases and later sandbox re-execs.
A `/proc/<host-pid>/fd/...` alias alone would also be insufficient after the
original sandbox creates its fresh PID namespace and `/proc`. This route is
explicitly unavailable; the sandbox and its namespace policy are retained. A
separately selected protected installed ELF may use the original stable paths;
its installer/ownership policy remains the producer's responsibility.

The new `hepta-smollm-cognitive-cell-host-v2` object contains these exact fields:

| Field | Meaning |
| --- | --- |
| `schema` | `hepta-smollm-cognitive-cell-host-v2` |
| `owner` | Unchanged complete `hepta-smollm-cognitive-host-v1` object |
| `sidecar` | `{path, sha256}` for the existing controlled eleven-object sidecar |
| `dependency_closure` | `{path, sha256}` for canonical TCD1 bytes |
| `dependency_closure_id` | TCD1 domain-separated content id, independently pinned by the host owner |
| `operation_id` | Exact original operation identity, checked against the sidecar |

The nested owner retains descriptor, worker, resource grant, inference journal
and FinalUse issuer configuration. Protected files use the existing bounded
regular-file, canonical-path, ownership, permissions and link-count checks.
Sidecars are at most 65,536 bytes; TCD1 objects are at most 1,048,576 bytes. The
decoder holds owned byte snapshots and opens no inference journal or model.

Preparation still replays the original product-qualified descriptor and CURRENT
selector and reads parameters from the selected descriptor FD. Only then does
Cell-v2 run the existing complete material verifier against those owned parameters
and the original worker/source/profile pins. All eleven TCM1 payloads and TCR1
membership are measured and verified before TCD1 admission.

After byte qualification, the same original resource, inference.control and
Unix FinalUse owners start the same cancellable inference port. The caller's
cancellation token is preserved. A cancelled or failed preparation never falls
back to an unqualified model; after-load cancellation retains the original
terminal unload path.

The existing 120-second startup window starts before queuing preparation. Original
qualification, Cell validation, opening inference owners, FinalUse and physical
loading all consume that one monotonic deadline and cancellation token. The
loader receives the original execution object; it does not start another
120-second window after scanning. Its durable load request is also limited to the
remaining whole milliseconds. Each Cell payload read checks the same execution
before and after the OS call, including short reads, EOF and EINTR, and after
each chunk hash. Expired verification cannot open inference owners or start a
model. A late physical completion keeps the original failed/terminal handling.

This is cooperative deadline enforcement, not a hard wall-time bound on a
blocking filesystem. Regular-file open, metadata or read operations may remain
inside the OS after expiry; small original source/config reads also only observe
the deadline after returning. The blocking task retains its owned files until
they return, then rejects their late result. Cancelling the preparation future
does not pretend that its blocking worker stopped or release a live model
custodian. Hard interruption of a stuck filesystem remains an open PN3 limit;
the CI observer's execution timeout is not a product startup budget.

## Exact registered closure

This is the existing fixed SmolLM2 135M dense single-adapter profile. It is not a
new general model registry. TCD1 is reconstructed byte-for-byte from the measured
existing sidecar and owner context; attacker-provided counts or graph indices are
not allocated or interpreted. Any changed byte, suffix, missing file, path alias,
different generation/profile, or incorrect content-id domain fails.

Files retain the original mandatory names, including `base/README.md`.
Canonical index 0 (`adapter/artifact.safetensors`) is the sole root and depends on
all ten remaining files. Base weights have role 1, tokenizer files role 2, the
adapter role 4, and the original configuration/metadata files role 6. Other model
layouts or dependency graphs require an explicitly reviewed loader profile.

The selected generation is the original model pin's generation; the loader
profile is its verified execution-profile digest. The embedded TCR1 carries the
existing backbone, parent payload, tokenizer, contract/layout and worker context.
The id uses `SHA256("trnm.cell-dependency-closure.v1\0" || canonical_TCD1)`.
Content addressing is not a PQ authorization protocol. This patch preserves the
existing owners and requires their independently authorized host pins; it cannot
make #4491 and #4368 an accepted joint PQ source pair.

## Validation scope and remaining PN3 gates

The new fixture is an independent Python-generated TCD1 vector with synthetic
bytes for the exact eleven-file roster. Rust reconstructs it and rejects every
mutated byte, missing member, wrong profile/generation and README case alias.
Protected-file tests cover separate v1/v2 decoding, pinned-byte mismatch, missing
or unknown fields, operation identity, and symlinks. Real CLI subprocess controls
exercise format dispatch and strict rejection before any fleet/model owner.
The actual CLI image control copies the native daemon into a sealed memfd and
checks both `cell-v2 --help` and a cold config reject before creating aliases.
Named-image help still reaches the normal parser, and an actual apply-patch alias
retains original helper priority. These are executable/entry controls, not proof
of a successful sandboxed model run.
These controls do not count as a successful real-model installation or round.

PN3 remains incomplete until the exact unified Chain/Hepta source pair passes its
ordinary required gates, the existing transport producer emits this exact TCD1
and sidecar, a real complete release reaches the ordinary selected model loader,
and three genuine feedback rounds produce their actual owner readbacks. A
transport completion file or synthetic fixture cannot replace those observations.
