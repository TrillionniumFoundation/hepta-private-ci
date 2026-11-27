// Copyright 2022 The Matrix.org Foundation C.I.C.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

use std::future::Future;
use std::sync::Arc;
use std::sync::atomic::AtomicU8;
use std::sync::atomic::Ordering;

/// Bounded observations for one group of SQLite store opens.
///
/// Snapshots contain only fixed labels, in state, crypto, event-cache, media
/// order. Values are last entered markers, not durations or success results.
/// Slots are read independently; a cipher worker may update after owner drop.
/// Use a fresh holder for each build; config clones share that build's holder.
#[derive(Clone, Default)]
pub struct SqliteStoreOpenDiagnostics {
    progress: Arc<OpenProgress>,
}

#[derive(Default)]
struct OpenProgress {
    owner: [AtomicU8; 4],
    worker: [AtomicU8; 4],
}

#[derive(Clone, Copy)]
pub(super) enum StoreRole {
    State,
    Crypto,
    EventCache,
    Media,
}

impl StoreRole {
    const ALL: [Self; 4] = [Self::State, Self::Crypto, Self::EventCache, Self::Media];
}

#[derive(Clone, Copy)]
pub(super) enum OpenPhase {
    Unobserved,
    PathPrepare,
    PoolAcquire,
    SchemaVersion,
    InitialSchema,
    Migrations,
    CipherRead,
    CipherWait,
    CipherSave,
    Checkpoint,
    MetadataRead,
    RuntimeConfig,
    Complete,
}

const OWNER_LABELS: [(OpenPhase, &str); 13] = [
    (OpenPhase::Unobserved, "unobserved"),
    (OpenPhase::PathPrepare, "path_prepare"),
    (OpenPhase::PoolAcquire, "pool_acquire"),
    (OpenPhase::SchemaVersion, "schema_version"),
    (OpenPhase::InitialSchema, "initial_schema"),
    (OpenPhase::Migrations, "migrations"),
    (OpenPhase::CipherRead, "cipher_read"),
    (OpenPhase::CipherWait, "cipher_wait"),
    (OpenPhase::CipherSave, "cipher_save"),
    (OpenPhase::Checkpoint, "checkpoint"),
    (OpenPhase::MetadataRead, "metadata_read"),
    (OpenPhase::RuntimeConfig, "runtime_config"),
    (OpenPhase::Complete, "complete"),
];

#[derive(Clone, Copy)]
pub(super) enum WorkerPhase {
    Unobserved,
    Submitted,
    Started,
    Returned,
}

const WORKER_LABELS: [(WorkerPhase, &str); 4] = [
    (WorkerPhase::Unobserved, "unobserved"),
    (WorkerPhase::Submitted, "submitted"),
    (WorkerPhase::Started, "started"),
    (WorkerPhase::Returned, "returned"),
];

impl SqliteStoreOpenDiagnostics {
    /// Read the owner and worker slots without waiting for store or worker work.
    pub fn snapshot(&self) -> ([&'static str; 4], [&'static str; 4]) {
        let owner = StoreRole::ALL.map(|role| {
            let value = self.progress.owner[role as usize].load(Ordering::Relaxed);
            OWNER_LABELS
                .get(usize::from(value))
                .map_or("unknown", |(_, label)| *label)
        });
        let worker = StoreRole::ALL.map(|role| {
            let value = self.progress.worker[role as usize].load(Ordering::Relaxed);
            WORKER_LABELS
                .get(usize::from(value))
                .map_or("unknown", |(_, label)| *label)
        });
        (owner, worker)
    }
}

#[derive(Clone)]
pub(super) struct OpenTrace {
    diagnostics: SqliteStoreOpenDiagnostics,
    role: StoreRole,
}

impl OpenTrace {
    pub(super) fn worker(&self, phase: WorkerPhase) {
        self.diagnostics.progress.worker[self.role as usize]
            .store(phase as u8, Ordering::Relaxed);
    }
}

tokio::task_local! {
    static CURRENT: Option<OpenTrace>;
}

pub(super) async fn observe_store_open<F: Future>(
    diagnostics: Option<&SqliteStoreOpenDiagnostics>,
    role: StoreRole,
    work: F,
) -> F::Output {
    if diagnostics.is_none() && !CURRENT.try_with(Option::is_some).unwrap_or_default() {
        return work.await;
    }
    // An unobserved nested open must not write into its caller's observer.
    let trace = diagnostics.map(|diagnostics| OpenTrace {
        diagnostics: diagnostics.clone(),
        role,
    });
    CURRENT.scope(trace, work).await
}

pub(super) fn record_open_phase(phase: OpenPhase) {
    let _ = CURRENT.try_with(|trace| {
        if let Some(trace) = trace {
            trace.diagnostics.progress.owner[trace.role as usize]
                .store(phase as u8, Ordering::Relaxed);
        }
    });
}

pub(super) fn capture_open_trace() -> Option<OpenTrace> {
    CURRENT.try_with(Clone::clone).ok().flatten()
}

#[cfg(test)]
#[path = "open_diagnostics_tests.rs"]
mod tests;
