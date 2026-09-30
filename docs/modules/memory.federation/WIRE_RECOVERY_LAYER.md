# memory.federation durable host and client recovery layer

This stacked delivery adds restart-surviving state and a read-only host/client boundary to the authenticated protocol core.

## Included

- canonical, integrity-bound durable replay and attempt snapshots;
- global and per-peer capacity isolation, bounded expiry cleanup, and clock high-water marks;
- outbound client query/cancel persistence and exact response correlation;
- staged inbound replay plus recovery commit so persistence failure remains retryable;
- two-stage authenticated host admission and terminal completion;
- cancellation fences that survive restart and reject late terminal success;
- handler-supplied owner-cut validation;
- Unix single-writer atomic snapshot backend with lock, same-directory rename, file and directory fsync, and indeterminate-state poisoning;
- recovery, process-failure, cancellation, replay, frontier, and host atomicity tests.

## Excluded

This layer does not encode canonical V2 federation bodies, select a mutually authenticated network transport, own deployment secrets, compose Agentd serving, qualify two independent real hosts, or claim activation, promotion, or release.
