# Frozen-family source replay: read-only root-cause report

## Finding

The two frozen prospective research families currently lack a complete source
replay. Their current efficacy eligibility must remain **UNKNOWN**. The native
cause is `SUBMITTED_COMMAND_WITHOUT_FILL_OR_ZERO_FILL_PROOF`; the strict evaluator
currently summarizes this as `STRICT_SOURCE_REPLAY_INCOMPLETE`.

The authoritative journal was readable and complete as a file: 53,087,317 bytes,
47,513 committed events, no uncommitted tail. Replaying it with the existing,
hash-verified release reproduced the failure in about 0.90 seconds. This is not
evidence of a read timeout, a malformed trailing write, or a missing journal.

The bound command has one exact original request binding inside the frozen
input window. Producer ingress verification reported no issues. Its five
original events are:

1. `order_intent`
2. `place_send_attempt`
3. `broker_order_accepted`
4. `place_sent`
5. `broker_order_status`, with nonterminal status `PreSubmitted`

The native validator found zero fill points and no terminal status. A
`PreSubmitted` observation with zero cumulative quantity is not evidence of
zero-fill termination. The unchanged driver still holds this same command as
pending. A fresh native owner observation reports a connected, authoritative
event stream and an incomplete recovery barrier with reason
`IB_RECOVERY_AUDIT_PLACE_MUTATION`.

For isolation, the journal prefix preceding this command's first intent was
replayed independently. Its 47,508 events replayed successfully. This earlier prefix is diagnostic only: it was not
substituted for the current source, used to restore sample credit, or used to
remove the unresolved command from the denominator.

The two families have identical hashes for the native accounting, reward
assembly, and source-reader implementations. The shared source failure therefore
has a concrete common cause. Exact command/request identities, account-related
source material, host paths, and full logs are retained only on authorized hosts.

## Existing-proof search and recovery boundary

The original OMS journal, driver state, existing owner journal, and observability
journal were inspected without sending a new broker request. No additional
already-produced native fill or terminal proof for the bound command was found
in those sources. The observability journal's exact-identity search had no
matches; aggregate connectivity or zero-position observations cannot replace
the missing command-specific evidence.

Recovery requires original, subject-bound native evidence accepted by the
existing accounting validator: a fill plus its required settlement evidence,
or a terminal status proving zero fill. That evidence must retain the original
command identity, source provenance, and relevant native subject/epoch checks.
Once available, the original complete-source evaluation can be repeated under
the frozen protocol. The present read-only evidence does not establish that
such a record exists elsewhere or that the pending command will terminate.

No order was cancelled, retried, or submitted; no account operation, broker
query, service restart, ledger rewrite, freeze modification, or synthetic
zero-fill event was performed. The substantive evidence blocker remains open.

## Diagnostics-only patch

`native_replay_diagnostics.patch` adds one pure helper and replaces the generic
issue construction. It retains the existing
`reason=CURRENT_LEDGER_REPLAY_UNAVAILABLE` and adds `native_replay_reason` when
the underlying error is a bounded uppercase/underscore code. Arbitrary exception
text, paths, digits, and identifiers are not copied into the diagnostic field.
Missing or non-symbolic reasons receive fixed diagnostic placeholders.

The patch does not repair a pending command or restore efficacy credit. It was
tested only in an independent source copy and was **not deployed**.

`verify_native_replay_diagnostics.py` exercised eight cases, including the real
aggregate native failure report, complete replay, global source failure, absent
reason, and private/non-symbolic/oversized error text. It compared the original
and modified snapshot arguments after removing only the new diagnostic field,
verified identical strict and final failure routes, and checked that all other
module AST nodes are identical. Acceptance rules, denominator retention,
outcome construction, and `strict_source_unavailable` are unchanged.

Base evaluator SHA256:
`5395b81661b11db331f16557c405b5c7aab902c29e6d24574fc03ec63c752de4`.

Candidate evaluator SHA256:
`10d42dbb9d35a25873bc098a3e81b41fb25dd4ab73f3fec6674c1142f3efc98b`.

The aggregate evidence and verification results are supplied separately as
`source_replay_blocker_aggregate.json` and
`native_replay_diagnostics_verification.json`. Reproduction needs an authorized
copy of the matching original release, while the symbolic-error tests require
no private rows, weights, account records, or broker connection.
