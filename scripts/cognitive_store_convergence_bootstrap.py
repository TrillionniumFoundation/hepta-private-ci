#!/usr/bin/env python3
"""Apply the reviewed cognitive.store convergence as one deterministic source edit.

This bootstrap is intentionally removed by its own result commit.  It exists only
because the connected GitHub API exposes whole-file replacement rather than a
repository checkout.  The resulting source, tests, workflows and documentation
are ordinary tracked files and are independently verified after this script is
removed.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text.rstrip() + "\n", encoding="utf-8")


def replace(path: str, old: str, new: str, *, count: int = 1) -> None:
    text = read(path)
    actual = text.count(old)
    if actual != count:
        raise SystemExit(f"{path}: expected {count} occurrence(s), found {actual}: {old!r}")
    write(path, text.replace(old, new, count))


def remove(path: str) -> None:
    target = ROOT / path
    if not target.exists():
        raise SystemExit(f"missing expected path: {path}")
    target.unlink()


# ---------------------------------------------------------------------------
# Phase 1/2: one product writer facade and a read-only serving capability.
# ---------------------------------------------------------------------------

remove("codex-rs/hepta-cognitive-store/src/production.rs")
remove("codex-rs/hepta-cognitive-store/src/production_tests.rs")

write(
    "codex-rs/hepta-cognitive-store/src/durable.rs",
    r'''//! Canonical cognitive-store boundaries over the single durable SQLite owner.
//!
//! `hepta-memory::CognitiveStore` remains the physical database owner.  Product
//! serving code receives [`DurableCognitiveReadStore`], which exposes only
//! bounded read/revalidation operations.  The raw backend and writer types are
//! compatibility/owner implementation details; the architecture gate permits
//! their use only inside the physical owner, the unique Agentd production host,
//! and explicit qualification code.

use std::fmt;
use std::sync::Arc;

pub const DURABLE_BACKEND_ID: &str = "hepta-memory::CognitiveStore";
pub const DURABLE_DATABASE_BASENAME: &str = "cognitive_1.sqlite3";
pub const DURABLE_SINGLE_WRITER: bool = true;

pub use codex_hepta_memory::CognitiveAccess;
pub use codex_hepta_memory::CognitiveRecoveryAnchor;
pub use codex_hepta_memory::CognitiveRecoveryError;
pub use codex_hepta_memory::CognitiveRecoveryRequirement;
pub use codex_hepta_memory::CognitiveScope;
pub use codex_hepta_memory::CognitiveStoreError as DurableCognitiveStoreError;
pub use codex_hepta_memory::CognitiveWriteReceipt;
pub use codex_hepta_memory::DurableCognitiveSnapshot;
pub use codex_hepta_memory::DurableCognitiveSnapshotCursor;
pub use codex_hepta_memory::DurableCognitiveSnapshotPage;
pub use codex_hepta_memory::ForgetMemoryDraft;
pub use codex_hepta_memory::KgFactSetDraft;
pub use codex_hepta_memory::LedgerSourceKind;
pub use codex_hepta_memory::MAX_LANE_C_PAGE_ANCESTRY_REVISIONS;
pub use codex_hepta_memory::MAX_LANE_C_PAGE_CITATIONS;
pub use codex_hepta_memory::MAX_LANE_C_SNAPSHOT_PAGE_HEADS;
pub use codex_hepta_memory::MemoryDraft;
pub use codex_hepta_memory::MemoryLifecycleState;
pub use codex_hepta_memory::MemoryRevisionDraft;
pub use codex_hepta_memory::MemoryVerification;
pub use codex_hepta_memory::PRODUCTION_COGNITIVE_MUTATION_NAMESPACE;
pub use codex_hepta_memory::PRODUCTION_COGNITIVE_MUTATION_SCHEMA_VERSION;
pub use codex_hepta_memory::ProductionAuthorityLease;
pub use codex_hepta_memory::ProductionAuthorityToken;
pub use codex_hepta_memory::ProductionAuthorityVerifier;
pub use codex_hepta_memory::ProductionCognitiveMutation;
pub use codex_hepta_memory::ProductionCognitiveMutationCapability;
pub use codex_hepta_memory::ProductionCognitiveMutationError;
pub use codex_hepta_memory::ProductionCognitiveMutationFuture;
pub use codex_hepta_memory::ProductionCognitiveMutationReceiptV1;
pub use codex_hepta_memory::ProductionDispatchFuture;
pub use codex_hepta_memory::ProductionDispatchReceipt;
pub use codex_hepta_memory::ProductionDispatchRequest;
pub use codex_hepta_memory::ProductionFinalUseOutboxDispatcher;
pub use codex_hepta_memory::ProductionOutboxTarget;
pub use codex_hepta_memory::ProductionQueuedReceipt;
pub use codex_hepta_memory::ProductionWriterError;
pub use codex_hepta_memory::RecoveredCognitiveReadOnly;
pub use codex_hepta_memory::SourceDraft;
pub use codex_hepta_memory::StableMemoryId;

/// Raw physical owner compatibility alias.
///
/// Product serving code must use [`DurableCognitiveReadStore`].  The repository
/// architecture check rejects new non-test uses of this alias outside the
/// physical owner bootstrap and `AgentdProductionWriterHost`.
#[doc(hidden)]
pub use codex_hepta_memory::CognitiveStore as DurableCognitiveStore;

/// Low-level durable writer compatibility alias.
///
/// The default Agentd build does not expose its writer accessor outside the
/// crate.  Qualification builds opt in explicitly.
#[doc(hidden)]
pub use codex_hepta_memory::ProductionDurableWriter;

/// Read-only product capability for one exact durable cognitive owner.
///
/// This wrapper has no mutation, source-append, lease-creation, migration or
/// raw-backend escape method.  It can only be constructed from the already
/// composed `CognitiveRuntime`, so normal serving code cannot open a second
/// writer or bypass recovery/authority composition.
#[derive(Clone)]
pub struct DurableCognitiveReadStore {
    backend: Arc<codex_hepta_memory::CognitiveStore>,
}

impl fmt::Debug for DurableCognitiveReadStore {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("DurableCognitiveReadStore")
            .field("owner_agent_id", self.backend.owner_agent_id())
            .finish_non_exhaustive()
    }
}

impl DurableCognitiveReadStore {
    /// Derive a read-only capability from a host-composed runtime.  No file is
    /// opened and no authority is manufactured here.
    pub fn from_runtime(runtime: &codex_hepta_memory::CognitiveRuntime) -> Option<Self> {
        runtime.available_store().map(|backend| Self {
            backend: Arc::clone(backend),
        })
    }

    pub fn owner_agent_id(&self) -> &codex_hepta_contracts::AgentId {
        self.backend.owner_agent_id()
    }

    pub async fn lane_c_snapshot(
        &self,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        now_unix_seconds: i64,
    ) -> Result<DurableCognitiveSnapshot, DurableCognitiveStoreError> {
        self.backend
            .lane_c_snapshot(access, scope, now_unix_seconds)
            .await
    }

    pub async fn observe_memory_retrieval(
        &self,
        access: &CognitiveAccess,
        request: &codex_hepta_memory::RetrievalRequest,
    ) -> Result<codex_hepta_memory::CognitiveRetrievalObservationV1, DurableCognitiveStoreError>
    {
        self.backend.observe_memory_retrieval(access, request).await
    }

    pub async fn revalidate_memory_candidates(
        &self,
        access: &CognitiveAccess,
        bindings: &[codex_hepta_memory::MemoryRevalidationBinding],
        now_unix_seconds: i64,
    ) -> Result<Vec<codex_hepta_memory::RevalidationStatus>, DurableCognitiveStoreError> {
        self.backend
            .revalidate_memory_candidates(access, bindings, now_unix_seconds)
            .await
    }

    pub async fn revalidate_lane_c_snapshot(
        &self,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        expected: &DurableCognitiveSnapshot,
        now_unix_seconds: i64,
    ) -> Result<DurableCognitiveSnapshot, DurableCognitiveStoreError> {
        self.backend
            .revalidate_lane_c_snapshot(access, scope, expected, now_unix_seconds)
            .await
    }
}''',
)

replace(
    "codex-rs/hepta-cognitive-store/Cargo.toml",
    "[dependencies]\ncodex-hepta-types = { path = \"../hepta-types\" }",
    "[dependencies]\ncodex-hepta-contracts = { workspace = true }\ncodex-hepta-types = { path = \"../hepta-types\" }",
)
replace(
    "codex-rs/hepta-cognitive-store/src/lib.rs",
    "pub use durable::DurableCognitiveSnapshotPage;",
    "pub use durable::DurableCognitiveSnapshotPage;\npub use durable::DurableCognitiveReadStore;",
)

replace(
    "codex-rs/hepta-agentd/src/state.rs",
    "use codex_hepta_cognitive_store::DurableCognitiveStore as CognitiveStore;",
    "use codex_hepta_cognitive_store::DurableCognitiveReadStore as CognitiveStore;\n#[cfg(test)]\nuse codex_hepta_cognitive_store::DurableCognitiveStore as RawCognitiveStore;\nuse codex_hepta_memory::CognitiveRuntime;",
)
replace(
    "codex-rs/hepta-agentd/src/state.rs",
    '''    pub(crate) fn attach_cognitive_store(
        &self,
        store: Arc<CognitiveStore>,
    ) -> Result<(), AgentdError> {
        if store.owner_agent_id() != &self.identity.agent_id {
            return Err(AgentdError::GenerationFenced(
                "cognitive store owner does not match agentd identity".to_string(),
            ));
        }
        let mut cognitive = self.cognitive.lock().map_err(poisoned_state)?;
        if cognitive.is_some() {
            return Err(AgentdError::Protocol(
                "cognitive store was attached more than once".to_string(),
            ));
        }
        *cognitive = Some(store);
        Ok(())
    }
''',
    '''    /// Attach only the read capability derived from the already composed
    /// runtime.  The state object never retains a raw mutable store handle.
    pub(crate) fn attach_cognitive_runtime(
        &self,
        runtime: &CognitiveRuntime,
    ) -> Result<(), AgentdError> {
        let Some(store) = CognitiveStore::from_runtime(runtime) else {
            return Ok(());
        };
        if store.owner_agent_id() != &self.identity.agent_id {
            return Err(AgentdError::GenerationFenced(
                "cognitive store owner does not match agentd identity".to_string(),
            ));
        }
        let mut cognitive = self.cognitive.lock().map_err(poisoned_state)?;
        if cognitive.is_some() {
            return Err(AgentdError::Protocol(
                "cognitive store was attached more than once".to_string(),
            ));
        }
        *cognitive = Some(Arc::new(store));
        Ok(())
    }

    /// Unit-test-only adapter for legacy fixtures.  Product code cannot call
    /// this method because it is absent from non-test builds.
    #[cfg(test)]
    pub(crate) fn attach_cognitive_store(
        &self,
        store: Arc<RawCognitiveStore>,
    ) -> Result<(), AgentdError> {
        self.attach_cognitive_runtime(&CognitiveRuntime::Available(store))
    }
''',
)
replace(
    "codex-rs/hepta-agentd/src/runtime.rs",
    '''    if let Some(store) = cognitive_runtime.available_store() {
        state.attach_cognitive_store(Arc::clone(store))?;
    }''',
    '''    state.attach_cognitive_runtime(&cognitive_runtime)?;''',
)
replace(
    "codex-rs/hepta-agentd/src/cognitive_context.rs",
    "use codex_hepta_cognitive_store::DurableCognitiveStore as CognitiveStore;",
    "use codex_hepta_cognitive_store::DurableCognitiveReadStore as CognitiveStore;",
)

# The unique product facade owns the externally verified mutation capability.
replace(
    "codex-rs/hepta-agentd/src/production_writer_host.rs",
    "//! Explicit Agentd/host seam for the production durable writer.",
    "//! Unique canonical Agentd production facade for cognitive durable writes.",
)
replace(
    "codex-rs/hepta-agentd/src/production_writer_host.rs",
    "    pub fn production_mutation(&self) -> Option<Arc<dyn ProductionCognitiveMutation>> {",
    "    pub(crate) fn production_mutation(&self) -> Option<Arc<dyn ProductionCognitiveMutation>> {",
)
replace(
    "codex-rs/hepta-agentd/src/production_writer_host.rs",
    '''    pub fn writer(&self) -> Arc<ProductionDurableWriter> {
        Arc::clone(&self.writer)
    }
''',
    '''    /// Qualification-only raw writer inspection.  Default product builds
    /// keep this accessor crate-private, so external callers can mutate only
    /// through the verified facade methods above.
    #[cfg(feature = "qualification-cognitive-write")]
    pub fn writer(&self) -> Arc<ProductionDurableWriter> {
        Arc::clone(&self.writer)
    }

    #[cfg(not(feature = "qualification-cognitive-write"))]
    pub(crate) fn writer(&self) -> Arc<ProductionDurableWriter> {
        Arc::clone(&self.writer)
    }

    pub(crate) fn owner_agent_id(&self) -> &codex_hepta_contracts::AgentId {
        self.writer.owner_agent_id()
    }

    pub(crate) fn writer_generation(&self) -> u64 {
        self.writer.generation()
    }

    pub(crate) fn authority(&self) -> &ProductionAuthorityLease {
        self.writer.authority()
    }
''',
)
replace(
    "codex-rs/hepta-agentd/src/config.rs",
    '''        let writer = host.writer();
        if writer.owner_agent_id() != &self.identity.agent_id {
            return Err(AgentdError::GenerationFenced(
                "production cognitive writer owner does not match Agentd identity".to_string(),
            ));
        }
        if writer.generation() != self.identity.spawn_generation {
            return Err(AgentdError::GenerationFenced(format!(
                "production cognitive writer generation {} does not match Agentd spawn generation {}",
                writer.generation(),
                self.identity.spawn_generation
            )));
        }''',
    '''        if host.owner_agent_id() != &self.identity.agent_id {
            return Err(AgentdError::GenerationFenced(
                "production cognitive writer owner does not match Agentd identity".to_string(),
            ));
        }
        if host.writer_generation() != self.identity.spawn_generation {
            return Err(AgentdError::GenerationFenced(format!(
                "production cognitive writer generation {} does not match Agentd spawn generation {}",
                host.writer_generation(),
                self.identity.spawn_generation
            )));
        }''',
)
replace(
    "codex-rs/hepta-agentd/src/state.rs",
    "        if host.writer().authority().agent_id != self.identity.agent_id {",
    "        if host.authority().agent_id != self.identity.agent_id {",
)
replace(
    "codex-rs/hepta-agentd/tests/cognitive_store_product_writer.rs",
    "#![cfg(unix)]",
    "#![cfg(unix)]\n#![cfg(feature = \"qualification-cognitive-write\")]",
)

# ---------------------------------------------------------------------------
# Build-time architecture policy and qualification receipt aggregation.
# ---------------------------------------------------------------------------

write(
    "docs/modules/cognitive.store/ARCHITECTURE_BOUNDARY.json",
    json.dumps(
        {
            "schema": "hepta.cognitive-store-architecture-boundary.v1",
            "canonicalProductWriteFacade": {
                "path": "codex-rs/hepta-agentd/src/production_writer_host.rs",
                "symbol": "AgentdProductionWriterHost",
            },
            "rawBackendAllowedNonTestPaths": [
                "codex-rs/hepta-cognitive-store/src/durable.rs",
                "codex-rs/hepta-agentd/src/runtime.rs",
                "codex-rs/hepta-agentd/src/production_writer_host.rs",
            ],
            "rawOwnerRoots": ["codex-rs/hepta-memory/src"],
            "qualificationMarkers": ["/tests/", "_tests.rs", "/examples/", "test_support.rs"],
            "directMutationMethods": [
                "remember_memory",
                "correct_memory",
                "forget_memory",
                "create_memory",
                "revise_memory",
            ],
            "rawWriterAccessorFeature": "qualification-cognitive-write",
            "orphanCheckedRoot": "codex-rs/hepta-cognitive-store/src",
        },
        indent=2,
        sort_keys=True,
    ),
)

write(
    "scripts/cognitive_store_architecture.py",
    r'''#!/usr/bin/env python3
"""Closed-world cognitive.store architecture check.

The check is intentionally stricter than source search in code review: it
rejects orphan Rust modules, a second product-write facade, raw durable-store
imports in serving code, direct mutation calls outside the owner/qualification
set, and a public default-build writer escape hatch.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads(
    (ROOT / "docs/modules/cognitive.store/ARCHITECTURE_BOUNDARY.json").read_text(
        encoding="utf-8"
    )
)


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def qualification_path(path: str) -> bool:
    return any(marker in path for marker in POLICY["qualificationMarkers"])


def rust_files() -> list[Path]:
    return sorted((ROOT / "codex-rs").rglob("*.rs"))


def referenced_modules(src: Path) -> set[str]:
    result: set[str] = set()
    for path in src.glob("*.rs"):
        text = path.read_text(encoding="utf-8")
        for target in re.findall(r'#\s*\[\s*path\s*=\s*"([^"]+)"\s*\]', text):
            result.add((path.parent / target).resolve().as_posix())
        for name in re.findall(r"(?m)^\s*(?:pub(?:\([^)]*\))?\s+)?mod\s+([A-Za-z_][A-Za-z0-9_]*)\s*;", text):
            flat = path.parent / f"{name}.rs"
            nested = path.parent / name / "mod.rs"
            if flat.exists():
                result.add(flat.resolve().as_posix())
            elif nested.exists():
                result.add(nested.resolve().as_posix())
    return result


def main() -> None:
    failures: list[str] = []
    src = ROOT / POLICY["orphanCheckedRoot"]
    referenced = referenced_modules(src)
    for path in sorted(src.glob("*.rs")):
        if path.name == "lib.rs":
            continue
        if path.resolve().as_posix() not in referenced:
            failures.append(f"orphan Rust source is not reachable from the crate root: {rel(path)}")

    forbidden_dead = [
        ROOT / "codex-rs/hepta-cognitive-store/src/production.rs",
        ROOT / "codex-rs/hepta-cognitive-store/src/production_tests.rs",
    ]
    for path in forbidden_dead:
        if path.exists():
            failures.append(f"superseded production facade still exists: {rel(path)}")

    facade = POLICY["canonicalProductWriteFacade"]
    host_path = ROOT / facade["path"]
    host_text = host_path.read_text(encoding="utf-8")
    if f"pub struct {facade['symbol']}" not in host_text:
        failures.append("canonical product-write facade symbol is missing")
    for method in ("remember_with_kg", "correct_with_kg", "forget_with_kg"):
        if f"pub async fn {method}" not in host_text:
            failures.append(f"canonical facade is missing {method}")
    if "pub(crate) fn production_mutation" not in host_text:
        failures.append("sealed mutation capability escapes the Agentd crate")
    if '#[cfg(feature = "qualification-cognitive-write")]\n    pub fn writer' not in host_text:
        failures.append("raw writer accessor is not qualification-feature gated")
    if '#[cfg(not(feature = "qualification-cognitive-write"))]\n    pub(crate) fn writer' not in host_text:
        failures.append("default-build raw writer accessor is not crate-private")

    allowed_raw = set(POLICY["rawBackendAllowedNonTestPaths"])
    raw_patterns = (
        "codex_hepta_memory::CognitiveStore",
        "DurableCognitiveStore as CognitiveStore",
        "DurableCognitiveStore::open",
    )
    owner_roots = tuple(POLICY["rawOwnerRoots"])
    mutation_patterns = tuple(f".{name}(" for name in POLICY["directMutationMethods"])
    for path in rust_files():
        path_s = rel(path)
        text = path.read_text(encoding="utf-8")
        if any(pattern in text for pattern in raw_patterns):
            if not path_s.startswith(owner_roots) and path_s not in allowed_raw and not qualification_path(path_s):
                failures.append(f"raw mutable cognitive backend imported by product source: {path_s}")
        if any(pattern in text for pattern in mutation_patterns):
            if not path_s.startswith(owner_roots) and not qualification_path(path_s):
                failures.append(f"direct cognitive mutation outside owner/qualification code: {path_s}")

    map_path = ROOT / "docs/modules/cognitive.store/IMPLEMENTATION_MAP.json"
    mapping = json.loads(map_path.read_text(encoding="utf-8"))
    callers = mapping.get("productCallers", [])
    canonical = [
        caller
        for caller in callers
        if caller.get("state") == "canonical_production_write_facade"
    ]
    if len(canonical) != 1:
        failures.append("implementation map must contain exactly one canonical production-write facade")
    elif canonical[0].get("sourcePath") != facade["path"] or canonical[0].get("nativeSymbol") != facade["symbol"]:
        failures.append("implementation map canonical facade disagrees with architecture policy")

    closure = (ROOT / "docs/modules/cognitive.store/PRODUCTION_CLOSURE.md").read_text(
        encoding="utf-8"
    )
    if "AgentdProductionWriterHost" not in closure or "unique canonical production-write facade" not in closure:
        failures.append("production closure does not state the unique canonical facade")

    if failures:
        raise SystemExit("FAIL_COGNITIVE_STORE_ARCHITECTURE: " + "; ".join(failures))
    print(
        json.dumps(
            {
                "status": "PASS_COGNITIVE_STORE_ARCHITECTURE",
                "canonicalFacade": facade,
                "orphanRustFiles": 0,
                "rawBackendServingViolations": 0,
                "directMutationViolations": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
''',
)
os.chmod(ROOT / "scripts/cognitive_store_architecture.py", 0o755)

write(
    "scripts/cognitive_store_qualification_manifest.py",
    r'''#!/usr/bin/env python3
"""Aggregate exact-command cognitive.store CI records into one signed-by-Git identity manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


def digest_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--tested-sha", required=True)
    parser.add_argument("--lane", choices=["source-head", "base-merge"], required=True)
    args = parser.parse_args()
    for value in (args.source_sha, args.tested_sha):
        if re.fullmatch(r"[0-9a-f]{40}", value) is None:
            raise SystemExit("invalid Git identity")
    records = []
    failures = []
    for path in sorted(args.records.glob("*.json")):
        row = json.loads(path.read_text(encoding="utf-8"))
        if row.get("status") != "passed" or row.get("exit_code") != 0:
            failures.append(path.name)
        if row.get("source_sha") != args.source_sha or row.get("tested_sha") != args.tested_sha or row.get("lane") != args.lane:
            failures.append(path.name + ":identity")
        records.append(
            {
                "name": path.name,
                "sha256": digest_file(path),
                "command": row.get("command"),
                "status": row.get("status"),
                "passedTests": row.get("observed_passed_tests", 0),
                "failedTests": row.get("observed_failed_tests", 0),
                "elapsedSeconds": row.get("elapsed_seconds"),
                "tree": row.get("after", {}).get("tree"),
            }
        )
    required = {
        "architecture.json",
        "format.json",
        "cognitive-store-tests.json",
        "memory-tests.json",
        "agentd-product-tests.json",
        "crash-reopen.json",
        "perf-256-command.json",
        "perf-16384-command.json",
        "clippy-store-memory.json",
        "clippy-agentd.json",
        "bootstrap-tests.json",
    }
    missing = sorted(required - {row["name"] for row in records})
    if missing:
        failures.extend("missing:" + name for name in missing)
    if failures:
        raise SystemExit("qualification records are incomplete: " + ", ".join(failures))
    manifest = {
        "schema": "hepta.cognitive-store-qualification-manifest.v1",
        "sourceSha": args.source_sha,
        "testedSha": args.tested_sha,
        "lane": args.lane,
        "terminalSuccess": True,
        "records": records,
        "claimBoundary": {
            "sourceImplementation": True,
            "productExecutionAtTestHost": True,
            "independentAcceptance": False,
            "activation": False,
            "release": False,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, sort_keys=True))


if __name__ == "__main__":
    main()
''',
)
os.chmod(ROOT / "scripts/cognitive_store_qualification_manifest.py", 0o755)

# ---------------------------------------------------------------------------
# Phase 4: independently authenticated host bootstrap state.
# ---------------------------------------------------------------------------

write(
    "tools/cognitive-store-host-bootstrap/bootstrap.py",
    r'''#!/usr/bin/env python3
"""Authenticate and transition cognitive.store host bootstrap evidence.

The HMAC key authenticates the host-retained current-cut bundle; it is not a
production-authority signing key.  Authority material must already have been
verified by its external issuer.  Raw fencing tokens are never persisted here.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import stat
import tempfile
import time
from pathlib import Path
from typing import Any

SCHEMA = "hepta.cognitive-store-host-bootstrap.v1"
TERMINAL = {"revoked", "indeterminate", "rolled_back"}
ALLOWED = {
    "prepared": {"active", "revoked", "indeterminate"},
    "active": {"prepared", "revoked", "indeterminate", "rollback_prepared"},
    "rollback_prepared": {"rolled_back", "revoked", "indeterminate"},
    "revoked": set(),
    "indeterminate": {"rollback_prepared"},
    "rolled_back": set(),
}


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha256(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return value


def load_key(path: Path) -> bytes:
    st = path.stat()
    if os.name == "posix" and stat.S_IMODE(st.st_mode) & 0o077:
        raise ValueError("host bootstrap key must not be group/world accessible")
    key = path.read_bytes()
    if not 32 <= len(key) <= 4096:
        raise ValueError("host bootstrap key must contain 32..=4096 bytes")
    return key


def sign(payload: dict[str, Any], key: bytes) -> str:
    return hmac.new(key, canonical(payload), hashlib.sha256).hexdigest()


def atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, pending = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        try:
            os.unlink(pending)
        except FileNotFoundError:
            pass


def validate_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise ValueError(f"{label} must be lowercase SHA-256")
    return value


def validate_anchor(anchor: dict[str, Any], owner: str) -> None:
    required = {"profile", "owner_agent_id", "schema_digest", "state_digest"}
    if set(anchor) != required or anchor["owner_agent_id"] != owner:
        raise ValueError("recovery anchor is incomplete or belongs to another owner")
    validate_sha(anchor["schema_digest"], "anchor schema digest")
    validate_sha(anchor["state_digest"], "anchor state digest")


def validate_authority(authority: dict[str, Any], owner: str, now: int) -> None:
    required = {
        "agent_id",
        "grant_digest",
        "authority_epoch",
        "owner_epoch",
        "lease_expires_at_unix_seconds",
        "fencing_token_digest",
        "issuer_receipt_digest",
    }
    if set(authority) != required or authority["agent_id"] != owner:
        raise ValueError("authority receipt is incomplete or belongs to another owner")
    for field in ("grant_digest", "fencing_token_digest", "issuer_receipt_digest"):
        validate_sha(authority[field], field)
    if type(authority["authority_epoch"]) is not int or authority["authority_epoch"] <= 0:
        raise ValueError("authority epoch must be positive")
    if type(authority["owner_epoch"]) is not int or authority["owner_epoch"] <= 0:
        raise ValueError("owner epoch must be positive")
    if type(authority["lease_expires_at_unix_seconds"]) is not int or authority["lease_expires_at_unix_seconds"] <= now:
        raise ValueError("authority lease is already expired")


def verify(envelope: dict[str, Any], key: bytes, *, now: int | None = None) -> dict[str, Any]:
    if set(envelope) != {"payload", "signature"} or not isinstance(envelope["payload"], dict):
        raise ValueError("invalid bootstrap envelope")
    payload = envelope["payload"]
    expected = sign(payload, key)
    if not hmac.compare_digest(expected, envelope["signature"]):
        raise ValueError("bootstrap signature mismatch")
    if payload.get("schema") != SCHEMA or payload.get("state") not in ALLOWED:
        raise ValueError("unsupported bootstrap schema/state")
    owner = payload.get("owner_agent_id")
    if not isinstance(owner, str) or not owner:
        raise ValueError("missing owner")
    validate_anchor(payload["recovery_anchor"], owner)
    validate_authority(payload["authority"], owner, int(time.time()) if now is None else now)
    if type(payload.get("writer_generation")) is not int or payload["writer_generation"] <= 0:
        raise ValueError("writer generation must be positive")
    validate_sha(payload["active_pointer_sha256"], "active pointer digest")
    validate_sha(payload["database_sha256"], "database digest")
    predecessor = payload.get("predecessor_bundle_sha256")
    if predecessor is not None:
        validate_sha(predecessor, "predecessor bundle digest")
    return payload


def envelope(payload: dict[str, Any], key: bytes) -> dict[str, Any]:
    return {"payload": payload, "signature": sign(payload, key)}


def prepare(
    *,
    owner: str,
    anchor: dict[str, Any],
    authority: dict[str, Any],
    lease_id: str,
    generation: int,
    pointer_digest: str,
    database_digest: str,
    predecessor: str | None,
    purpose: str = "activate",
    now: int | None = None,
) -> dict[str, Any]:
    observed = int(time.time()) if now is None else now
    validate_anchor(anchor, owner)
    validate_authority(authority, owner, observed)
    if not lease_id or generation <= 0:
        raise ValueError("lease id and positive writer generation are required")
    validate_sha(pointer_digest, "active pointer digest")
    validate_sha(database_digest, "database digest")
    if predecessor is not None:
        validate_sha(predecessor, "predecessor bundle digest")
    return {
        "schema": SCHEMA,
        "state": "prepared" if purpose == "activate" else "rollback_prepared",
        "owner_agent_id": owner,
        "recovery_anchor": anchor,
        "authority": authority,
        "lease_id": lease_id,
        "writer_generation": generation,
        "active_pointer_sha256": pointer_digest,
        "database_sha256": database_digest,
        "predecessor_bundle_sha256": predecessor,
        "canary": None,
        "rollback": None if purpose == "activate" else {"compatibility_digest": None},
        "observation": {"issued_at_unix_seconds": observed},
    }


def transition(
    current: dict[str, Any],
    target: str,
    *,
    details: dict[str, Any],
    now: int | None = None,
) -> dict[str, Any]:
    state = current["state"]
    if target not in ALLOWED[state]:
        raise ValueError(f"illegal bootstrap transition {state!r} -> {target!r}")
    next_payload = json.loads(json.dumps(current))
    next_payload["state"] = target
    next_payload["predecessor_bundle_sha256"] = sha256(current)
    next_payload["observation"] = {
        "observed_at_unix_seconds": int(time.time()) if now is None else now,
        **details,
    }
    if target == "active":
        canary = details.get("canary")
        if not isinstance(canary, dict) or canary.get("status") != "committed":
            raise ValueError("activation requires a committed canary receipt")
        if canary.get("before_state_digest") != current["recovery_anchor"]["state_digest"]:
            raise ValueError("canary predecessor does not match the authenticated current cut")
        if canary.get("after_state_digest") == canary.get("before_state_digest"):
            raise ValueError("canary did not advance the durable cut")
        validate_sha(canary.get("after_state_digest"), "canary successor digest")
        next_payload["canary"] = canary
    if target == "rollback_prepared":
        compatibility = details.get("compatibility_digest")
        validate_sha(compatibility, "rollback compatibility digest")
        next_payload["rollback"] = {"compatibility_digest": compatibility}
    if target in TERMINAL:
        reason = details.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("terminal transition requires a reason")
    return next_payload


def load_verified(path: Path, key: bytes, now: int | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    value = load_json(path)
    return value, verify(value, key, now=now)


def cli() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--key-file", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)

    prepare_p = sub.add_parser("prepare")
    prepare_p.add_argument("--owner", required=True)
    prepare_p.add_argument("--anchor", type=Path, required=True)
    prepare_p.add_argument("--authority", type=Path, required=True)
    prepare_p.add_argument("--lease-id", required=True)
    prepare_p.add_argument("--generation", type=int, required=True)
    prepare_p.add_argument("--active-pointer-sha256", required=True)
    prepare_p.add_argument("--database-sha256", required=True)
    prepare_p.add_argument("--predecessor-bundle-sha256")
    prepare_p.add_argument("--output", type=Path, required=True)

    verify_p = sub.add_parser("verify")
    verify_p.add_argument("--input", type=Path, required=True)
    verify_p.add_argument("--expected-owner")
    verify_p.add_argument("--minimum-generation", type=int, default=1)

    transition_p = sub.add_parser("transition")
    transition_p.add_argument("--input", type=Path, required=True)
    transition_p.add_argument("--target", choices=sorted({state for states in ALLOWED.values() for state in states}), required=True)
    transition_p.add_argument("--details", type=Path, required=True)
    transition_p.add_argument("--output", type=Path, required=True)

    args = parser.parse_args()
    key = load_key(args.key_file)
    if args.command == "prepare":
        payload = prepare(
            owner=args.owner,
            anchor=load_json(args.anchor),
            authority=load_json(args.authority),
            lease_id=args.lease_id,
            generation=args.generation,
            pointer_digest=args.active_pointer_sha256,
            database_digest=args.database_sha256,
            predecessor=args.predecessor_bundle_sha256,
        )
        atomic_write(args.output, envelope(payload, key))
        print(json.dumps({"state": payload["state"], "bundle_sha256": sha256(payload)}, sort_keys=True))
    elif args.command == "verify":
        _, payload = load_verified(args.input, key)
        if args.expected_owner is not None and payload["owner_agent_id"] != args.expected_owner:
            raise SystemExit("owner mismatch")
        if payload["writer_generation"] < args.minimum_generation:
            raise SystemExit("writer generation below minimum")
        print(json.dumps({"state": payload["state"], "bundle_sha256": sha256(payload)}, sort_keys=True))
    else:
        _, current = load_verified(args.input, key)
        details = load_json(args.details)
        next_payload = transition(current, args.target, details=details)
        if next_payload["writer_generation"] < current["writer_generation"]:
            raise SystemExit("writer generation regressed")
        atomic_write(args.output, envelope(next_payload, key))
        print(json.dumps({"state": next_payload["state"], "bundle_sha256": sha256(next_payload)}, sort_keys=True))


if __name__ == "__main__":
    cli()
''',
)
os.chmod(ROOT / "tools/cognitive-store-host-bootstrap/bootstrap.py", 0o755)

write(
    "tools/cognitive-store-host-bootstrap/test_bootstrap.py",
    r'''#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

MODULE = Path(__file__).with_name("bootstrap.py")
spec = importlib.util.spec_from_file_location("cognitive_store_bootstrap", MODULE)
bootstrap = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(bootstrap)

HEX_A = "a" * 64
HEX_B = "b" * 64
HEX_C = "c" * 64
HEX_D = "d" * 64
OWNER = "00000000-0000-4000-8000-000000000058"


def anchor(state=HEX_B):
    return {
        "profile": "hepta:cognitive:exact-current-cut:v1",
        "owner_agent_id": OWNER,
        "schema_digest": HEX_A,
        "state_digest": state,
    }


def authority(epoch=1, owner_epoch=1, expiry=500):
    return {
        "agent_id": OWNER,
        "grant_digest": HEX_A,
        "authority_epoch": epoch,
        "owner_epoch": owner_epoch,
        "lease_expires_at_unix_seconds": expiry,
        "fencing_token_digest": HEX_C,
        "issuer_receipt_digest": HEX_D,
    }


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.key = b"k" * 64
        self.payload = bootstrap.prepare(
            owner=OWNER,
            anchor=anchor(),
            authority=authority(),
            lease_id="lease-1",
            generation=1,
            pointer_digest=HEX_C,
            database_digest=HEX_D,
            predecessor=None,
            now=100,
        )

    def test_signed_prepare_round_trip_and_atomic_permissions(self):
        value = bootstrap.envelope(self.payload, self.key)
        self.assertEqual(bootstrap.verify(value, self.key, now=100), self.payload)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bundle.json"
            bootstrap.atomic_write(path, value)
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_activation_requires_committed_cut_advancing_canary(self):
        with self.assertRaises(ValueError):
            bootstrap.transition(self.payload, "active", details={"canary": {"status": "failed"}}, now=101)
        active = bootstrap.transition(
            self.payload,
            "active",
            details={
                "canary": {
                    "status": "committed",
                    "before_state_digest": HEX_B,
                    "after_state_digest": HEX_C,
                    "operation_digest": HEX_D,
                }
            },
            now=101,
        )
        self.assertEqual(active["state"], "active")
        self.assertEqual(active["canary"]["after_state_digest"], HEX_C)

    def test_revocation_is_terminal(self):
        revoked = bootstrap.transition(self.payload, "revoked", details={"reason": "operator revoke"}, now=102)
        with self.assertRaises(ValueError):
            bootstrap.transition(revoked, "active", details={}, now=103)

    def test_pointer_publication_ambiguity_is_explicit(self):
        value = bootstrap.transition(self.payload, "indeterminate", details={"reason": "pointer rename fsync unknown"}, now=104)
        self.assertEqual(value["state"], "indeterminate")

    def test_rollback_requires_compatibility_digest(self):
        active = bootstrap.transition(
            self.payload,
            "active",
            details={"canary": {"status": "committed", "before_state_digest": HEX_B, "after_state_digest": HEX_C}},
            now=101,
        )
        with self.assertRaises(ValueError):
            bootstrap.transition(active, "rollback_prepared", details={}, now=105)
        rollback = bootstrap.transition(active, "rollback_prepared", details={"compatibility_digest": HEX_D}, now=105)
        self.assertEqual(rollback["state"], "rollback_prepared")

    def test_stale_or_expired_authority_rejects(self):
        with self.assertRaises(ValueError):
            bootstrap.prepare(
                owner=OWNER,
                anchor=anchor(),
                authority=authority(expiry=99),
                lease_id="lease-expired",
                generation=2,
                pointer_digest=HEX_C,
                database_digest=HEX_D,
                predecessor=HEX_A,
                now=100,
            )


if __name__ == "__main__":
    unittest.main()
''',
)

write(
    "tools/cognitive-store-host-bootstrap/SCHEMA.json",
    json.dumps(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "hepta.cognitive-store-host-bootstrap.v1",
            "type": "object",
            "additionalProperties": False,
            "required": ["payload", "signature"],
            "properties": {
                "signature": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                "payload": {
                    "type": "object",
                    "additionalProperties": True,
                    "required": [
                        "schema",
                        "state",
                        "owner_agent_id",
                        "recovery_anchor",
                        "authority",
                        "lease_id",
                        "writer_generation",
                        "active_pointer_sha256",
                        "database_sha256",
                    ],
                },
            },
        },
        indent=2,
        sort_keys=True,
    ),
)

# ---------------------------------------------------------------------------
# Phase 5: lifecycle, operations, SLO and threat documentation.
# ---------------------------------------------------------------------------

write(
    "docs/modules/cognitive.store/README.md",
    r'''# cognitive.store authoritative entry point

This directory has one current architecture decision:

- **Unique production-write facade:** `AgentdProductionWriterHost`.
- **Physical owner:** `hepta-memory::CognitiveStore` over `cognitive_1.sqlite3`.
- **Serving capability:** `DurableCognitiveReadStore`, which has no mutation or raw-backend escape.
- **Semantic oracle:** `AdmittedCognitiveStoreV2`; it is not a second database.
- **External prerequisites:** an independently authenticated current-cut witness and an externally verified live production-authority lease.

`TECHNICAL.md` defines the module, `PRODUCTION_CLOSURE.md` fixes composition and evidence boundaries, and `IMPLEMENTATION_MAP.json` is the machine-readable status.  The remaining files are normative lifecycle and operator references:

- `adr/ADR-0001-retention-pruning.md`
- `BACKUP_WAL_DERIVED_ARTIFACTS.md`
- `PRIVACY_EXPORT_DELETE.md`
- `SCHEMA_COMPATIBILITY.md`
- `ERROR_CATALOG.md`
- `RETRY_RECONCILE_MATRIX.md`
- `SLO.md`
- `THREAT_MODEL.md`

Run `python3 scripts/cognitive_store_architecture.py` before any cognitive-store change.  Exact source-head and deterministic base-merge execution belongs to `.github/workflows/cognitive-store-qualification.yml`; source presence or prose never substitutes for its terminal receipts.
''',
)

write(
    "docs/modules/cognitive.store/PRODUCTION_CLOSURE.md",
    r'''# cognitive.store production convergence

Status: source implementation with independent exact-candidate qualification required; activation and release remain externally governed.

## Unique canonical production-write facade

`codex_hepta_agentd::AgentdProductionWriterHost` is the **unique canonical production-write facade**.  The deleted `ProductionCognitiveStore` file was unreachable from its crate root and is not an API.  The semantic V2 store is a qualification oracle, not a production database.

```text
external trusted host
  | current-cut witness + live authority + generation
  v
AgentdProductionWriterHost
  | sealed ProductionCognitiveMutationCapability
  v
hepta-memory::CognitiveStore
  | BEGIN IMMEDIATE + WAL/FULL + append-only provenance
  v
cognitive_1.sqlite3
```

Normal serving state retains only `DurableCognitiveReadStore`.  Its API exposes snapshots, retrieval observation and revalidation, but no source append, memory mutation, migration, lease creation, writer or raw backend.  The raw writer accessor on the product facade is public only under `qualification-cognitive-write`; the default build keeps it crate-private.

## Authority and linearization

Every production semantic mutation requires an externally verified authority lease, owner/authority epochs, an opaque grant-bound fencing token, a nonzero writer generation, the expected predecessor revision and the final semantic input digest.  Agentd never mints these values.  Admission, source/Memory/fact/projection mutation and committed provenance share one SQLite transaction.  Identical recovery is idempotent; changed semantics conflict; uncertain external dispatch is observer-only reconciliation and never blind replay.

## Recovery and bootstrap

Writable recovery is descriptor-bound and fail-closed.  It acquires the exclusive store fence, copies retained database/WAL/journal descriptors into a private generation, verifies schema, integrity, exact current-cut equality and live production authority, checkpoints, then atomically publishes the active pointer.  Ambiguity after pointer rename is `Indeterminate`.

`tools/cognitive-store-host-bootstrap/bootstrap.py` persists and authenticates the host-side witness bundle, monotone epochs/generation, active-pointer/database digests, canary, revocation and rollback state.  Its HMAC key authenticates host evidence only; it cannot issue production authority and never stores raw fencing tokens.

## Qualification boundary

The dedicated workflow independently runs source-head and deterministic base-merge lanes.  Each command is wrapped by `hepta_ci_exec.py`, bound to exact source/tested SHAs and retained in one machine-readable manifest.  Required commands include package tests, the Agentd product test, ignored crash/reopen probe, 256 and 16,384 record profiles, strict Clippy, architecture verification and bootstrap tests.

A green source workflow proves the tested source implementation only.  Independent semantic review, target-host qualification, operator acceptance, canary promotion, activation and release remain separate.  Tombstone is logical non-use; it is never represented as physical erase, backup deletion, derived-artifact revocation or model unlearning.
''',
)

write(
    "docs/modules/cognitive.store/adr/ADR-0001-retention-pruning.md",
    r'''# ADR-0001: ancestry-safe retention and pruning

Status: accepted design; destructive compaction requires a separately qualified implementation.

The authoritative Memory/source/fact ledgers remain append-only.  Bounded paging limits materialization and does not authorize deletion.  A retention job may remove payload bytes only after a signed prune plan proves: every retained head has complete required ancestry; tombstones and revocation frontiers survive; citations and KG generation receipts remain interpretable; backup/WAL generations are covered; dependent artifacts have acknowledged revocation; and an independently retained current-cut witness advances after commit.

Pruning is a fenced generation transition.  It writes an immutable plan and predecessor digest, builds a private compacted generation, verifies semantic equivalence for retained live state and non-resurrection for deleted state, then atomically publishes.  Failure before publication leaves the predecessor active.  Uncertain publication is `Indeterminate`.  No in-place `DELETE` of ledger rows is allowed.

Minimum retention classes are: live payload, tombstone lineage, security/audit receipt, legal hold and prohibited payload.  A legal hold blocks physical deletion but not logical non-use.  A prohibited payload may be cryptographically shredded while retaining non-content lineage.  Model unlearning and derived-artifact deletion are separate owners and cannot be inferred from this store.
''',
)

write(
    "docs/modules/cognitive.store/BACKUP_WAL_DERIVED_ARTIFACTS.md",
    r'''# Backup, WAL and derived-artifact handling

A cognitive backup is a database/WAL/journal generation plus owner identity, schema digest, exact current-cut anchor and active-pointer digest.  Copying only the main SQLite file is not a valid backup while WAL state is live.  Backups are encrypted, generation-labelled, immutable and excluded from ordinary retrieval.

Restore never opens the supplied source path as a writer.  The descriptor-bound recovery boundary copies it into a private generation, validates exact currentness and authority, checkpoints and publishes.  A backup older than the independently retained witness is rejected even when SQLite integrity succeeds.

Deletion disposition is tracked independently for: active database, WAL/SHM/journal, recovery candidates, offline backups, search indexes, KG projections, prompt/context caches, evaluation datasets and learned artifacts.  A logical tombstone closes retrieval immediately; physical media deletion and derived-artifact revocation require receipts from their owners.  Unknown acknowledgement remains pending or indeterminate, never “deleted”.
''',
)

write(
    "docs/modules/cognitive.store/PRIVACY_EXPORT_DELETE.md",
    r'''# Privacy, export and delete runbook

## Export

Authenticate the requester and exact Agent/workspace scope.  Acquire one read snapshot, bind its cut digest and observation time, export only current permitted fields and citations, redact secrets/provider credentials, and emit a DENY_ALL export receipt.  Pagination must remain on the same cut; drift restarts the export rather than mixing generations.

## Logical delete

Record an explicit source event and append a successor tombstone with compare-and-swap predecessor.  Commit the empty fact set and projection update in the same transaction.  Revalidate retrieval and shared-use grants; revoked or stale consumers must stop using the record.

## Physical delete

Create a prune plan under ADR-0001, enumerate database/WAL/backups/derived artifacts, honor legal holds, obtain each owner’s receipt and publish a new exact-cut witness.  Do not claim physical erase while any required disposition is pending, unavailable or indeterminate.  Model unlearning is reported separately.

## Incident stop

On owner mismatch, rollback evidence, stale/revoked authority, pointer ambiguity or secret leakage: fence new writes, preserve descriptors and receipts, revoke the authority generation, mark host bootstrap state indeterminate where applicable, and require a new trusted recovery ceremony.
''',
)

write(
    "docs/modules/cognitive.store/SCHEMA_COMPATIBILITY.md",
    r'''# Schema migration compatibility matrix

| Transition | Read old | Write old | Roll back binary | Required evidence |
| --- | --- | --- | --- | --- |
| Same schema, newer binary | yes | after owner verification | yes | schema oracle, exact cut, package tests |
| Additive tables/indexes/triggers | yes after migration | new schema only | only if old binary ignores additions | migration checksum, reopen, rollback rehearsal |
| Semantic digest or authority change | adapter only | no dual write | no without explicit compatibility adapter | golden vectors, caller migration, fresh generation |
| Destructive/compacting migration | private generation only | after atomic publish | predecessor generation retained | prune plan, equivalence/non-resurrection proof |
| Unknown schema object or checksum drift | no | no | no automatic fallback | quarantine and operator recovery |

Migrations run under the single owner before readiness.  Required schema objects and their SQL are digest-bound.  A migration failure leaves the predecessor generation recoverable.  No route cutover may copy records into a second writable cognitive database.
''',
)

write(
    "docs/modules/cognitive.store/ERROR_CATALOG.md",
    r'''# Stable error catalog

| Code | Class | Retry | Operator action |
| --- | --- | --- | --- |
| `COG_INVALID_INPUT` | rejected | no | correct bounded/versioned input |
| `COG_ACCESS_DENIED` | security | no | verify owner/scope/authority; do not downgrade |
| `COG_REVISION_CONFLICT` | concurrency | after reread | reacquire head and issue a new intent |
| `COG_WRITER_FENCED` | security/concurrency | no on same generation | obtain newer externally verified generation |
| `COG_AUTHORITY_REVOKED` | security | no | stop writer and reconcile committed outcomes |
| `COG_STORE_UNAVAILABLE` | availability | bounded before admission | preserve existing cut; alert on SLO breach |
| `COG_STORE_CORRUPT` | integrity | no ordinary retry | descriptor-safe recovery ceremony |
| `COG_RECOVERY_STALE_CUT` | rollback protection | no | supply authenticated current witness |
| `COG_RECOVERY_INDETERMINATE` | integrity | no automatic retry | reconcile active pointer/candidate manually |
| `COG_CAPACITY_EXCEEDED` | resource | no blind retry | page, archive under ADR, or increase qualified profile |
| `COG_EXTERNAL_EFFECT_INDETERMINATE` | effect truth | observer only | reconcile destination; never redispatch blindly |

Rust variants remain the typed source of truth.  Adapters map them to these stable codes without parsing display strings; messages may change, codes and retry classes may not change in place.
''',
)

write(
    "docs/modules/cognitive.store/RETRY_RECONCILE_MATRIX.md",
    r'''# Retry and reconciliation matrix

| Point of failure | Mutation possible? | Allowed next action |
| --- | ---: | --- |
| Before SQLite admission | no | bounded retry with identical intent identity |
| During transaction before commit | no after rollback | identical retry after store availability |
| Commit returned success | yes | return/query committed receipt; changed retry conflicts |
| Response lost after local commit | yes | query occurrence/provenance; do not create a new intent |
| Before external final-use entry | local queue only | renew bounded claim or release safely |
| After possible external entry | unknown | mark Indeterminate and observer-only reconcile |
| Authority revoked before mutation | no | reject; obtain a newer grant/generation |
| Authority revoked after local commit | yes | preserve commit; revoke future use |
| Active-pointer rename/fsync ambiguous | unknown active generation | no cleanup; mark recovery Indeterminate |
| Restore older valid backup | would resurrect | reject by exact current-cut witness |

Backoff, claim lifetime and batch size are bounded configuration.  Reconciliation never treats queue acceptance, process exit or timeout as destination success.
''',
)

write(
    "docs/modules/cognitive.store/SLO.md",
    r'''# Cognitive store SLO and capacity profile

These are qualification targets, not claims about an unmeasured host.

- Correctness: zero acknowledged mutations without a committed receipt; zero cross-owner reads/writes; zero resurrection after a committed tombstone or current-witness rollback rejection.
- Availability: 99.9% successful bounded local read/revalidation operations over a 30-day target-host window, excluding explicit security denial.
- Latency targets: p99 local semantic commit <= 100 ms at the 256-record profile; p99 exact-ID read/revalidation <= 50 ms; cold reopen <= 2 s; 16,384-record snapshot/profile measurements must complete inside the dedicated CI command deadline.
- Growth: report database, WAL/journal and recovery-generation bytes; alert at 70% and stop new ordinary writes before the qualified hard limit.
- Recovery: crash/reopen RTO <= 60 s on the selected host; RPO is the last acknowledged SQLite FULL commit.  Descriptor-safe recovery requires the exact independently retained witness.

The workflow records p50/p95/p99/max, file bytes, cold-open, recovery-anchor and reopen cost for 256 and 16,384 records.  Threshold promotion requires target-host evidence and operator approval; repository CI artifacts alone do not activate production.
''',
)

write(
    "docs/modules/cognitive.store/THREAT_MODEL.md",
    r'''# cognitive.store threat model

| Threat | Control | Required negative evidence |
| --- | --- | --- |
| Raw-store/capability bypass | read-only serving wrapper; unique Agentd facade; architecture gate | forbidden import/direct-write fixtures fail |
| Stale or replayed authority | grant digest, epochs, expiry, generation, live verifier | stale/revoked grant cannot advance cut |
| Valid-but-old backup rollback | independently retained exact current-cut witness | pre-tombstone backup rejected |
| Symlink/path/descriptor replacement | canonical path, `O_NOFOLLOW`, retained descriptors, exclusive fence | hostile identity cases reject |
| WAL/journal omission | descriptor-bound database/WAL/journal copy and checkpoint | crash/reopen exposes only committed predecessor/successor |
| Pointer publication ambiguity | atomic pointer + directory fsync; Indeterminate retirement | candidate is not deleted or reported inactive |
| Cross-Agent/workspace confusion | stable owner/scope identity and authorization before query | cross-owner and scope-escape tests deny |
| Intent/receipt replay with payload drift | semantic digest + stable intent identity | identical retry idempotent; changed retry conflicts |
| Provenance/source mismatch | same-transaction source revision/digest/time binding | canonical/durable mismatch rejects |
| Secret leakage | bounded content, redacted/digested evidence, no raw token persistence | canary secret absent from logs/receipts/exports |
| Resource exhaustion | content/count/page/journal/recovery bounds | oversize and maximum-retained profiles fail closed |
| Tombstone misrepresented as erasure | explicit lifecycle dispositions and ADR | docs/API never equate tombstone with media/model deletion |

New persistence, authority, export, federation or effect boundaries require threat-table and negative-test updates in the same change.
''',
)

# Append a current, non-ambiguous convergence section to the stable guide and
# replace the empty owned-threat declaration.
replace(
    "docs/modules/cognitive.store/TECHNICAL.md",
    "Owned threat entries:\n\nNone.",
    "Owned threat entries:\n\n- raw-store or capability bypass;\n- stale/replayed authority and generation rollback;\n- valid-but-old backup restoration;\n- symlink, descriptor, WAL/journal and active-pointer substitution;\n- cross-Agent/workspace scope confusion;\n- intent/receipt replay with semantic drift;\n- provenance/source-revision mismatch;\n- secret leakage and bounded-resource exhaustion;\n- tombstone being misreported as physical erasure or model unlearning.\n\nThe normative control/test mapping is [THREAT_MODEL.md](THREAT_MODEL.md).",
)
with (ROOT / "docs/modules/cognitive.store/TECHNICAL.md").open("a", encoding="utf-8") as stream:
    stream.write(
        "\n\n## 18. Current convergence decision (2026-09-27)\n\n"
        "`AgentdProductionWriterHost` is the unique production-write facade.  The unreachable "
        "`production.rs` facade has been removed.  Normal Agentd serving state stores only "
        "`DurableCognitiveReadStore`; raw backend imports and direct mutation calls are closed-world "
        "checked by `scripts/cognitive_store_architecture.py`.  The default build keeps the raw writer "
        "accessor crate-private; qualification explicitly enables `qualification-cognitive-write`.\n\n"
        "The dedicated `cognitive-store-qualification.yml` workflow runs independently of unrelated "
        "modules in source-head and deterministic base-merge lanes and emits exact-SHA command records, "
        "crash/reopen and 256/16,384-record performance artifacts.  Host bootstrap evidence is persisted "
        "by `tools/cognitive-store-host-bootstrap`; it authenticates current-cut/rotation/revocation/canary/"
        "rollback observations but never mints production authority.  Activation, independent acceptance "
        "and release remain false until their external gates complete.\n"
    )

# Update the machine map semantically.  The bootstrap workflow commits these
# edits, then runs the canonical map migrator in a second clean commit so every
# source object and provenance anchor is rebound to the exact result.
map_path = ROOT / "docs/modules/cognitive.store/IMPLEMENTATION_MAP.json"
mapping = json.loads(map_path.read_text(encoding="utf-8"))
mapping["productCallerState"] = "single_canonical_agentd_writer_facade_source_composed_external_bootstrap_qualification_pending"
mapping["productionWriterState"] = "sealed_same_transaction_live_verified_writer_default_escape_closed_qualification_pending"
mapping["productionImplementation"] = False
mapping["productWriteFacade"] = {
    "sourcePath": "codex-rs/hepta-agentd/src/production_writer_host.rs",
    "nativeSymbol": "AgentdProductionWriterHost",
    "uniquenessEnforcedBy": "scripts/cognitive_store_architecture.py",
}
mapping["productCallers"] = [
    {
        "sourcePath": "codex-rs/hepta-agentd/src/production_writer_host.rs",
        "nativeSymbol": "AgentdProductionWriterHost",
        "state": "canonical_production_write_facade",
    }
]
for op in mapping.get("operations", []):
    if op.get("operation") == "durable_owner":
        op["nativeSymbol"] = "DurableCognitiveReadStore"
        op["state"] = "read_only_product_facade_source_implemented_qualification_pending"
        op["authority"] = "deny_all_read"
    elif op.get("operation") == "product_writer_host":
        op["state"] = "unique_canonical_product_write_facade_source_implemented_qualification_pending"
    elif op.get("operation") == "production_mutation_capability":
        op["state"] = "sealed_live_verified_same_transaction_source_implemented_default_escape_closed_qualification_pending"
new_ops = [
    {
        "operation": "architecture_boundary_gate",
        "designOperation": "closed_world_raw_store_and_unique_facade_verification",
        "nativeSymbol": "main",
        "sourcePath": "scripts/cognitive_store_architecture.py",
        "mappingClass": "source_verifier",
        "delegatedCallees": [],
        "tests": [".github/workflows/cognitive-store-qualification.yml"],
        "state": "source_implemented_execution_pending",
        "authority": "none",
        "sourcePathExists": True,
    },
    {
        "operation": "host_bootstrap_evidence",
        "designOperation": "authenticate_current_cut_rotation_revocation_canary_rollback",
        "nativeSymbol": "verify",
        "sourcePath": "tools/cognitive-store-host-bootstrap/bootstrap.py",
        "mappingClass": "trusted_host_tool",
        "delegatedCallees": [],
        "tests": ["tools/cognitive-store-host-bootstrap/test_bootstrap.py"],
        "state": "source_implemented_target_host_acceptance_pending",
        "authority": "host_evidence_authentication_not_authority_issuance",
        "sourcePathExists": True,
    },
    {
        "operation": "cognitive_store_qualification",
        "designOperation": "exact_source_head_and_deterministic_base_merge_execution",
        "nativeSymbol": "Cognitive store qualification",
        "sourcePath": ".github/workflows/cognitive-store-qualification.yml",
        "mappingClass": "qualification_workflow",
        "delegatedCallees": [],
        "tests": [
            "scripts/cognitive_store_qualification_manifest.py",
            "codex-rs/hepta-agentd/tests/cognitive_store_product_writer.rs",
        ],
        "state": "source_implemented_execution_pending",
        "authority": "none",
        "sourcePathExists": True,
    },
]
existing = {op.get("operation") for op in mapping.get("operations", [])}
mapping["operations"].extend(op for op in new_ops if op["operation"] not in existing)
mapping["repositoryControlledGaps"] = [
    "Obtain terminal-success source-head and deterministic synthetic-merge manifests for the exact final candidate, including crash/reopen and 256/16384 PERF-DURABLE records.",
    "Qualify the authenticated bootstrap bundle, canary, active-pointer ambiguity handling and rollback generation on the selected target host.",
    "Implement and qualify destructive ancestry-safe pruning/physical erasure; current tombstones remain logical non-use and do not imply backup or model deletion.",
]
mapping["externalEvidenceGates"] = [
    "independent semantic and security review",
    "trusted authority issuer and target-host product qualification",
    "operator acceptance, canary promotion, activation and release",
]
mapping["claimBoundary"] = {
    "nativeSourceMappingComplete": True,
    "sourceRootPresent": True,
    "productionImplementation": False,
    "productExecutionProved": False,
    "independentAcceptance": False,
    "activation": False,
    "release": False,
    "implementedOperationMappingComplete": True,
}
mapping["phaseClosure"] = {
    "architectureAmbiguity": "source_implemented",
    "compileTimeCapabilityBoundary": "source_implemented_with_closed_world_build_gate",
    "dedicatedQualification": "workflow_source_implemented_execution_pending",
    "trustedHostBootstrap": "source_implemented_target_host_acceptance_pending",
    "dataLifecycleAndRunbooks": "documented_pruning_runtime_pending",
}
map_path.write_text(json.dumps(mapping, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

# ---------------------------------------------------------------------------
# Dedicated independent workflow.  It is intentionally not chained to the
# monolithic repository qualification job, so unrelated failures cannot cancel
# its receipts.
# ---------------------------------------------------------------------------

write(
    ".github/workflows/cognitive-store-qualification.yml",
    r'''name: Cognitive store qualification

on:
  pull_request:
    paths:
      - 'codex-rs/hepta-cognitive-store/**'
      - 'codex-rs/hepta-memory/**'
      - 'codex-rs/hepta-agentd/**'
      - 'codex-rs/state/**'
      - 'docs/modules/cognitive.store/**'
      - 'tools/cognitive-store-host-bootstrap/**'
      - 'scripts/cognitive_store_*.py'
      - '.github/workflows/cognitive-store-qualification.yml'
  push:
    branches:
      - main
      - codex/cognitive-store-full-convergence-20260927
    paths:
      - 'codex-rs/hepta-cognitive-store/**'
      - 'codex-rs/hepta-memory/**'
      - 'codex-rs/hepta-agentd/**'
      - 'codex-rs/state/**'
      - 'docs/modules/cognitive.store/**'
      - 'tools/cognitive-store-host-bootstrap/**'
      - 'scripts/cognitive_store_*.py'
      - '.github/workflows/cognitive-store-qualification.yml'

permissions:
  contents: read

env:
  SOURCE_SHA: ${{ github.event.pull_request.head.sha || github.sha }}
  BASE_SHA: ${{ github.event.pull_request.base.sha || github.event.before }}

jobs:
  architecture:
    name: cognitive.store architecture and host bootstrap
    runs-on: ubuntu-24.04
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
        with:
          ref: ${{ env.SOURCE_SHA }}
          fetch-depth: 0
          persist-credentials: false
      - name: Bind exact source
        run: |
          set -euo pipefail
          test "$(git rev-parse HEAD)" = "$SOURCE_SHA"
          git diff --quiet
          git diff --cached --quiet
          test -z "$(git status --porcelain --untracked-files=normal)"
      - name: Verify closed-world architecture
        run: python3 scripts/cognitive_store_architecture.py
      - name: Test authenticated host bootstrap
        run: python3 tools/cognitive-store-host-bootstrap/test_bootstrap.py
      - name: Verify module maps
        run: python3 scripts/hepta-implementation-maps.py verify --expected-sha "$SOURCE_SHA" --expected-tree "$(git rev-parse HEAD^{tree})"

  qualification:
    name: cognitive.store exact candidate (${{ matrix.lane }})
    needs: [architecture]
    runs-on: ubuntu-24.04
    timeout-minutes: 90
    strategy:
      fail-fast: false
      matrix:
        lane: ${{ fromJSON(github.event_name == 'pull_request' && '["source-head","base-merge"]' || '["source-head"]') }}
    steps:
      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
        with:
          ref: ${{ env.SOURCE_SHA }}
          fetch-depth: 0
          persist-credentials: false
      - name: Resolve current pull-request base
        id: current-base
        if: github.event_name == 'pull_request'
        env:
          BASE_REF: ${{ github.base_ref }}
        run: |
          set -euo pipefail
          CURRENT_BASE="$(git rev-parse "refs/remotes/origin/${BASE_REF}^{commit}")"
          echo "sha=$CURRENT_BASE" >> "$GITHUB_OUTPUT"
          echo "BASE_SHA=$CURRENT_BASE" >> "$GITHUB_ENV"
      - name: Construct deterministic base merge
        id: synthetic
        if: matrix.lane == 'base-merge'
        uses: ./.github/actions/hepta-synthetic-merge
        with:
          base-sha: ${{ steps.current-base.outputs.sha }}
          source-sha: ${{ env.SOURCE_SHA }}
          pr-number: ${{ github.event.pull_request.number }}
          author-name: Hepta Cognitive Store CI
          author-email: hepta-cognitive-ci@users.noreply.github.com
          message: Cognitive store synthetic merge
      - name: Bind executable identity
        env:
          TESTED_SHA: ${{ steps.synthetic.outputs.sha || env.SOURCE_SHA }}
          HEPTA_CI_LANE: ${{ matrix.lane }}
        run: |
          set -euo pipefail
          test "$(git rev-parse HEAD)" = "$TESTED_SHA"
          git diff --quiet
          git diff --cached --quiet
          test -z "$(git status --porcelain --untracked-files=normal)"
          echo "TESTED_SHA=$TESTED_SHA" >> "$GITHUB_ENV"
          echo "HEPTA_CI_LANE=$HEPTA_CI_LANE" >> "$GITHUB_ENV"
          mkdir -p "$RUNNER_TEMP/cognitive-store-records"
      - name: Prepare native prerequisites
        run: |
          sudo apt-get update
          sudo apt-get install -y build-essential bubblewrap libcap-dev pkg-config
          sudo sysctl -w kernel.unprivileged_userns_clone=1
          if sysctl kernel.apparmor_restrict_unprivileged_userns >/dev/null 2>&1; then
            sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
          fi
      - name: Install DotSlash
        uses: facebook/install-dotslash@1e4e7b3e07eaca387acb98f1d4720e0bee8dbb6a
      - name: Expose DotSlash
        run: sudo install -m 0755 "$(command -v dotslash)" /usr/local/bin/dotslash
      - uses: taiki-e/install-action@44c6d64aa62cd779e873306675c7a58e86d6d532
        with:
          tool: just@1.51.0,nextest@0.9.103
      - name: Resolve verified V8 artifacts
        env:
          CODEX_REPO_ROOT: ${{ github.workspace }}
          PYTHONPATH: scripts
        run: python3 scripts/hepta_ci_v8.py
      - name: Architecture receipt
        run: python3 scripts/hepta_ci_exec.py --output "$RUNNER_TEMP/cognitive-store-records/architecture.json" --minimum-tests 0 -- python3 scripts/cognitive_store_architecture.py
      - name: Format receipt
        working-directory: codex-rs
        run: python3 ../scripts/hepta_ci_exec.py --output "$RUNNER_TEMP/cognitive-store-records/format.json" -- cargo fmt --package codex-hepta-cognitive-store --package codex-hepta-memory --package codex-hepta-agentd -- --check
      - name: cognitive-store package tests
        working-directory: codex-rs
        run: python3 ../scripts/hepta_ci_exec.py --output "$RUNNER_TEMP/cognitive-store-records/cognitive-store-tests.json" --minimum-tests 1 -- cargo test --locked -p codex-hepta-cognitive-store
      - name: memory package tests
        working-directory: codex-rs
        run: python3 ../scripts/hepta_ci_exec.py --output "$RUNNER_TEMP/cognitive-store-records/memory-tests.json" --minimum-tests 1 -- cargo test --locked -p codex-hepta-memory
      - name: Agentd product test
        working-directory: codex-rs
        run: python3 ../scripts/hepta_ci_exec.py --output "$RUNNER_TEMP/cognitive-store-records/agentd-product-tests.json" --minimum-tests 1 -- cargo test --locked -p codex-hepta-agentd --test cognitive_store_product_writer --features qualification-cognitive-write
      - name: Child-process crash and reopen
        working-directory: codex-rs
        run: python3 ../scripts/hepta_ci_exec.py --output "$RUNNER_TEMP/cognitive-store-records/crash-reopen.json" --minimum-tests 1 -- cargo test --locked -p codex-hepta-memory local_lease_outbox_tests::qualification_durable_writer_crash_reopen_probe -- --ignored --exact
      - name: Durable profile 256
        working-directory: codex-rs
        env:
          HEPTA_COGNITIVE_PERF_RECORDS: '256'
          HEPTA_COGNITIVE_PERF_OUTPUT: ${{ runner.temp }}/cognitive-store-records/perf-256.json
        run: python3 ../scripts/hepta_ci_exec.py --output "$RUNNER_TEMP/cognitive-store-records/perf-256-command.json" -- cargo run --locked -p codex-hepta-memory --example cognitive_store_perf
      - name: Durable profile 16384
        working-directory: codex-rs
        env:
          HEPTA_COGNITIVE_PERF_RECORDS: '16384'
          HEPTA_COGNITIVE_PERF_OUTPUT: ${{ runner.temp }}/cognitive-store-records/perf-16384.json
        run: python3 ../scripts/hepta_ci_exec.py --output "$RUNNER_TEMP/cognitive-store-records/perf-16384-command.json" --timeout-seconds 5400 -- cargo run --locked -p codex-hepta-memory --example cognitive_store_perf
      - name: Strict Clippy store and memory
        working-directory: codex-rs
        run: python3 ../scripts/hepta_ci_exec.py --output "$RUNNER_TEMP/cognitive-store-records/clippy-store-memory.json" -- cargo clippy --locked -p codex-hepta-cognitive-store -p codex-hepta-memory --all-targets -- -D warnings
      - name: Strict Clippy Agentd product profile
        working-directory: codex-rs
        run: python3 ../scripts/hepta_ci_exec.py --output "$RUNNER_TEMP/cognitive-store-records/clippy-agentd.json" -- cargo clippy --locked -p codex-hepta-agentd --all-targets --features qualification-cognitive-write -- -D warnings
      - name: Host bootstrap tests receipt
        run: python3 scripts/hepta_ci_exec.py --output "$RUNNER_TEMP/cognitive-store-records/bootstrap-tests.json" --minimum-tests 1 -- python3 tools/cognitive-store-host-bootstrap/test_bootstrap.py
      - name: Build exact qualification manifest
        run: |
          python3 scripts/cognitive_store_qualification_manifest.py \
            --records "$RUNNER_TEMP/cognitive-store-records" \
            --output "$RUNNER_TEMP/cognitive-store-qualification.json" \
            --source-sha "$SOURCE_SHA" \
            --tested-sha "$TESTED_SHA" \
            --lane "$HEPTA_CI_LANE"
          git diff --check
          git diff --exit-code
          test -z "$(git status --porcelain --untracked-files=no)"
      - name: Retain exact command and performance evidence
        if: always()
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02
        with:
          name: cognitive-store-${{ github.run_id }}-${{ github.run_attempt }}-${{ matrix.lane }}
          path: |
            ${{ runner.temp }}/cognitive-store-records/*
            ${{ runner.temp }}/cognitive-store-qualification.json
          if-no-files-found: error
          retention-days: 30
''',
)

# The temporary bootstrap removes itself and its one-shot workflow from the
# result.  The permanent qualification workflow above remains.
for temporary in (
    "scripts/cognitive_store_convergence_bootstrap.py",
    ".github/workflows/cognitive-store-convergence-bootstrap.yml",
):
    target = ROOT / temporary
    if target.exists():
        target.unlink()

print(json.dumps({"status": "applied", "module": "cognitive.store"}, sort_keys=True))
