# `@hepta/control-ui`

Authority-free runtime-control client core and framework-free browser console shell.

The package may project coherent runtime state and submit authenticated requests. It does not own runtime state, grant authority, or infer terminal success from a local acknowledgement. The durable server operation ledger and runtime owner remain authoritative.

## Stable imports

```js
import {
  RuntimeClient,
  SameOriginHttpTransport,
  SessionProvider,
  createControlConsole,
} from "@hepta/control-ui";
```

Supported subpaths are `@hepta/control-ui/core`, `@hepta/control-ui/browser`, and `@hepta/control-ui/transport/http`. Imports from `src/*` are intentionally blocked.

## Repository checks

```bash
npm run lint --prefix apps/hepta-control-ui
npm test --prefix apps/hepta-control-ui
npm run test:contract --prefix apps/hepta-control-ui
npm run build --prefix apps/hepta-control-ui
npm run test:e2e --prefix apps/hepta-control-ui
```

The browser E2E suite runs Chromium, Firefox, WebKit, keyboard/focus scenarios, duplicate activation, stale revision, accepted-response-loss recovery, and axe-core.

## Security and operations

- [`TECHNICAL.md`](../../docs/modules/ui.control/TECHNICAL.md)
- [`THREAT_MODEL.md`](../../docs/modules/ui.control/THREAT_MODEL.md)
- [`SERVER_IDEMPOTENCY.md`](../../docs/modules/ui.control/SERVER_IDEMPOTENCY.md)
- [`OPERATIONS.md`](../../docs/modules/ui.control/OPERATIONS.md)

`projectRuntimeFromLocalCanonicalJson` and `buildLocalOperationProposalFromCanonicalJson` remain strict local qualification helpers. They are not production configuration loaders and accept only exact bounded canonical JSON.
