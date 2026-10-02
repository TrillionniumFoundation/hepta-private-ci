//! A cancellation deadline that remains live until the entire browser operation finishes.
use js_sys::Promise;
use std::{
    cell::RefCell,
    future::{Future, poll_fn},
    pin::pin,
    rc::Rc,
    task::{Poll, Waker},
};
use wasm_bindgen::{JsCast, JsValue, closure::Closure};
use wasm_bindgen_futures::JsFuture;
use web_sys::{AbortController, AbortSignal, Window};

pub(crate) struct Deadline {
    window: Window,
    controller: AbortController,
    timer: i32,
    timer_callback: Closure<dyn FnMut()>,
    external: Option<(AbortSignal, Closure<dyn FnMut()>)>,
    waiter: Rc<RefCell<Option<Waker>>>,
    abort_callback: Closure<dyn FnMut()>,
}

impl Deadline {
    pub(crate) fn new(external: Option<AbortSignal>, milliseconds: u32) -> Result<Self, JsValue> {
        let window = web_sys::window().ok_or_else(|| JsValue::from_str("window unavailable"))?;
        let controller = AbortController::new()?;
        let signal = controller.signal();
        let waiter: Rc<RefCell<Option<Waker>>> = Rc::new(RefCell::new(None));
        let pending = waiter.clone();
        let abort_callback = Closure::wrap(Box::new(move || {
            if let Some(waker) = pending.borrow_mut().take() {
                waker.wake();
            }
        }) as Box<dyn FnMut()>);
        signal
            .add_event_listener_with_callback("abort", abort_callback.as_ref().unchecked_ref())?;
        let external = if let Some(external) = external {
            let target = controller.clone();
            let closure = Closure::wrap(Box::new(move || target.abort()) as Box<dyn FnMut()>);
            if let Err(error) =
                external.add_event_listener_with_callback("abort", closure.as_ref().unchecked_ref())
            {
                let _ = signal.remove_event_listener_with_callback(
                    "abort",
                    abort_callback.as_ref().unchecked_ref(),
                );
                return Err(error);
            }
            if external.aborted() {
                controller.abort();
            }
            Some((external, closure))
        } else {
            None
        };
        let target = controller.clone();
        let timer_callback = Closure::wrap(Box::new(move || target.abort()) as Box<dyn FnMut()>);
        let timer = match window.set_timeout_with_callback_and_timeout_and_arguments_0(
            timer_callback.as_ref().unchecked_ref(),
            milliseconds as i32,
        ) {
            Ok(timer) => timer,
            Err(error) => {
                let _ = signal.remove_event_listener_with_callback(
                    "abort",
                    abort_callback.as_ref().unchecked_ref(),
                );
                if let Some((source, closure)) = external {
                    let _ = source.remove_event_listener_with_callback(
                        "abort",
                        closure.as_ref().unchecked_ref(),
                    );
                }
                return Err(error);
            }
        };
        Ok(Self {
            window,
            controller,
            timer,
            timer_callback,
            external,
            waiter,
            abort_callback,
        })
    }

    pub(crate) fn signal(&self) -> AbortSignal {
        self.controller.signal()
    }

    pub(crate) async fn race(&self, operation: Promise) -> Result<JsValue, JsValue> {
        let mut operation = pin!(JsFuture::from(operation));
        // One Rust waker is reused across all body reads. Repeated Promise::race calls
        // would attach a retained callback to a pending abort promise for every chunk.
        let result = poll_fn(|context| {
            if self.signal().aborted() {
                return Poll::Ready(Err(JsValue::from_str("operation aborted")));
            }
            *self.waiter.borrow_mut() = Some(context.waker().clone());
            operation.as_mut().poll(context)
        })
        .await;
        self.waiter.borrow_mut().take();
        result
    }
}

impl Drop for Deadline {
    fn drop(&mut self) {
        self.window.clear_timeout_with_handle(self.timer);
        if let Some((signal, callback)) = &self.external {
            let _ = signal
                .remove_event_listener_with_callback("abort", callback.as_ref().unchecked_ref());
        }
        let _ = self
            .controller
            .signal()
            .remove_event_listener_with_callback(
                "abort",
                self.abort_callback.as_ref().unchecked_ref(),
            );
        // Keep the closure alive until its timer has been removed.
        let _ = &self.timer_callback;
        self.controller.abort();
    }
}
