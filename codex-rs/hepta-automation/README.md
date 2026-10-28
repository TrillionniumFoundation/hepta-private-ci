# Automation: technical and development guide

`codex-hepta-automation` owns per-Agent durable schedules, occurrences and
TaskFlow records. The existing Core queue owns turn execution; registered effect
owners and trusted terminal observers own external outcomes. Baseline: `7673ea62`.

## Technical contract

| Entry point | Owner contract |
| --- | --- |
| `AutomationStore::open` | Open `automation_1.sqlite3` beneath the Agent's automation layout; reconcile known migration history, apply embedded migrations, then verify schema/owner/timer epoch. [store.rs:27](src/store.rs#L27), [40](src/store.rs#L40). |
| `AutomationScheduler<Q>::tick` | Claim/materialize at most one occurrence; persist TaskFlow and uncertain dispatch intent before calling `AutomationTurnQueue`. [scheduler.rs:77](src/scheduler.rs#L77). |
| `AutomationTurnQueue` | Existing Agent App Server queue admission with stable client ID/canonical payload. Adapters must report `DispatchUnknown` after possible admission; only proven pre-admission failures may be retried. [scheduler.rs:18](src/scheduler.rs#L18). |
| Occurrence / step APIs | Bind schedule revision, scheduled instant, run/step/attempt, fence, command IDs and observed receipts in durable state. [lifecycle.rs:312](src/lifecycle.rs#L312), [taskflow_step.rs:209](src/taskflow_step.rs#L209). |
| Authorized effects | Intent/final-use binding, durable pending state, registered provider adapter and explicit reconciliation. No arbitrary effect closure is authorized by a timer tick. [authorized_effect.rs:62](src/authorized_effect.rs#L62), [292](src/authorized_effect.rs#L292). |
| Local execution assessment | Validated TaskFlow requests return typed unavailable reasons for missing effect owner or trusted terminal observer. They do not execute. [taskflow_execution_boundary.rs:203](src/taskflow_execution_boundary.rs#L203). |

Task state is enabled, disabled, cancelled or completed ([model.rs:79](src/model.rs#L79)).
Occurrences additionally retain admission, turn and terminal observations.
`AutomationTick::Submitted` preserves the v1 public spelling but means durable
Core queue admission only. A dropped response, timeout or possible provider
contact stays uncertain/indeterminate and must be reconciled using the same
durable identity; reopening is not permission to redispatch
([scheduler.rs:103](src/scheduler.rs#L103), [dispatch_recovery.rs](src/dispatch_recovery.rs)).

The timer lifecycle is `Active` → `Draining` → `Retired`. Handoff requires
draining with no leased occurrences or uncertain dispatches; pending work can be
retained. Epoch fencing prevents predecessor mutation after handoff. These APIs
require the trusted host's existing writer lock and management authorization
([timer_lifecycle.rs:1](src/timer_lifecycle.rs#L1), [can_handoff:43](src/timer_lifecycle.rs#L43)).

| Failure/resource boundary | Behavior |
| --- | --- |
| Open / migration | Wrong owner, corrupt schema/epoch, unknown or dirty migration history fail; historical checksums must not be rewritten. [store.rs:40](src/store.rs#L40). |
| Tick budget | Nonzero generation/lease/timeout; dispatch timeout must be shorter than the lease. One tick does not scan an unbounded work batch. [scheduler.rs:45](src/scheduler.rs#L45). |
| Enumeration | Task pages cap at 1,024. [store.rs:28](src/store.rs#L28). |
| Local TaskFlow envelope | At most 127 predecessors and 64 KiB encoded input, with typed unavailable assessment. [taskflow_execution_boundary.rs:24](src/taskflow_execution_boundary.rs#L24). |
| Effect/step receipt | An observed digest is not proof a provider accepted an effect; actual final-use authority and provider/terminal evidence remain separate. [taskflow_step.rs:108](src/taskflow_step.rs#L108). |

`taskflow-structural-qualification` is opt-in with empty default features
([Cargo.toml](Cargo.toml)); it exposes structural helpers, not production authority.
Default durable step outbox flags explicitly keep effects, production caller and
scheduler authority false ([taskflow_step.rs:39](src/taskflow_step.rs#L39)).
The legacy `effect_executor` module is test-only ([lib.rs:9](src/lib.rs#L9)).

## Development and verification

Start at `src/lib.rs` exports, then the owning state machine above. Schema version
is 19; migrations are in [migrations](migrations). Preserve occurrence/attempt
identity, append-only receipts and original migration checksums when changing
recovery. Calendar timezone/DST policy belongs in [schedule_v2.rs](src/schedule_v2.rs),
not an independent timer or model scheduler.

From repository root, use the original package command and host flags with an
external `CARGO_TARGET_DIR`; this is narrower than the complete 19-owner gate:

```sh
RUSTUP_TOOLCHAIN=1.95.0 CARGO_BUILD_JOBS=2 CARGO_INCREMENTAL=0 \
  just test --locked --offline -p codex-hepta-automation \
  --test-threads 2 --retries 0 --cargo-profile dev-small
```

Exact existing binary/test IDs to inspect:

- `codex-hepta-automation::automation` / `crash_after_external_acceptance_keeps_unknown_intent_across_reopen` — [automation.rs:543](tests/automation.rs#L543).
- `codex-hepta-automation::automation` / `uncertain_dispatch_requires_explicit_negative_provider_proof_before_retry` — [automation.rs:854](tests/automation.rs#L854).
- `codex-hepta-automation::authorized_effect` / `indeterminate_effect_reopens_without_redispatch_then_reconciles_terminally` — [authorized_effect.rs:916](tests/authorized_effect.rs#L916).
- `codex-hepta-automation::operation_timer_fence` / `predecessor_kernel_destination_cannot_write_after_timer_handoff` — [operation_timer_fence.rs:95](tests/operation_timer_fence.rs#L95).

Tests use temporary per-Agent databases and controlled queue/provider/clock
fixtures. They do not configure a production grant provider, protected clock,
revocation service, recovered writer or physical device. No Rust command ran
for these docs, and this new source tuple inherits no earlier runtime results.
