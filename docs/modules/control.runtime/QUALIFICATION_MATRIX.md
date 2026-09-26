# control.runtime exact-head qualification matrix

This file is an auditable trigger and scope declaration for the production-closure qualification branch. It does not claim activation or release.

Every qualifying candidate must bind one exact source SHA and record both the checked-out tree and the effective synthetic-merge tree. The following checks are required on that candidate:

- source-head regression;
- synthetic-merge regression;
- control NDU caller regression;
- strict Clippy with warnings denied;
- repository formatting check;
- control-plane, protocol, and Agentd cognitive-context package tests;
- named-host NDU qualification with a retained receipt.

A generated source commit is not qualified by an earlier bootstrap run. Qualification evidence is valid only when its declared source SHA equals the candidate branch head under review.

The maturity truth source must keep the following distinctions explicit until separately evidenced:

- read-only Agentd caller: `source_composed_candidate`;
- global planner caller: `not_composed`;
- durable production writer composition: `not_composed`;
- planner, organ-host framework, and embodiment reference: separate maturity dimensions;
- activation, canary, independent acceptance, rollback rehearsal, and release: false unless backed by retained receipts.
