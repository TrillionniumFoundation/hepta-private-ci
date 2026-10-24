# BFCL interface and grouping audit: interface gap, not a model score

## Custody and scope

Official Gorilla pin `6ea57973c7a6097fd7c5915698c54c17c5b1b6c8`, Apache2.0 LICENSE retained. `upstream-manifest.json` lists the three task files, eight API schema files and LICENSE (12 files, 1,299,406 bytes); `extra-source-manifest.json` lists three small source files read to resolve name discrepancies. All original bytes match upstream Git blobs. Scripts parse JSON/Python AST only; no third-party source was imported/executed, no model, task rollout, training, scoring, database mutation, external API or remote CI was run. Reproduce the initial manifest/schema/group inventory using `python audit.py`, then `python group_risks.py`.

## Verified variant linkage and leakage risks

The three categories each contain exactly200 records with integer suffix0–199. Each suffix joins one base, missing-function and missing-parameter record, producing200 groups rather than600 independent cases. All paired paths and involved_classes match. However, initial_config differs from base for7 missing-function and9 missing-parameter variants; every variant's question differs. Hence grouping must preserve lineage without assuming identical starting state. Base contains734 turn blocks and each augmented file934; these 2602 blocks are correlated sequences, not independent examples.

`groups.json` contains every ID join, per-field equality, state/question/path digests, original path and turn counts. Three pairs of different base IDs share exactly the same path:21/22,40/43,116/117. Initial-state hashes repeat for63/83,66/70/74,100/104/133. Conservatively merging these additional potential overlaps gives192 components. This is a leakage screen, not proof that repeated templates/states make tasks semantically identical. No train/cal/test split was assigned. Any future split must keep all base variants together and justify how these cross-base risks are handled. An entire API-family holdout is a domain-shift test, not iid calibration.

The four primary domains each have50 base groups. Companion APIs overlap domains. Taking file-system groups0–49 gives50 base groups/150 linked variants, not150 independent examples. Published 2024-era tasks are not a future-window acceptance test; unknown model pretraining or prior Hepta exposure remains possible.

## What may be exposed to a model

Fields must be routed through the original environment's visibility rules, not dumped as one feature string. `path` is construction/expected-call metadata and must not be a predictor input. `missed_function` describes staged tool unavailability/release and is evaluator/environment control, not an answer hint. `initial_config` is backend state: only the observation visible to the agent may be exposed, not hidden database/account state. Future turns and answer files must remain hidden until their legitimate turn. `excluded_function` must filter offered tools, not turn into an implicit correctness label. The schema audit does not establish a complete observer adapter; this is an integration prerequisite.

## Actual six-action expressibility criteria

The inspected Hepta local profile has six actions, four target slots, no parameter values, a192-token maximum and action-name postcondition labels. Inspected local source: cell-feature-snapshot-profile/baseline.py, SHA256 56f88a126c1e0e55cd1b17db81bdce9ab205d0f6ea1196f71144235cd8d38e4d. This audit is limited to that exact inspected profile, not all latest Hepta versions. A valid mapping must preserve action meaning, required arguments, target identity, visibility/authorization, state effect and checked postcondition. Name similarity alone fails that test.

- open_path: possible conceptual relation to reading a file, but BFCL cat takes a filename within current directory and returns contents. Need explicit path resolution, correct current-directory state and read-result postcondition; no exact mapping verified.
- navigate: possible relation to cd, but cannot stand for vehicle set_navigation or booking travel. Need the original directory target semantics and cwd postcondition.
- copy_text: cannot stand for cp/mv, file creation, delete, grep/sort/diff, account changes or a parameterized message; copying text and copying/mutating a file are different operations.
- notify: possible relation to send_message only after recipient, body, account/auth and delivery-result semantics are explicit. It cannot stand for arbitrary social posts, ticket creation or purchases merely because a notification follows them.
- request_evidence: may describe asking for truly unavailable required information; it is not execution of an absent tool, not automatic correct handling of a missing function, and not a substitute for refund/order/booking. Original dialogue/release policy must determine appropriate behavior.
- stop: control-flow termination is not successful completion. It cannot stand for logout, cancel_order, cancel_booking, close_ticket or resolve_ticket. Success requires the original evaluated outcome.

The audited paths reference76 distinct function names. `function-interface-inventory.json` records each, its required parameter schema/response schema when available, base-group frequency and expressibility status. Exact mapping is unverified for all76; only cat/cd/send_message have a narrowly marked analogy. The remaining73 have no identical operation in the inspected six-action profile. This is an interface statement, not a claim the system could never be extended.

Clearly non-mappable operation classes include file writes/moves/deletes and analysis operators; trading/funding/order management; travel booking/cancellation/payment/insurance/authentication; vehicle control and sensor queries; social posting/commenting; ticket lifecycle; and mathematical computation. These require genuine additional semantics/executors, not relabeling. Required parameters mean the current none-v1 parameter representation is insufficient even for the three analogies. Arbitrarily retaining four tools or truncating192 tokens would alter the task; measure full offered candidate sets/observation lengths only after an observer adapter exists.

## Pinned metadata inconsistency requiring resolution

Six names in task `path` annotations are absent both from same-pin function documentation and from AST method definitions in the corresponding source classes:

MessageAPI.view_messages_received; TradingBot.add_stock_to_watchlist; TradingBot.logout; TradingBot.make_transaction; TradingBot.update_market_status; TravelAPI.authenticate.

Some current methods have similar names (add_to_watchlist, trading_logout, authenticate_travel), but no alias has been assumed. Expected paths are not necessarily executed ground-truth trajectories; answer files and checker routing were not read, so this does NOT establish that the official evaluator is broken or a task unsolvable. It does establish that direct path-to-action label generation would silently create invalid names. Before integration, trace official actual tool inventory/ground-truth handling for these cases or exclude affected cases under a predeclared, documented rule, never using eventual model scores.

## Minimal next engineering work and stopping boundary

1. Pin the intended current Hepta profile and define the observation/permission boundary.
2. Build a schema-preserving sandbox adapter for at most the file-system/clarification domain, retaining native BFCL function names, arguments and visibility; do not claim a six-action mapping until validated.
3. Resolve annotated-path/schema discrepancies and stage tools exactly as the official checker does; preserve base group lineage and changed initial states.
4. Only then freeze a new group-wise development/calibration/audit protocol with sufficient independent groups. The50 file-system families are a small semantic study, not enough for the earlier200-candidate risk-control ambition.

This audit supplies reusable schema/grouping evidence, not new task labels, training data qualification, or production-risk proof. Real Hepta decision traces and independently labeled future-window states/permissions/outcomes are still needed.
