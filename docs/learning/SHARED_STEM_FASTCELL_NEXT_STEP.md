# Shared Stem / FastCell next-step execution contract

Status: `DRAFT` · `SHADOW_ONLY` · `DENY_ALL`

This document binds the next research sequence to the existing Stem and MemoryCell evidence owners. It does not select a production Stem, grant NDU authority, enable automatic Cell split, change the Neuron V1 wire format, or replace the production MCP/tool-call control plane.

## Ordered gates

1. **E1 same-cohort Stem triad.** Complete #2072 for Granite R2 97M, mmBERT-small 140M, and ModernBERT-base 149M on the same source-disjoint panel, tokenizer policy, pooling/width ABI, Head schedule, and resource ledger. Report descriptive paired wins, Brier, calibration, Encoder forwards, CPU/GPU time, RSS, and serving p50/p95/p99. A queued, skipped, metadata-only, or synthetic job is not a physical result.
2. **E2 real multimodal utility.** Extend #1885 through the existing #2136/#2146/#2149 evidence boundary. Require real text, image, audio, and video sources, source-disjoint future windows, modality deletion/swap counterfactuals, independent labels, and a text-only control. The result must report rescued and harmed tasks, retention, negative transfer, and modality-specific cost.
3. **Equal-budget differentiation.** Compare shared Stem plus typed lightweight Heads against an unsplit Head bank with the same total trainable parameters, optimizer bytes, updates, Reader calls, and data exposure. Do not count row-level proxy accuracy as complete-task success.
4. **Sparse NDU controller.** NDU may propose candidate split, promotion, or rollback decisions only after three real future windows and independent evaluation. NDU is a candidate generator; deterministic authority, CAS, revocation, final-use, and effect reconciliation remain outside the learned Cell.
5. **FastCell pilot.** FastCell emits typed ActionIR only. The pilot supports validation and receipt generation, not external effects. Compilation is allowed only from an allowlisted IR template, with content digest, generation binding, resource bound, and explicit `DENY_ALL`.
6. **Promotion boundary.** Keep all outputs Draft/Shadow/Deny. Production selection requires exact-head blocking-ci, independent evidence, target-host measurements, restart/revocation tests, and the existing production gates.

## Stem and Cell accounting

Shared tensors count once as parameters and once per actual invocation as computation. A Cell ledger must include Head and Adapter tensors, optimizer state, activation memory, Encoder cache bytes, queueing, and cold-load cost. Physical sharing is accepted only when the runtime observes one immutable producer snapshot and bounded borrower reads.

A Stem score is a Pareto record, not a single accuracy winner:

`quality, transfer, retention, negative_transfer, p95, p99, RSS, train_cost, provenance, rollback_cost`.

## FastCell safety contract

A Cell may propose an ActionIR with a bounded operation, typed arguments, capability scope, and expected output schema. It may not emit native bytes, raw pointers, syscalls, credentials, arbitrary paths, or GPU launch parameters. The host must validate the ActionIR, bind the final payload, and record the decision before any future executor is considered.

A later executor implementation must use a signed, content-addressed artifact produced from the allowlisted IR. W^X, sandboxing, revocation, timeout, memory and device budgets, independent verification, and durable terminal receipts are mandatory. This branch contains no executor and no production activation.

## Stop conditions

Stop and retain DENY_ALL on any source/cohort drift, incomplete modality evidence, hidden label access, false host attestation, missing independent evaluator, negative-transfer regression, unbounded resource use, stale capability, digest mismatch, or attempt to convert a research receipt into authority.
