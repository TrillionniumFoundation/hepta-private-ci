# Historical supervisor authoring workflow

[runtime-supervisor-six-phase-materializer.yml.txt](runtime-supervisor-six-phase-materializer.yml.txt) preserves the original bytes
of the retired `runtime-supervisor-six-phase-materializer.yml` workflow from
commit `6012fc54edd67a8b19dcd8055bc01bbe9fc9a128`:

| Identity | Value |
| --- | --- |
| Git blob | `7096a6275e824eb06c4f19f19a5e8b8b959ff73a` |
| Bytes | `9279` |
| SHA-256 | `34c3b04945fee25600229e5a3cbb06bca5bd0be04bd493f9e5808cbc6047c043` |

The original workflow was a one-shot source-authoring lane. Its push trigger
covered only `codex/runtime-supervisor-six-phase-closure-20260930-r4`, with a
separate manual dispatch entry. It requested repository writes and persisted
checkout credentials so it could publish generated source. Its successful path
was designed to remove itself and the other supervisor authoring workflows,
then commit and push an ordinary source candidate. It was not the read-only
qualification contract used by the current daemon candidate.

The active workflow has been retired. The archived text is historical evidence;
GitHub Actions does not execute files in this directory. It does not establish
that its generation, test or publication commands succeeded, and its historical
`source_complete` output does not override the current capability matrix.

`scripts/runtime_supervisor_six_phase_materialize.py` and
`scripts/runtime_supervisor_six_phase_followup.py` remain available as reviewed
source-authoring CLIs with their regression tests and source bindings. Their
presence is not a running qualification lane, a production receipt or permission
to write source, provision authority, activate or release the module. Current
qualification remains owned by the read-only workflows and their independently
validated execution receipts.

## Unlinked lifecycle prototypes

The files in `unlinked-prototypes/` preserve the exact bytes of three unlinked
Rust prototypes from source `5b71df96f682765b01357ccf4af62f7b4917d02a`:

| Archived file | Git blob | Bytes |
| --- | --- | --- |
| `mutation_journal.rs.txt` | `71aa2cea44e9a09af307e6c96b0bab4d3f89a43f` | 19558 |
| `process_exit_witness.rs.txt` | `0057ad13bacf842ead124a81b812237143c7060f` | 16522 |
| `recovery_observation.rs.txt` | `881852ec560aaf94c48b09842ca477b938781a6e` | 15361 |

The PR base already contained these files without a Cargo target or module
declaration. Later mechanical adaptation to `durable_publish::publish_at`
changed their blobs but did not link them. The native library did not compile
their embedded tests. Their presence never implemented cross-daemon exit
cleanup, ordinary-mutation idempotency or atomic recovery observations.

The prototypes are now outside the native source root. The existing explicit
six-phase authoring CLI can stage their restoration inside its source-edit
transaction before applying its legacy patches. Importing the CLI restores
nothing; marker failure still aborts the transaction. The archived text is not
an active workflow, production API, supported journal codec or recovery
authority. Source authoring does not establish successful compilation, executed
embedded tests, protocol closure, acceptance or activation.
