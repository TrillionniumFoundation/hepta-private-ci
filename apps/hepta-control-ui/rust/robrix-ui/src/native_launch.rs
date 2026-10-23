//! Shared admission for the two mutually exclusive modes of the original App.
//! An observation-only composition never implements or installs NativeHost.

use makepad_widgets::*;
use std::cell::{Cell, RefCell};
use std::rc::Rc;
use std::sync::Arc;

#[derive(Default)]
pub(crate) struct RunOutcome {
    pub(crate) adopted: bool,
    pub(crate) exited: bool,
    pub(crate) error: Option<String>,
}

pub(crate) enum LaunchMode {
    #[cfg(feature = "native-host")]
    OwnerHost(Box<dyn crate::native_host::NativeHost>),
    #[cfg(feature = "native-presentation")]
    Presentation(crate::native_presentation::OwnedComposition),
}

pub(crate) type ConfigureResources = Box<dyn FnOnce(&mut Cx)>;

pub(crate) struct Setup {
    pub(crate) mode: LaunchMode,
    resources: Option<ConfigureResources>,
    pub(crate) outcome: Rc<RefCell<RunOutcome>>,
}

thread_local! {
    static RUNNING: Cell<bool> = const { Cell::new(false) };
    static PENDING: RefCell<Option<Setup>> = const { RefCell::new(None) };
}

#[derive(Default)]
struct LaunchSlot(Option<Setup>);

/// Keeps the existing Linux event-loop scope and cleanup. Both native modes
/// use this admission, so a reentrant caller cannot replace a pending owner.
#[cfg(target_os = "linux")]
pub(crate) fn run(mode: LaunchMode, resources: ConfigureResources) -> Result<(), String> {
    run_with_loop(mode, resources, crate::app::app_main)
}

#[cfg(target_os = "linux")]
fn run_with_loop(
    mode: LaunchMode,
    resources: ConfigureResources,
    event_loop: impl FnOnce(),
) -> Result<(), String> {
    if RUNNING.with(|running| running.replace(true)) {
        return Err("a native Robrix host is already running on this thread".into());
    }
    struct Reset;
    impl Drop for Reset {
        fn drop(&mut self) {
            PENDING.with(|slot| slot.borrow_mut().take());
            RUNNING.with(|running| running.set(false));
        }
    }
    let _reset = Reset;
    let outcome = Rc::new(RefCell::new(RunOutcome::default()));
    PENDING.with(|slot| {
        *slot.borrow_mut() = Some(Setup {
            mode,
            resources: Some(resources),
            outcome: Rc::clone(&outcome),
        });
    });
    event_loop();
    let outcome = outcome.borrow();
    if let Some(error) = &outcome.error {
        return Err(error.clone());
    }
    if !outcome.adopted || !outcome.exited {
        return Err("native Robrix host did not complete its renderer lifecycle".into());
    }
    Ok(())
}

pub(crate) fn configure(cx: &mut Cx) {
    if let Some(mut setup) = PENDING.with(|slot| slot.borrow_mut().take()) {
        setup
            .resources
            .take()
            .expect("native resources are configured once")(cx);
        let waker: Arc<dyn Fn() + Send + Sync> = Arc::new(SignalToUI::set_ui_signal);
        match &mut setup.mode {
            #[cfg(feature = "native-host")]
            LaunchMode::OwnerHost(host) => host.set_waker(waker),
            #[cfg(feature = "native-presentation")]
            LaunchMode::Presentation(composition) => composition.inner.set_waker(waker),
        }
        cx.set_global(LaunchSlot(Some(setup)));
    }
}

pub(crate) fn take(cx: &mut Cx) -> Option<Setup> {
    cx.global::<LaunchSlot>().0.take()
}

#[cfg(all(test, feature = "native-presentation", target_os = "linux"))]
#[path = "native_launch_tests.rs"]
mod tests;
