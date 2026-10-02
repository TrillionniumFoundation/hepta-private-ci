//! Executor boundary: native Tokio workers and the SDK's browser-local executor.
use std::future::Future;
use matrix_sdk_common::{executor::JoinHandle, SendOutsideWasm};

#[cfg(not(target_family = "wasm"))]
pub use tokio::runtime::Handle;

#[cfg(not(target_family = "wasm"))]
pub fn handle() -> Handle {
    static RUNTIME: std::sync::LazyLock<tokio::runtime::Runtime> = std::sync::LazyLock::new(|| {
        tokio::runtime::Runtime::new().expect("Failed to create Matrix runtime")
    });
    RUNTIME.handle().clone()
}

#[cfg(target_family = "wasm")]
#[derive(Clone, Copy)]
pub struct Handle;

#[cfg(target_family = "wasm")]
pub fn handle() -> Handle {
    Handle
}

#[cfg(target_family = "wasm")]
impl Handle {
    pub fn spawn<F, T>(&self, future: F) -> JoinHandle<T>
    where
        F: Future<Output = T> + SendOutsideWasm + 'static,
        T: 'static,
    {
        browser_tasks::spawn_for_epoch(crate::ui_dispatch::origin_epoch(), future)
    }
}

/// Native paths are never interpreted as browser filesystem paths.
/// The browser file picker must provide bytes through a dedicated upload adapter.
pub async fn read_file(path: impl AsRef<std::path::Path>) -> std::io::Result<Vec<u8>> {
    #[cfg(not(target_family = "wasm"))]
    {
        tokio::fs::read(path).await
    }
    #[cfg(target_family = "wasm")]
    {
        let _ = path;
        Err(std::io::Error::new(
            std::io::ErrorKind::Unsupported,
            "Browser file uploads require a browser file-picker adapter",
        ))
    }
}

/// Use the same platform clock as Ruma's RetryAfter timestamp.
#[cfg(not(target_family = "wasm"))]
pub fn system_time_now() -> std::time::SystemTime { std::time::SystemTime::now() }
#[cfg(target_family = "wasm")]
pub fn system_time_now() -> web_time::SystemTime { web_time::SystemTime::now() }

/// Browser SDK errors can contain local-only JS state. Project their display
/// description at the anyhow boundary; retain typed native error sources.
#[cfg(not(target_family = "wasm"))]
pub fn sdk_error<E: std::error::Error + Send + Sync + 'static>(error: E) -> anyhow::Error {
    anyhow::Error::new(error)
}
#[cfg(target_family = "wasm")]
pub fn sdk_error(error: impl std::fmt::Display) -> anyhow::Error {
    anyhow::anyhow!(error.to_string())
}

/// Lifetime control loops must remain alive across account transitions.
pub fn spawn_control<F, T>(future: F) -> JoinHandle<T>
where F: Future<Output = T> + SendOutsideWasm + 'static, T: SendOutsideWasm + 'static {
    #[cfg(not(target_family = "wasm"))]
    { handle().spawn(future) }
    #[cfg(target_family = "wasm")]
    { matrix_sdk_common::executor::spawn(future) }
}

/// Callback-created tasks retain the authority of the registering client.
pub fn spawn_for_epoch<F, T>(epoch: u64, future: F) -> JoinHandle<T>
where F: Future<Output = T> + SendOutsideWasm + 'static, T: SendOutsideWasm + 'static {
    #[cfg(not(target_family = "wasm"))]
    { let _ = epoch; handle().spawn(future) }
    #[cfg(target_family = "wasm")]
    { browser_tasks::spawn_for_epoch(epoch, future) }
}

/// Retire account work before replacing/clearing globally accessible authority.
pub fn advance_authority() {
    #[cfg(target_family = "wasm")]
    {
        crate::ui_dispatch::advance_epoch();
        browser_tasks::retire_previous_epochs(crate::ui_dispatch::current_epoch());
    }
}

#[cfg(target_family = "wasm")]
mod browser_tasks {
    use super::*;
    use std::cell::{Cell, RefCell};
    use std::collections::HashMap;
    use matrix_sdk_common::executor::AbortHandle;

    const MAX_ACCOUNT_TASKS: usize = 8192;
    tokio::task_local! { static CURRENT_TASK: u64; }
    thread_local! {
        static NEXT_ID: Cell<u64> = const { Cell::new(0) };
        static TASKS: RefCell<HashMap<u64, (u64, AbortHandle)>> = RefCell::new(HashMap::new());
    }
    struct Registration(u64);
    impl Drop for Registration {
        fn drop(&mut self) { TASKS.with(|tasks| { tasks.borrow_mut().remove(&self.0); }); }
    }

    pub(super) fn spawn_for_epoch<F, T>(epoch: u64, future: F) -> JoinHandle<T>
    where F: Future<Output = T> + 'static, T: 'static {
        let id = NEXT_ID.with(|next| { let id = next.get().wrapping_add(1); next.set(id); id });
        let registration = Registration(id);
        let scoped = crate::ui_dispatch::scope_epoch(epoch, CURRENT_TASK.scope(id, async move {
            let _registration = registration;
            future.await
        }));
        let task = matrix_sdk_common::executor::spawn(scoped);
        let accepted = TASKS.with(|tasks| {
            let mut tasks = tasks.borrow_mut();
            if epoch != crate::ui_dispatch::current_epoch() || tasks.len() >= MAX_ACCOUNT_TASKS { return false; }
            tasks.insert(id, (epoch, task.abort_handle()));
            true
        });
        if !accepted {
            task.abort();
            makepad_widgets::error!("Rejected stale or over-capacity browser account task");
        }
        task
    }

    pub(super) fn retire_previous_epochs(epoch: u64) {
        let current = CURRENT_TASK.try_with(|id| *id).ok();
        let obsolete = TASKS.with(|tasks| {
            let mut tasks = tasks.borrow_mut();
            let mut obsolete = Vec::new();
            tasks.retain(|id, (task_epoch, abort)| {
                if Some(*id) == current { *task_epoch = epoch; return true; }
                if *task_epoch != epoch { obsolete.push(abort.clone()); false } else { true }
            });
            obsolete
        });
        // Abort outside the RefCell borrow; future destruction removes its registration.
        for task in obsolete { task.abort(); }
    }
}

#[cfg(all(test, target_family = "wasm"))]
mod tests {
    use super::*;
    use wasm_bindgen_test::wasm_bindgen_test;

    #[wasm_bindgen_test]
    async fn authority_transition_aborts_old_account_work() {
        let old = handle().spawn(std::future::pending::<()>());
        advance_authority();
        assert!(old.await.unwrap_err().is_cancelled());
    }

    #[wasm_bindgen_test]
    async fn old_account_cannot_mutate_after_an_await() {
        let started = std::rc::Rc::new(tokio::sync::Notify::new());
        let resume = std::rc::Rc::new(tokio::sync::Notify::new());
        let mutated = std::rc::Rc::new(std::cell::Cell::new(false));
        let task = handle().spawn({
            let started = started.clone();
            let resume = resume.clone();
            let mutated = mutated.clone();
            async move {
                started.notify_one();
                resume.notified().await;
                mutated.set(true);
            }
        });
        started.notified().await;
        advance_authority();
        resume.notify_one();
        assert!(task.await.unwrap_err().is_cancelled());
        assert!(!mutated.get());
    }

    #[wasm_bindgen_test]
    async fn delayed_account_setup_cannot_install_after_shutdown() {
        // Mirrors the lifetime control -> run_account(initializer) boundary.
        // The paused step stands for supported_versions/SyncService::build.
        let started = std::rc::Rc::new(tokio::sync::Notify::new());
        let resume = std::rc::Rc::new(tokio::sync::Notify::new());
        let effects = std::rc::Rc::new(std::cell::Cell::new((false, false, false)));
        let control = spawn_control({
            let started = started.clone();
            let resume = resume.clone();
            let effects = effects.clone();
            async move {
                run_account(async move {
                    started.notify_one();
                    resume.notified().await;
                    // Global service install, LoginSuccess, send-queue enable.
                    effects.set((true, true, true));
                    Ok(())
                }).await
            }
        });
        started.notified().await;
        advance_authority();
        resume.notify_one();
        assert!(control.await.unwrap().is_err());
        assert_eq!(effects.get(), (false, false, false));
    }

    #[wasm_bindgen_test]
    async fn active_logout_task_survives_its_own_transition() {
        let logout = handle().spawn(async {
            let previous = crate::ui_dispatch::origin_epoch();
            advance_authority();
            assert_ne!(crate::ui_dispatch::origin_epoch(), previous);
            assert_eq!(crate::ui_dispatch::origin_epoch(), crate::ui_dispatch::current_epoch());
            42
        });
        assert_eq!(logout.await.unwrap(), 42);
    }

    #[wasm_bindgen_test]
    async fn stale_registered_callback_is_cancelled_before_execution() {
        let old_epoch = crate::ui_dispatch::current_epoch();
        advance_authority();
        let callback = spawn_for_epoch(old_epoch, async { panic!("Stale callback executed") });
        assert!(callback.await.unwrap_err().is_cancelled());
    }
}

/// Native has no browser epoch boundary; retain its existing multithread model.
pub fn current_epoch() -> u64 {
    #[cfg(not(target_family = "wasm"))] { 0 }
    #[cfg(target_family = "wasm")] { crate::ui_dispatch::current_epoch() }
}
pub fn origin_epoch() -> u64 {
    #[cfg(not(target_family = "wasm"))] { 0 }
    #[cfg(target_family = "wasm")] { crate::ui_dispatch::origin_epoch() }
}

/// Await one cancellable account operation from a lifetime control loop.
pub async fn run_account<F, T>(future: F) -> anyhow::Result<T>
where F: Future<Output = anyhow::Result<T>> + SendOutsideWasm + 'static,
      T: SendOutsideWasm + 'static {
    handle().spawn(future).await.map_err(|error| anyhow::anyhow!("Account operation ended: {error}"))?
}
