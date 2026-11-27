use crate::attached::AttachedListener;
use crate::attached::TupleVec;
use crate::Closure;
use crate::ListenTuple;
use fancy_constructor::new;
use js_sys::Function;
use smallvec::SmallVec;
use std::borrow::Cow;
use std::task::Context;
use std::task::Poll;
use tokio::sync::mpsc::UnboundedReceiver;
use wasm_bindgen::JsCast;
use wasm_bindgen::JsValue;
use web_sys::Event;
use web_sys::EventTarget;

/// An event listener that may or may not be atached to `1..` [event targets](EventTarget).
#[derive(new)]
#[new(vis(pub(crate)))]
pub struct Listener<T = Event> {
    closure: Closure<T>,
    opts: Option<js_sys::Object>,
    pub(crate) rx: UnboundedReceiver<T>,
}

impl<T> std::fmt::Debug for Listener<T> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Listener")
            .field("closure", &self.closure)
            .field("opts", &self.opts)
            .field("rx", &self.rx)
            .finish()
    }
}

macro_rules! comment {
    (add_use) => {
        r#"-----

 - Use [`attach`](Listener::attach), [`attach_multi`](Listener::attach_multi), or
   [`attach_multi_owned`](Listener::attach_multi_owned) to automatically [remove](Self::rm_from) event listeners on drop.
 - Use [`add_to`](Listener::add_to) to add an event listener, but not remove it on drop."#
    };
    (listen) => {
        r#" Listen for events of type `event` on `target`, putting them into the internal [buffer](UnboundedReceiver)
for [polling](Self::recv)."#
    }
}

/// Listener attachment.
#[allow(clippy::missing_errors_doc)]
impl<T> Listener<T> {
    #[doc = comment!(listen)]
    #[doc = ""]
    #[doc = comment!(add_use)]
    pub fn add_to(&self, event: &str, target: &EventTarget) -> Result<(), JsValue> {
        if let Some(ref opts) = self.opts {
            target.add_event_listener_with_callback_and_add_event_listener_options(
                event,
                self.as_ref(),
                opts.unchecked_ref(),
            )
        } else {
            target.add_event_listener_with_callback(event, self.as_ref())
        }
    }

    /// Stop listening for events of type `event` on `target`.
    pub fn rm_from(&self, event: &str, target: &EventTarget) -> Result<(), JsValue> {
        if let Some(ref opts) = self.opts {
            target.remove_event_listener_with_callback_and_event_listener_options(
                event,
                self.as_ref(),
                opts.unchecked_ref(),
            )
        } else {
            target.remove_event_listener_with_callback(event, self.as_ref())
        }
    }

    #[doc = comment!(listen)]
    #[doc = ""]
    #[doc = comment!(add_use)]
    pub fn attach<'a, E>(
        self,
        event: E,
        target: Cow<'a, EventTarget>,
    ) -> Result<AttachedListener<'a, T>, JsValue>
    where
        E: Into<Cow<'a, str>>,
    {
        let tuple = ListenTuple::new(event.into(), target);
        self.add_to(tuple.event_name(), tuple.target())?;

        let mut tuples = SmallVec::with_capacity(1);
        tuples.push(tuple);

        Ok(AttachedListener::new(self, tuples))
    }

    /// Listen for multiple events on multiple _borrowed_ targets.
    ///
    /// For each tuple in `tuples`, we'll listen for events of type `.0` on the target `.1`.
    ///
    #[doc = comment!(add_use)]
    pub fn attach_multi<'a, It>(self, tuples: It) -> Result<AttachedListener<'a, T>, JsValue>
    where
        It: IntoIterator<Item = (Cow<'a, str>, &'a EventTarget)>,
    {
        let tuples = tuples
            .into_iter()
            .map(move |(evt, tgt)| ListenTuple::new(evt, Cow::Borrowed(tgt)))
            .collect();

        self.attach_multi_common(tuples)
    }

    /// Listen for multiple events on multiple _owned_ targets.
    ///
    /// For each tuple in `tuples`, we'll listen for events of type `.0` on the target `.1`.
    ///
    #[doc = comment!(add_use)]
    pub fn attach_multi_owned<'a, It>(self, tuples: It) -> Result<AttachedListener<'a, T>, JsValue>
    where
        It: IntoIterator<Item = (Cow<'a, str>, EventTarget)>,
    {
        let tuples = tuples
            .into_iter()
            .map(move |(evt, tgt)| ListenTuple::new(evt, Cow::Owned(tgt)))
            .collect();

        self.attach_multi_common(tuples)
    }
}

/// Polling
impl<T> Listener<T> {
    /// Poll for an event emission.
    pub fn poll_recv(&mut self, cx: &mut Context<'_>) -> Poll<T> {
        match self.rx.poll_recv(cx) {
            Poll::Ready(Some(evt)) => Poll::Ready(evt),
            Poll::Pending => Poll::Pending,
            Poll::Ready(None) => {
                // The closure contained within this struct owns the sender, therefore it should never resolve to None.
                unreachable!("Listener tx dropped");
            }
        }
    }

    /// Wait for an event to be emitted.
    ///
    /// Note that this future will never resolve if the event target(s) never emit the monitored event(s) - include
    /// a cancellation condition e.g. using `futures::future::select`.
    pub async fn recv(&mut self) -> T {
        if let Some(evt) = self.rx.recv().await {
            evt
        } else {
            // The closure contained within this struct owns the sender, therefore it should never resolve to None.
            unreachable!("Listener tx dropped")
        }
    }

    /// Check if an event got emitted, returning it if it was.
    #[inline]
    pub fn try_recv(&mut self) -> Option<T> {
        self.rx.try_recv().ok()
    }

    /// Close the receiver without dropping it. Equivalent to calling [`close`](UnboundedReceiver::close) on the
    /// internal receiver.
    #[inline]
    pub fn close(&mut self) {
        self.rx.close();
    }
}

/// Internals
impl<T> Listener<T> {
    fn attach_multi_common(self, tuples: TupleVec) -> Result<AttachedListener<T>, JsValue> {
        // attach multiple listeners
        for (idx, tuple) in tuples.iter().enumerate() {
            match self.add_to(tuple.event_name(), tuple.target()) {
                Ok(()) => {}
                Err(e) => {
                    // roll back previous attachments
                    if idx != 0 {
                        self.rm_multi(tuples.iter().take(idx));
                    }

                    return Err(e);
                }
            }
        }

        Ok(AttachedListener::new(self, tuples))
    }

    pub(crate) fn rm_multi<'a, It>(&self, tuples: It)
    where
        It: IntoIterator<Item = &'a ListenTuple<'a>>,
    {
        let func = self.as_ref();
        if let Some(ref opts) = self.opts {
            let opts = opts.unchecked_ref();
            for t in tuples {
                let _ = t
                    .target()
                    .remove_event_listener_with_callback_and_event_listener_options(
                        t.event_name(),
                        func,
                        opts,
                    );
            }
        } else {
            for t in tuples {
                let _ = t
                    .target()
                    .remove_event_listener_with_callback(t.event_name(), func);
            }
        }
    }
}

impl<T> AsRef<Function> for Listener<T> {
    fn as_ref(&self) -> &Function {
        self.closure.as_ref().unchecked_ref()
    }
}
