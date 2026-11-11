# Original Desktop organ candidate

This is the development and qualification entry for the independent Notes and
Calculator successor to Hepta `a39a0871d9601ffccb5e0d95d8f39d54b3a63360`.
The historical frozen Linux product paired Desktop
`fd8d56c52b971c2d5d0e6430f296803b43ef60a3` with that Hepta commit. The current
source contract below, each fixture result and each installed product receipt
have separate scope. Historical evidence is preserved with its original pair.

## Versioned composition

The candidate uses the original Root issuer, registry, writer authorization,
protected CognitiveStore, Objective sender/outbox and FinalUse machinery. Notes
keeps the original Notes consumer; Calculator has its own exact target, topic,
payload and typed receipt on the original Device consumer. Both use the same
`Arc<ProductionDurableWriter>`. There is no second authority or effect ledger.

| Boundary | Candidate value and owning code |
| --- | --- |
| Session reservation and deployment profile | `notes_calculator_v1`; `desktop_startup.rs`, `root_desktop_reservation.rs` |
| Trusted Root launch profile | Fresh `hepta.root.desktop_launch_profile.v1`, explicit recovery `.v2`; `desktop_launch.rs`, `root_desktop_startup.rs` |
| Root-sealed Agentd deployment | Fresh `hepta.agentd.original_desktop_launch.v1`, explicit recovery `.v2`; `production_desktop_deployment.rs`, `desktop_previous_recovery.rs` |
| Original Core execution profile | `hepta.desktop.core-execution.v1`; `desktop_thread_execution.rs` |
| Original Objective admission and retained callback profile | `organ.desktop.thread-tool.v1`; `hepta-objective/src/desktop_thread_source.rs`, `hepta-memory/src/objective_sender_desktop.rs` |
| Original Core catalog and seed | `desktop_thread_catalog.rs`, `desktop_thread_seed.rs`; a new `DesktopThreadSeedReceipt` |

`seed_original_desktop_thread` creates metadata for a new original Core thread
with the six-tool catalog and restrictive execution configuration. It does not
submit a user message, run a model turn or grant authority. The original
SessionMeta, catalog, model/provider tuple and configuration hashes are retained
and independently compared on resume. A lost thread-start reply stays unknown;
thread creation is not retried. Existing Notes-only catalogs, seeds, threads and
historical receipts keep their original meaning and are not migrated in place.

## Six tools on one original thread

| Tool | Input and result boundary |
| --- | --- |
| `hepta_notes_state` | Independent current document observation; no effect permission. |
| `hepta_notes_replace` | Bounded text and the independently observed `expected_revision`; exact Notes operation through the original writer. |
| `hepta_notes_status` | Read the exact retained `turn_id`/`call_id`, or `latest_original_replace`; no replacement operation. |
| `hepta_calculator_state` | Empty argument object; independent current Calculator target, revision, operands, operator and result. |
| `hepta_calculator_evaluate` | Canonical decimal-string signed i64 operands, `add`/`subtract`/`multiply`/`divide`, and `expected_revision`; checked arithmetic, with integral division required. |
| `hepta_calculator_status` | Read the exact retained `turn_id`/`call_id`, or `latest_original_evaluate`; no effect dispatch. |

The two effect tools share one durable attempt per original Core turn. The
original sender's Run fence and the writer's already-prepared operation both
participate, including a preparation whose signing or sender acknowledgement
was lost. Changing application, call ID or arguments cannot obtain another
attempt. A subsequent original turn can choose a target under a new actual
human/Core admission; this version does not support multiple effects in one
turn.

The runtime accepts callbacks from its one original App Server connection and
compares the actual in-progress Core item, arguments and callback digest.
Serialized callback metadata alone is not that proof. The original human text
authorization, source compiler, issuer and Objective admission remain required.

For a later effect callback in an occupied turn, the response says
`requested_effect_performed: false`. Its `callback` identifies the refused
request; `original_reference` and nested `original_operation` preserve the first
request's tool, target, destination and causal result. A committed Notes result
cannot become a successful Calculator result, or the reverse. The response does
not promote the nested receipt or terminal state to a top-level success.

Status uses the original sender's complete bounded retained cut, with exact
signed source, callback, operation and target checks. It does not scan only the
latest sixteen Core turns. Missing or ambiguous history remains unknown.
Current application state is reported separately from the original causal
receipt; a displayed result or a matching revision alone cannot prove an old
operation. Recovered sender handles and status calls cannot sign, send or
repeat an effect. See [the sender contract](../hepta-memory/OBJECTIVE_SENDER.md).

## Trusted startup and budgets

The Root factory consumes the real Session's credential-checked reservation and
held pidfd. It binds the actual Notes and Calculator targets and nonce, seals
the separate Desktop deployment, and releases the original late Root handoff.
Agentd reads the deployment only after authenticating that handoff. It opens
the original protected writer once, activates the reservation, then accepts
Notes's two-descriptor offer/ACK followed by Calculator's two-descriptor
offer/ACK. The original owner acknowledges its protected Current before installing the
joint runtime and selecting previous operations. Selection itself is read-only.
The original installer publishes the runtime only after its live-authority
checks. The launcher retains the entire
`AgentdDesktopProductionAttachment`, including Calculator's read-only observer.

The new launcher carries one 30-second `CLOCK_BOOTTIME` deadline from argument
parsing through the late handoff, protected recovery, activation and both
offers. Shorter phase limits cap that same deadline. Calculator transport and
effect preparation/admission likewise check their original total budget after
awaits and successful I/O; suspend or a late reply does not create more time.
A late effect acknowledgement remains unknown and cannot rearm dispatch.
These checks do not make synchronous blocking work preemptible. Owning
implementations and their verification commands are in
[the launcher contract](PRODUCTION_LAUNCHER.md).

The retained Root service is still a finite session, with the existing maximum
300,000 ms lifetime and application grants of at most 30,000 ms. The source now
includes an explicit Root administrative renewal of the same original issuer
lease: one fixed predecessor/postimage, revision plus one, original registry
CAS, then a newly opened original instance pinned to the returned revision.
Revoked or missing originals cannot be renewed or recreated. This is neither
an automatic renewal service nor an epoch reset.

Fresh v1 profiles require `previous_recovery` to be absent; explicit null is
rejected. Recovery v2 requires both exact previous targets, frozen helper
hashes, absolute helper/state paths and each application's typed exact/latest
selector. Root verifies the retained physical Current and replaces both exact
old policies with the actual new Session reservation in one original CAS.
Both applications then resolve against one complete, bounded original sender
cut with identical protected Current observations before and after the read.
An unselected old operation can be skipped only when the original writer has
persisted its validated target retirement ACK. The old helpers can observe and
acknowledge their selected operations, never dispatch a new effect. See
[the joint recovery contract](PRODUCTION_LAUNCHER.md#explicit-joint-recovery).

These source paths do not establish installed joint recovery qualification.
The same new product pair still needs the actual Notes/Calculator round trip,
two consecutive bounded successor cycles and post-revocation refusal. The
original 1,024-request/32-MiB retained-cut limits remain; no unlimited history,
automatic reclamation or cross-version database upgrade is qualified. New
application targets start with new document/state identity. Explicit Notes
text restoration retains its revision/digest checks; Calculator has no
automatic historical-state transfer. Old target results and new target state
must remain distinct. The original Notes-only recovery contract retains its
own meaning and cannot be applied by renaming a profile.

## Executed evidence and remaining gates

### Actual joint Rust execution

The four-package run used Hepta
26a46e3fe763b53e1f0362793701f112383a72fa, tree
2175f198948308c3a2f9d61f8282bc179669e798, with Rust 1.96.0
(ac68faa20c58cbccd01ee7208bf3b6e93a7d7f96). Each original command was
"just test -p PACKAGE --locked --offline --test-threads 1".
Job 1a1a397dd99-96a-7709 finished with exit 1, complete output, no job
timeout and unchanged clean source.

| Original package | Selected | First-attempt passes | Failed after original retry | Skipped | Command exit |
| --- | ---: | ---: | ---: | ---: | ---: |
| codex-hepta-objective | 66 | 66 | 0 | 2 | 0 |
| codex-hepta-memory | 400 | 399 | 1 | 13 | 100 |
| codex-hepta-agentd | 547 | 546 | 1 | 60 | 100 |
| codex-app-server | 1,331 | 1,315 | 16 | 2 | 100 |

The original nextest local profile and one retry were unchanged. Every failed
case failed both attempts; there were no flaky passes. Skipped cases were not
executed. Pipeline SHA256:
9e0c61045ffd1a44c6a977daa26bdb63f13a9d7e28343f94066ea0123b9330c1.
Complete App Server stderr SHA256 (404,859 bytes):
61c4167e207e2df0315a054efe30d544ed8d3c5b82995b57370699abab991161.

The 26a format check, Memory fix, Objective fix and explicit production Agentd
binary check passed with clean source. App Server fix passed on preceding
ffe82edb72e4d7edaf09402f1434a082f313f5fc; the later change before 26a was
only a Memory test. Agentd fix was repeated on the repair below. Passing
cases include Calculator original-owner payload/readback and typed retirement,
shared-turn fences, actual UnixStream/pidfd text budgets, and App Server's
three actual-child signal/ACK tests plus two drain tests. These are component
results, not installed joint Root or GUI qualification.

Memory's original federation test failed at cognitive_runtime_tests.rs:466
with zero completed peers instead of sixteen, twice. Its original two-second
budget and seventeen-store setup were unchanged; no unique failing peer or
stage is identified. Agentd's custody test failed the final takes_lock
assertion twice. Fourteen App Server cases lacked original cross-package
helpers: code-mode host 4, codex 4, test_stdio_server 6. The other two failures
remain independent: disconnect cleanup did not observe its own command exit
within the original deadline, and cold-resume worker metadata had a different
parent ThreadId. Core and the shared process library were not changed to
suppress these failures.

### Selected custody repair

Hepta 47b3335357c5607e2f09791fcb028ee1207a9cd7, tree
eab8c04e0bd441ee990356f3bf98c6f4d1e59eda, changes only the original custody
test's completion observation relative to 26a. Within the same one-second
deadline it waits for both Weak retirement and the same contender's actual
lock availability: Weak retirement is not a File destructor completion barrier.
Production custody and original inode, refusal and fencing assertions remain.

Job 1a1a3ce2d75-96a-7769 passed original Rust 1.96 format, Agentd fix and
the one selected custody case on that clean source. It passed on the first
attempt; 554 library cases were skipped. The full Agentd suite was not repeated
and its 26a red result remains. Repair pipeline SHA256:
67199fd3d335184f15addf3b11f2e3b384d9911eb075f6f8f800182d876b3559.
Selected stderr SHA256 (24,223 bytes):
bc37ce53eb9fec818ebc1cc3ce939d3b9b264ce984cc4bc627132bde0b64606d.

### Separate original seed component

Minimal App Server concern 857d8f61b96453c06a7f93dfba79dcdebca31bf8,
tree ed0824c48bb4133dcebbff6c1aa733f23f2e0f28, passed the original
Desktop seed fixture at 92a06c4b4b041a9e94d83480bc2c4cdcd6afa3d2,
tree 7eb3cff149daf8109ce823ff86cfa8827161dcae. Desktop Rust dependencies
remained a39; the fixture used the exact separately built App Server.
Job 1a1a3cb8614-96a-7761 recorded one pass, 27 filtered out, zero ignored,
in 20.721 seconds. Its durable observation bound the binary SHA, retained
the original ten-second child-shutdown limit, and observed socket retirement
and same-namespace mount detach. Overall create time is not that child limit.
Result SHA256:
f87224b2f64d7899bb02f9d72c1c743d4c44769f99cba7257b9cdd9815319f2b.

This was component-only, with production qualification false and no authority,
model turn, Notes request or application effect. The older failed seed receipt
is retained. Neither result qualifies a new installed product pair.

### Earlier checkpoints

The following execution belongs to candidate parent
`580a07bfadad97d1dfc13ece112facc13dcc00bb`, tree
`cd6004e85a5ae28513a0bcf32da5bf7b190103f5`:

| Actual scope | Recorded result |
| --- | --- |
| Original Objective suite | 66 passed, 2 skipped. |
| Selected causal-receipt regression | 1 passed, 407 not selected. |
| Selected Agentd profile tests | 6 passed, 587 not selected; job `1a1a2897174-96a-7411` completed. |
| Earlier Memory suite (separate 0259fc82cc1b6ac9e245227dceffb767e306378f source) | 393 passed, 1 original federation failure, 13 skipped; the unchanged targeted recheck also failed. That earlier discovery-budget assertion does not identify the cause of the later 26a peer-count mismatch. |

At that earlier checkpoint the newer Core adapter, shared-turn fence, callbacks,
Root factory and CLI had selected format/parser evidence. The actual joint
Cargo runs above supersede that limitation within their recorded scope.
The Desktop serialization
golden fixture and typed retirement tests are fixture evidence, not a real
Root grant, GUI effect or installed-product result. Frozen fd/a39 P0 build and
installation jobs do not qualify this successor.

Run owning tests through the repository entry point after freezing one coherent
Hepta commit and its matching Desktop dependencies:

```text
cd codex-rs
just test --locked -p codex-hepta-memory --lib production_calculator
just test --locked -p codex-hepta-memory --lib desktop_turn
just test --locked -p codex-hepta-memory --lib objective_sender_desktop
just test --locked -p codex-hepta-objective --lib desktop_thread
just test --locked -p codex-hepta-agentd --lib desktop
just test --locked -p codex-hepta-agentd --lib calculator
just test --locked -p codex-hepta-agentd --lib production_launcher
```

These are verification commands, not claimed results. The original Agentd
binary must also build because its manifest sets `test = false`. Full owning
package tests, lint and the original Root privilege checks remain separate
gates. Installed acceptance must then bind the exact pair and real human/Core
turn to an actual application effect, independent readback and the same
writer's durable typed terminal. Preserve unknown and failure receipts. A
local calculation, application launch, model fixture or component CI success
cannot replace that acceptance sequence.

## App Server cross-package helper preparation

The original [cargo-bin contract](../utils/cargo-bin/README.md) accepts
CARGO_BIN_EXE_* and NEXTEST_BIN_EXE_* metadata. Outside Bazel runfiles the
value must name an existing absolute path. It does not infer target paths or
fall back to PATH; nextest supplies binaries only to tests in the same package.
Therefore an App Server package run needs explicit preparation of the original
cross-package helpers. Changing metadata mode alone does not supply them.

| Owning package | Original binary | Per-test-process metadata key |
| --- | --- | --- |
| codex-cli | codex | CARGO_BIN_EXE_codex |
| codex-code-mode-host | codex-code-mode-host | CARGO_BIN_EXE_codex-code-mode-host |
| codex-rmcp-client | test_stdio_server | CARGO_BIN_EXE_test_stdio_server |

Use one exact clean Hepta checkout, its unchanged Cargo.lock, Rust 1.96,
default features and the same owned Cargo target/profile as the App Server
tests. Record source commit/tree and compiler identity. Never substitute an
unrelated installed executable or copy an older helper into that target.
The original code-mode runtime also needs the host in the same target/profile.

Run the original builds and retain their Cargo artifact records. Keep the
locked/offline requirements when resolving a missing cache prerequisite.

~~~sh
cd codex-rs
set -eu
validation_out="$(mktemp -d /tmp/hepta-app-server-helpers.XXXXXXXX)"
cargo build --locked --offline -p codex-cli --bin codex \
  --message-format=json > "$validation_out/codex.jsonl" \
  2> "$validation_out/codex.stderr"
cargo build --locked --offline -p codex-code-mode-host --bin codex-code-mode-host \
  --message-format=json > "$validation_out/codex-code-mode-host.jsonl" \
  2> "$validation_out/codex-code-mode-host.stderr"
cargo build --locked --offline -p codex-rmcp-client --bin test_stdio_server \
  --message-format=json > "$validation_out/test_stdio_server.jsonl" \
  2> "$validation_out/test_stdio_server.stderr"
~~~

Read executable paths from successful Cargo compiler-artifact messages. This
Python 3.11+ example verifies the owning source, records actual executable
hashes, and binds only these original keys for a separate fourteen-case run.
The original two other failures and the original full-package result remain
unchanged.

~~~sh
python3 - "$validation_out" <<'PY'
import hashlib, json, os, re, subprocess, sys
from pathlib import Path

out = Path(sys.argv[1])
root = Path.cwd().resolve()
owners = {
    "codex": root / "cli/src/main.rs",
    "codex-code-mode-host": root / "code-mode-host/src/main.rs",
    "test_stdio_server": root / "rmcp-client/src/bin/test_stdio_server.rs",
}
env = os.environ.copy()
receipts = []
for name, source in owners.items():
    paths, finished = set(), False
    for line in (out / (name + ".jsonl")).read_text().splitlines():
        event = json.loads(line)
        if event.get("reason") == "build-finished":
            finished = event.get("success") is True
        target = event.get("target", {})
        if (event.get("reason") == "compiler-artifact"
                and target.get("name") == name and "bin" in target.get("kind", [])
                and Path(target["src_path"]).resolve() == source.resolve()
                and event.get("executable")):
            paths.add(event["executable"])
    if not finished or len(paths) != 1:
        raise RuntimeError("missing or ambiguous original artifact: " + name)
    path = Path(paths.pop())
    if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
        raise RuntimeError("artifact is not an existing absolute executable")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    receipts.append({"binary": name, "path": str(path), "sha256": digest})
    env["CARGO_BIN_EXE_" + name] = str(path)
    env["CARGO_BIN_EXE_" + name.replace("-", "_")] = str(path)
with (out / "executables.json").open("x") as stream:
    json.dump(receipts, stream, indent=2)

selected = [
    "suite::v2::code_mode_host::app_server_shares_flag_selected_code_mode_host_across_threads",
    "suite::v2::code_mode_host::app_server_shares_flag_selected_grpc_code_mode_host_across_threads",
    "suite::v2::executor_mcp::guardian_review_does_not_discover_executor_mcp",
    "suite::v2::executor_mcp::legacy_executor_skips_required_browser_and_keeps_host_owned_mcp",
    "suite::v2::executor_mcp::selected_executor_discovers_browser_mcp_with_executor_only_bearer_token",
    "suite::v2::executor_mcp::selected_executor_plugin_exposes_its_mcps_only_to_that_thread",
    "suite::v2::imagegen_extension::standalone_image_generation_is_callable_from_code_mode_only",
    "suite::v2::mcp_server_status::mcp_server_status_list_reports_disconnected_stdio_transport",
    "suite::v2::mcp_server_status::mcp_server_status_list_waits_for_live_stdio_metadata_before_using_cached_tools",
    "suite::v2::plugin_install::plugin_install_makes_bundled_mcp_servers_available_to_followup_requests",
    "suite::v2::selected_capability_stack::selected_capabilities_become_available_between_samples_in_one_turn",
    "suite::v2::selected_capability_stack::selected_capability_stack_tracks_environment_availability_and_resume",
    "suite::v2::thread_start::thread_start_with_managed_read_only_does_not_trust_or_load_project_mcp",
    "suite::v2::turn_start::code_mode_exec_emits_correlated_production_analytics",
]
command = [
    "just", "test", "-p", "codex-app-server", "--test", "all",
    "--locked", "--offline", "--test-threads", "1", "-E",
    " | ".join("test(" + name + ")" for name in selected),
]
with (out / "selected.stdout").open("xb") as stdout, (out / "selected.stderr").open("xb") as stderr:
    result = subprocess.run(command, env=env, stdout=stdout, stderr=stderr, check=False)
if not re.search(r"Starting 14 tests across 1 binary", (out / "selected.stderr").read_text()):
    raise RuntimeError("expected fourteen original cases were not selected")
raise SystemExit(result.returncode)
PY
~~~

Preserve raw build/test output, artifact identities, exact selected names,
original retries and the clean source check. At this document's checkpoint
the fourteen-case follow-up has not completed; all sixteen original App Server
failures remain recorded. A later selected pass applies only to that selected
scope and exact source, not to the whole package or installed product.
