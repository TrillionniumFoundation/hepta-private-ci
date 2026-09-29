# prompt.registry architecture and evidence diagrams

These diagrams describe the committed source boundaries. They do not claim
activation, independent acceptance, release, secure erasure, or cancellation of
bytes already observed outside the fenced host.

## Governed final-use sequence

```mermaid
sequenceDiagram
    participant R as PromptRegistry
    participant C as Compiler
    participant S as Durable stage owner
    participant D as Dispatch fence
    participant P as Provider transport
    participant O as Output fence
    R->>C: exact snapshot + selected payloads
    C->>S: immutable compilation/lease identity
    S->>D: validate current owner + durable claim
    D->>P: attempt/request digest + fence token
    P->>O: provider chunks tagged with attempt/fence
    O->>O: validate fence before each observable batch
    O-->>S: terminal or indeterminate observation fact
```

## Atomic publication and reopen

```mermaid
flowchart TD
    A[Validate predecessor and candidate] --> B[Write and fsync payload extent]
    B --> C[Write and fsync registry.next]
    C --> D[Atomic metadata rename]
    D --> E[Directory fsync]
    C -->|failure before rename| F[Predecessor remains authoritative]
    D -->|unknown after rename| G[Poison owner: ReopenRequired]
    G --> H[Reopen and validate selected image]
    H --> I[Reconcile committed or predecessor outcome]
```

## V4/V5 payload-bank handoff

```mermaid
flowchart LR
    V4[V4 semantic image] --> A[Selected payload bank]
    A --> G[Build alternate V5 bank]
    G --> M[Publish metadata selecting alternate]
    M --> F[Directory fsync]
    F --> C[Clean predecessor only after selected image validates]
```

## Qualification traceability

| Operation/evidence | Source | Tests | Qualification lane | Immutable output |
| --- | --- | --- | --- | --- |
| Registry lifecycle and durable GC | `hepta-prompt-registry` | registry unit/integration and operational profiles | core exact-head + base-merge | per-lane receipt, logs and source blobs |
| Agentd stage/current-use/dispatch | `hepta-agentd` | prompt inventory, regressions and pipeline profile | product exact-head + base-merge | per-lane receipt, logs and measurements |
| Extension cached reuse | `ext/hepta-prompt` | cached withdrawal and payload-equivalence regressions | product exact-head + base-merge | product lane receipt |
| Four-lane identity equality | aggregate verifier | Python harness and receipt digest checks | aggregate gate | qualification summary v2 |
| Independent acceptance | protected acceptance workflow | acceptance verifier | separate environment-approved run | independent acceptance v1 |
