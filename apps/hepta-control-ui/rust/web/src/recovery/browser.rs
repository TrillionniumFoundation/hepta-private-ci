use super::*;
use crate::transport::deadline::Deadline;
use js_sys::{JsString, Object, Promise, Reflect, Uint8Array};
use std::cell::RefCell;
use wasm_bindgen::{JsCast, JsValue, closure::Closure, prelude::wasm_bindgen};
use wasm_bindgen_futures::JsFuture;
use web_sys::{AbortSignal, Storage, Url};

// Web Locks remains behind web-sys's unstable flag. These are only Web API bindings;
// lock admission and crash-recovery policy remain entirely in Rust.
#[wasm_bindgen]
extern "C" {
    #[wasm_bindgen(extends = Object, typescript_type = "LockManager")]
    #[derive(Clone)]
    type BrowserLocks;
    #[wasm_bindgen(extends = Object, typescript_type = "Storage")]
    type RawStorage;
    #[wasm_bindgen(method, catch, structural, js_name = getItem)]
    fn get_raw(this: &RawStorage, key: &str) -> Result<JsValue, JsValue>;
    #[wasm_bindgen(method, catch, structural, js_name = request)]
    fn request(
        this: &BrowserLocks,
        name: &str,
        options: &Object,
        callback: &js_sys::Function,
    ) -> Result<Promise, JsValue>;
}

struct BrowserStorage(Storage);
impl StorageIo for BrowserStorage {
    fn get(&self, key: &str, reason: &'static str) -> Result<Option<String>, ControlError> {
        let value = self
            .0
            .unchecked_ref::<RawStorage>()
            .get_raw(key)
            .map_err(|_| failure(reason))?;
        if value.is_null() {
            return Ok(None);
        }
        let value = value.dyn_into::<JsString>().map_err(|_| failure(reason))?;
        let (limit, oversized) = if key.starts_with(DIRECTORY_SCHEMA) {
            (MAX_DIRECTORY_BYTES, "directory_oversized")
        } else {
            (MAX_RECORD_BYTES, "record_oversized")
        };
        if value.length() as usize > limit {
            return Err(failure(oversized));
        }
        // wasm-bindgen's String conversion replaces lone surrogates; never let
        // that silently alter a persisted operation's exact semantic identity.
        if !value.is_valid_utf16() {
            return Err(failure("record_corrupt"));
        }
        Ok(Some(value.into()))
    }
    fn set(&self, key: &str, value: &str, reason: &'static str) -> Result<(), ControlError> {
        self.0.set_item(key, value).map_err(|_| failure(reason))
    }
    fn remove(&self, key: &str, reason: &'static str) -> Result<(), ControlError> {
        self.0.remove_item(key).map_err(|_| failure(reason))
    }
    fn len(&self) -> Result<u32, ControlError> {
        self.0
            .length()
            .map_err(|_| failure("migration_inventory_read_failed"))
    }
    fn key(&self, index: u32) -> Result<Option<String>, ControlError> {
        self.0
            .key(index)
            .map_err(|_| failure("migration_enumeration_failed"))
    }
}

/// One authenticated endpoint/principal/protocol/namespace, shared safely across tabs.
#[derive(Clone)]
pub struct ScopedRecoveryStore {
    engine: Rc<Engine>,
    locks: BrowserLocks,
}

/// A durable, read-back admission receipt for exactly one immutable record.
pub struct PreparedRecovery {
    store: ScopedRecoveryStore,
    record: PreparedRecord,
}

impl ScopedRecoveryStore {
    pub async fn create(
        endpoint: &str,
        identity_id: &str,
        protocol_version: &str,
        namespace: &str,
        max_entries: usize,
    ) -> Result<Self, ControlError> {
        let window = web_sys::window().ok_or_else(|| failure("storage_or_lock_unavailable"))?;
        let storage = window
            .local_storage()
            .map_err(|_| failure("storage_or_lock_unavailable"))?
            .ok_or_else(|| failure("storage_or_lock_unavailable"))?;
        let locks = Reflect::get(window.navigator().as_ref(), &JsValue::from_str("locks"))
            .map_err(|_| failure("storage_or_lock_unavailable"))?;
        if locks.is_null()
            || locks.is_undefined()
            || !Reflect::get(&locks, &JsValue::from_str("request"))
                .map_err(|_| failure("storage_or_lock_unavailable"))?
                .is_function()
        {
            return Err(failure("storage_or_lock_unavailable"));
        }
        let url = Url::new(endpoint).map_err(|_| failure("endpoint_invalid"))?;
        if !matches!(url.protocol().as_str(), "https:" | "http:")
            || !url.username().is_empty()
            || !url.password().is_empty()
            || !url.search().is_empty()
            || !url.hash().is_empty()
        {
            return Err(failure("endpoint_invalid"));
        }
        let binding = serde_json::to_string(&json!([
            SCHEMA,
            url.href(),
            recovery_identifier(namespace)?,
            recovery_identifier(identity_id)?,
            recovery_identifier(protocol_version)?
        ]))
        .map_err(|_| failure("identity_invalid"))?;
        let crypto = window
            .crypto()
            .map_err(|_| failure("scope_digest_unavailable"))?;
        let promise = crypto
            .subtle()
            .digest_with_str_and_u8_array("SHA-256", binding.as_bytes())
            .map_err(|_| failure("scope_digest_unavailable"))?;
        let digest = Uint8Array::new(
            &JsFuture::from(promise)
                .await
                .map_err(|_| failure("scope_digest_unavailable"))?,
        )
        .to_vec();
        let scope_digest: String = digest.iter().map(|byte| format!("{byte:02x}")).collect();
        let store = Self {
            engine: Rc::new(Engine::new(
                Rc::new(BrowserStorage(storage)),
                scope_digest,
                max_entries,
            )?),
            locks: locks.unchecked_into(),
        };
        if store.engine.needs_initialization()? {
            let engine = store.engine.clone();
            store
                .with_lock(None, move || engine.initialize_locked())
                .await?;
        }
        Ok(store)
    }

    pub fn load(&self) -> Result<Value, ControlError> {
        self.engine.load()
    }
    pub fn diagnostics(&self) -> Result<Value, ControlError> {
        self.engine.diagnostics()
    }

    pub async fn prepare(
        &self,
        operation: &Value,
        signal: Option<AbortSignal>,
    ) -> Result<PreparedRecovery, ControlError> {
        let operation = operation.clone();
        let engine = self.engine.clone();
        let record = self
            .with_lock(signal, move || engine.prepare_locked(&operation))
            .await?;
        Ok(PreparedRecovery {
            store: self.clone(),
            record,
        })
    }

    pub async fn complete(
        &self,
        operation: &Value,
        signal: Option<AbortSignal>,
    ) -> Result<bool, ControlError> {
        if operation.get("state").and_then(Value::as_str) != Some("terminal") {
            return Ok(false);
        }
        let operation = operation.clone();
        let engine = self.engine.clone();
        self.with_lock(signal, move || engine.complete_locked(&operation))
            .await
    }

    async fn with_lock<T: 'static>(
        &self,
        signal: Option<AbortSignal>,
        work: impl FnOnce() -> Result<T, ControlError> + 'static,
    ) -> Result<T, ControlError> {
        let deadline = Deadline::new(signal, 5000).map_err(|_| failure("lock_unavailable"))?;
        let options = Object::new();
        Reflect::set(
            &options,
            &JsValue::from_str("mode"),
            &JsValue::from_str("exclusive"),
        )
        .map_err(|_| failure("lock_unavailable"))?;
        Reflect::set(
            &options,
            &JsValue::from_str("signal"),
            deadline.signal().as_ref(),
        )
        .map_err(|_| failure("lock_unavailable"))?;
        let result = Rc::new(RefCell::new(None));
        let captured = result.clone();
        let mut work = Some(work);
        let callback = Closure::wrap(Box::new(move |_: JsValue| {
            if let Some(work) = work.take() {
                *captured.borrow_mut() = Some(work());
            }
            JsValue::UNDEFINED
        }) as Box<dyn FnMut(JsValue) -> JsValue>);
        let request = self
            .locks
            .request(
                &self.engine.prefix,
                &options,
                callback.as_ref().unchecked_ref(),
            )
            .map_err(|_| failure("lock_unavailable"))?;
        // Await the actual lock promise, not a competing timer promise: never drop a
        // callback while the LockManager still owns it. Its AbortSignal bounds acquisition.
        let settled = JsFuture::from(request).await;
        let result = result.borrow_mut().take();
        drop(callback);
        drop(deadline);
        match (result, settled) {
            (Some(Err(error)), _) => Err(error),
            (Some(Ok(value)), Ok(_)) => Ok(value),
            (Some(Ok(_)), Err(_)) => Err(failure("lock_completion_failed")),
            (None, _) => Err(failure("lock_unavailable")),
        }
    }
}

impl PreparedRecovery {
    /// Caller must use this only for a definitely-not-accepted outcome; never for timeouts.
    pub async fn discard_rejected(&self) -> Result<bool, ControlError> {
        let engine = self.store.engine.clone();
        let record = self.record.clone();
        self.store
            .with_lock(None, move || engine.discard_locked(&record))
            .await
    }
}
