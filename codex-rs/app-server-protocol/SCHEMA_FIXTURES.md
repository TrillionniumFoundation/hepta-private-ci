# Protocol schema fixtures

Rust protocol definitions and their serialization/experimental annotations own
the wire shape. Review their generated TypeScript, JSON schema and precomputed
exports together when changing an API or persisted rollout event.

From `codex-rs`, run both original generators:

```sh
just write-app-server-schema
just write-app-server-schema --experimental
just test -p codex-app-server-protocol
```

The stable generator refreshes `schema/typescript`, `schema/json`, and
`schema/precomputed/app-server-exports-stable.json.zst`. The experimental command
refreshes the corresponding experimental cache. The compressed caches contain
complete source maps for public exports and the internal rollout schema; compare
their decoded contents during review. Keep the generator and fixture equality
tests enabled.

The recovery fixture refresh adds the existing `completed` subagent activity to
`TurnRecoverResponse.json`. It also brings the stable cache into agreement with
already tracked `turn/recover`, queue reconciliation and Hepta historical-evidence
types, and with persisted turn-recovery provenance in the internal rollout
schema. Review additions to both request unions and internal event variants.
The Rust implementations, annotations, recovery admission and replay rules stay
at their existing source definitions in this refresh.

The owning suite checks freshly generated JSON and TypeScript against all
fixtures, checks the stable and experimental precomputed maps, and checks the
internal schema. Commit every changed generated artifact from both commands.
An export-cache refresh requires its own build and consumer verification when
it joins an integrated release; a successful generator invocation alone does
not qualify a new Desktop/Hepta source pair.
