#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "codex-rs/hepta-infer-worker-host/src/model_worker.rs"
TESTS = ROOT / "codex-rs/hepta-infer-worker-host/src/model_worker_tests.rs"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def patch_model() -> None:
    s = MODEL.read_text()
    s = replace_once(
        s,
        """    ModelAlreadyLoaded,
    ModelNotLoaded,
    ModelMismatch,""",
        """    ModelAlreadyLoaded,
    ModelNotLoaded,
    ModelCleanupPending,
    ModelMismatch,""",
        "model cleanup error",
    )
    s = replace_once(
        s,
        """    FeatureOutputMismatch,
    FeatureContract,
}""",
        """    FeatureOutputMismatch,
    FeatureContract,
    CleanupPending(String),
}""",
        "cleanup pending error",
    )
    s = replace_once(
        s,
        """#[derive(Debug)]
struct LoadedModel {
    manifest: ModelManifest,
    handle: DriverModelHandle,
    active_requests: usize,
}""",
        """#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ModelLifecycle {
    Active,
    CleanupRequired,
}

#[derive(Debug)]
struct LoadedModel {
    manifest: ModelManifest,
    handle: DriverModelHandle,
    active_requests: usize,
    lifecycle: ModelLifecycle,
}""",
        "model lifecycle",
    )
    s = replace_once(
        s,
        """    models: BTreeMap<String, LoadedModel>,
    active_requests: BTreeMap<String, String>,
}""",
        """    models: BTreeMap<String, LoadedModel>,
    active_requests: BTreeMap<String, String>,
    resident_memory_bytes: u128,
}""",
        "resident memory field",
    )
    s = replace_once(
        s,
        """            models: BTreeMap::new(),
            active_requests: BTreeMap::new(),
        })""",
        """            models: BTreeMap::new(),
            active_requests: BTreeMap::new(),
            resident_memory_bytes: 0,
        })""",
        "resident memory initialization",
    )
    s = replace_once(
        s,
        """    pub fn worker_id(&self) -> &str {
        &self.worker_id
    }""",
        """    pub fn worker_id(&self) -> &str {
        &self.worker_id
    }

    #[must_use]
    pub fn resident_memory_bytes(&self) -> u128 {
        self.resident_memory_bytes
    }""",
        "resident memory getter",
    )
    s = replace_once(
        s,
        """        let handle = self.driver.load(&manifest)?;
        validate_identity(&handle.opaque_id, "model handle")?;
        if handle.observed_memory_bytes > self.grant.maximum_memory_bytes {
            self.driver.unload(handle)?;
            return Err(Error::ModelCapacity);
        }
        let observation = ModelLoadObservation {
            model_id: manifest.model_id.clone(),
            worker_generation: self.generation,
            handle_id: handle.opaque_id.clone(),
            observed_memory_bytes: handle.observed_memory_bytes,
            terminal_observed: true,
        };
        self.models.insert(
            manifest.model_id.clone(),
            LoadedModel {
                manifest,
                handle,
                active_requests: 0,
            },
        );
        Ok(observation)""",
        """        let handle = self.driver.load(&manifest)?;
        let next_resident_memory = self
            .resident_memory_bytes
            .checked_add(u128::from(handle.observed_memory_bytes))
            .ok_or(Error::ArithmeticOverflow)?;
        let post_load_error = validate_identity(&handle.opaque_id, "model handle")
            .err()
            .or_else(|| {
                (next_resident_memory > u128::from(self.grant.maximum_memory_bytes))
                    .then_some(Error::ModelCapacity)
            });
        if let Some(load_error) = post_load_error {
            if let Err(cleanup_error) = self.driver.unload(handle.clone()) {
                self.resident_memory_bytes = next_resident_memory;
                self.models.insert(
                    manifest.model_id.clone(),
                    LoadedModel {
                        manifest,
                        handle,
                        active_requests: 0,
                        lifecycle: ModelLifecycle::CleanupRequired,
                    },
                );
                return Err(Error::CleanupPending(format!(
                    "post-load validation failed ({load_error}); cleanup failed ({cleanup_error})"
                )));
            }
            return Err(load_error);
        }
        let observation = ModelLoadObservation {
            model_id: manifest.model_id.clone(),
            worker_generation: self.generation,
            handle_id: handle.opaque_id.clone(),
            observed_memory_bytes: handle.observed_memory_bytes,
            terminal_observed: true,
        };
        self.resident_memory_bytes = next_resident_memory;
        self.models.insert(
            manifest.model_id.clone(),
            LoadedModel {
                manifest,
                handle,
                active_requests: 0,
                lifecycle: ModelLifecycle::Active,
            },
        );
        Ok(observation)""",
        "load lifecycle",
    )
    s = replace_once(
        s,
        """        let loaded = self.models.get_mut(model_id).ok_or(Error::ModelNotLoaded)?;
        if request.model_digest != loaded.manifest.model_digest""",
        """        let loaded = self.models.get_mut(model_id).ok_or(Error::ModelNotLoaded)?;
        if loaded.lifecycle != ModelLifecycle::Active {
            return Err(Error::ModelCleanupPending);
        }
        if request.model_digest != loaded.manifest.model_digest""",
        "normal run cleanup fence",
    )
    s = replace_once(
        s,
        """    pub fn unload_model(
        &mut self,
        now_ms: u64,
        model_id: &str,
    ) -> Result<ModelUnloadObservation, Error> {
        self.validate_current_grant(now_ms)?;
        validate_identity(model_id, "model")?;
        let loaded = self.models.get(model_id).ok_or(Error::ModelNotLoaded)?;
        if loaded.active_requests != 0 {
            return Err(Error::ActiveRequests);
        }
        let loaded = self.models.remove(model_id).ok_or(Error::ModelNotLoaded)?;
        self.driver.unload(loaded.handle)?;
        Ok(ModelUnloadObservation {
            model_id: model_id.to_string(),
            worker_generation: self.generation,
            terminal_observed: true,
        })
    }""",
        """    pub fn unload_model(
        &mut self,
        _now_ms: u64,
        model_id: &str,
    ) -> Result<ModelUnloadObservation, Error> {
        validate_identity(model_id, "model")?;
        let (handle, observed_memory_bytes) = {
            let loaded = self
                .models
                .get_mut(model_id)
                .ok_or(Error::ModelNotLoaded)?;
            if loaded.active_requests != 0 {
                return Err(Error::ActiveRequests);
            }
            // Cleanup is capability-reducing and remains permitted after the
            // execution grant expires or is revoked. Once requested, the model
            // cannot return to Active unless it is loaded again under a new grant.
            loaded.lifecycle = ModelLifecycle::CleanupRequired;
            (loaded.handle.clone(), loaded.handle.observed_memory_bytes)
        };
        self.driver.unload(handle)?;
        self.models.remove(model_id).ok_or(Error::ModelNotLoaded)?;
        self.resident_memory_bytes = self
            .resident_memory_bytes
            .checked_sub(u128::from(observed_memory_bytes))
            .ok_or(Error::ArithmeticOverflow)?;
        Ok(ModelUnloadObservation {
            model_id: model_id.to_string(),
            worker_generation: self.generation,
            terminal_observed: true,
        })
    }""",
        "unload lifecycle",
    )
    s = replace_once(
        s,
        """        let loaded = self.models.get_mut(model_id).ok_or(Error::ModelNotLoaded)?;
        if request.authorization.model_digest != loaded.manifest.model_digest""",
        """        let loaded = self.models.get_mut(model_id).ok_or(Error::ModelNotLoaded)?;
        if loaded.lifecycle != ModelLifecycle::Active {
            return Err(Error::ModelCleanupPending);
        }
        if request.authorization.model_digest != loaded.manifest.model_digest""",
        "neuron cleanup fence",
    )
    MODEL.write_text(s)


def patch_tests() -> None:
    s = TESTS.read_text()
    s = replace_once(
        s,
        """#[derive(Debug, Default)]
struct Driver {
    fail_terminal: bool,
    indeterminate: bool,
    corrupt_neuron_head: bool,
    loaded: usize,
}""",
        """#[derive(Debug)]
struct Driver {
    fail_terminal: bool,
    indeterminate: bool,
    corrupt_neuron_head: bool,
    fail_unload: bool,
    invalid_handle: bool,
    load_memory_bytes: u64,
    loaded: usize,
    unload_attempts: usize,
}

impl Default for Driver {
    fn default() -> Self {
        Self {
            fail_terminal: false,
            indeterminate: false,
            corrupt_neuron_head: false,
            fail_unload: false,
            invalid_handle: false,
            load_memory_bytes: 1_024,
            loaded: 0,
            unload_attempts: 0,
        }
    }
}""",
        "test driver state",
    )
    s = replace_once(
        s,
        """        Ok(DriverModelHandle {
            opaque_id: format!("handle.{}", manifest.model_id),
            observed_memory_bytes: 1_024,
        })""",
        """        Ok(DriverModelHandle {
            opaque_id: if self.invalid_handle {
                String::new()
            } else {
                format!("handle.{}", manifest.model_id)
            },
            observed_memory_bytes: self.load_memory_bytes,
        })""",
        "test load handle",
    )
    s = replace_once(
        s,
        """    fn unload(&mut self, _handle: DriverModelHandle) -> Result<(), Error> {
        self.loaded = self.loaded.saturating_sub(1);
        Ok(())
    }""",
        """    fn unload(&mut self, _handle: DriverModelHandle) -> Result<(), Error> {
        self.unload_attempts += 1;
        if self.fail_unload {
            return Err(Error::DriverFailure("unload failed".to_string()));
        }
        self.loaded = self.loaded.saturating_sub(1);
        Ok(())
    }""",
        "test unload behavior",
    )
    insertion = """#[test]
fn lost_driver_terminality_is_indeterminate() {
    let driver = Driver {
        indeterminate: true,
        ..Driver::default()
    };
    let mut worker =
        InferenceWorker::new(100, "worker.1".to_string(), 3, grant(), driver).expect("worker");
    worker.load_model(100, manifest()).expect("load");
    let observed = worker.run(100, "model.1", request()).expect("run");
    assert_eq!(observed.status, ExecutionStatus::Indeterminate);
    assert!(!observed.terminal_observed);
    assert_eq!(observed.output_digest, None);
}
"""
    additions = insertion + """
#[test]
fn aggregate_resident_memory_cannot_exceed_grant() {
    let mut constrained = grant();
    constrained.maximum_memory_bytes = 1_500;
    let mut worker = InferenceWorker::new(
        100,
        "worker.memory".to_string(),
        3,
        constrained,
        Driver::default(),
    )
    .expect("worker");
    worker.load_model(100, manifest()).expect("first load");

    let mut second = manifest();
    second.model_id = "model.2".to_string();
    assert_eq!(worker.load_model(100, second), Err(Error::ModelCapacity));
    assert_eq!(worker.resident_memory_bytes(), 1_024);
    assert_eq!(worker.models.len(), 1);
    assert_eq!(worker.driver.loaded, 1);
    assert_eq!(worker.driver.unload_attempts, 1);
}

#[test]
fn expired_or_revoked_grant_never_blocks_cleanup() {
    let mut expired = InferenceWorker::new(
        100,
        "worker.expired".to_string(),
        3,
        grant(),
        Driver::default(),
    )
    .expect("worker");
    expired.load_model(100, manifest()).expect("load");
    expired
        .unload_model(10_000, "model.1")
        .expect("expired grant cleanup");
    assert_eq!(expired.resident_memory_bytes(), 0);

    let mut revoked = InferenceWorker::new(
        100,
        "worker.revoked".to_string(),
        3,
        grant(),
        Driver::default(),
    )
    .expect("worker");
    revoked.load_model(100, manifest()).expect("load");
    revoked.grant.revoked = true;
    revoked
        .unload_model(100, "model.1")
        .expect("revoked grant cleanup");
    assert_eq!(revoked.resident_memory_bytes(), 0);
}

#[test]
fn failed_unload_retains_handle_for_retry_and_fences_execution() {
    let driver = Driver {
        fail_unload: true,
        ..Driver::default()
    };
    let mut worker =
        InferenceWorker::new(100, "worker.retry".to_string(), 3, grant(), driver).expect("worker");
    worker.load_model(100, manifest()).expect("load");

    assert_eq!(
        worker.unload_model(100, "model.1"),
        Err(Error::DriverFailure("unload failed".to_string()))
    );
    assert_eq!(worker.models.len(), 1);
    assert_eq!(
        worker.models["model.1"].lifecycle,
        ModelLifecycle::CleanupRequired
    );
    assert_eq!(worker.resident_memory_bytes(), 1_024);
    assert_eq!(
        worker.run(100, "model.1", request()),
        Err(Error::ModelCleanupPending)
    );

    worker.driver.fail_unload = false;
    worker
        .unload_model(10_000, "model.1")
        .expect("cleanup retry after expiry");
    assert!(worker.models.is_empty());
    assert_eq!(worker.resident_memory_bytes(), 0);
}

#[test]
fn post_load_validation_failure_cleans_or_tracks_acquired_resources() {
    let driver = Driver {
        invalid_handle: true,
        ..Driver::default()
    };
    let mut cleaned =
        InferenceWorker::new(100, "worker.invalid-clean".to_string(), 3, grant(), driver)
            .expect("worker");
    assert_eq!(
        cleaned.load_model(100, manifest()),
        Err(Error::InvalidIdentity("model handle"))
    );
    assert!(cleaned.models.is_empty());
    assert_eq!(cleaned.resident_memory_bytes(), 0);
    assert_eq!(cleaned.driver.unload_attempts, 1);

    let driver = Driver {
        invalid_handle: true,
        fail_unload: true,
        ..Driver::default()
    };
    let mut tracked =
        InferenceWorker::new(100, "worker.invalid-track".to_string(), 3, grant(), driver)
            .expect("worker");
    assert!(matches!(
        tracked.load_model(100, manifest()),
        Err(Error::CleanupPending(_))
    ));
    assert_eq!(
        tracked.models["model.1"].lifecycle,
        ModelLifecycle::CleanupRequired
    );
    assert_eq!(tracked.resident_memory_bytes(), 1_024);
    tracked.driver.fail_unload = false;
    tracked
        .unload_model(10_000, "model.1")
        .expect("tracked cleanup retry");
    assert!(tracked.models.is_empty());
}
"""
    s = replace_once(s, insertion, additions, "resource lifecycle regressions")
    TESTS.write_text(s)


patch_model()
patch_tests()
