use crate::Closure;
use crate::Listener;
use accessory::Accessors;
use fancy_constructor::new;
use std::marker::PhantomData;
use tokio::sync::mpsc;
use wasm_bindgen::convert::FromWasmAbi;
use wasm_bindgen::prelude::*;
use web_sys::Event;

/// Options builder for an event listener.
#[derive(Accessors, new)]
#[access(defaults(set(owned, prefix(with), const_fn)))]
#[new(const_fn, bounds(T: FromWasmAbi + 'static))]
#[must_use]
pub struct ListenerBuilder<T = Event> {
    /// Set the [`passive`](https://developer.mozilla.org/en-US/docs/Web/API/EventTarget/addEventListener#passive)
    /// option.
    #[access(set)]
    #[new(val(false))]
    passive: bool,

    /// Set the [`capture`](https://developer.mozilla.org/en-US/docs/Web/API/EventTarget/addEventListener#capture)
    /// option.
    #[access(set)]
    #[new(val(false))]
    capture: bool,

    /// Set the [`once`](https://developer.mozilla.org/en-US/docs/Web/API/EventTarget/addEventListener#once)
    /// option.
    #[access(set)]
    #[new(val(false))]
    once: bool,

    #[new(val(PhantomData))]
    _arg: PhantomData<T>,
}

impl<T> std::fmt::Debug for ListenerBuilder<T> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("ListenerBuilder")
            .field("passive", &self.passive)
            .field("capture", &self.capture)
            .field("once", &self.once)
            .finish()
    }
}

impl<T> Clone for ListenerBuilder<T> {
    fn clone(&self) -> Self {
        Self {
            passive: self.passive,
            capture: self.capture,
            once: self.once,
            _arg: PhantomData,
        }
    }
}

impl<T> PartialEq for ListenerBuilder<T> {
    fn eq(&self, other: &Self) -> bool {
        self.passive == other.passive && self.capture == other.capture && self.once == other.once
    }
}

impl<T> Eq for ListenerBuilder<T> {}

impl<T> ListenerBuilder<T>
where
    T: FromWasmAbi + 'static,
{
    /// Build the options into a listener that can be attached to things.
    #[allow(clippy::missing_errors_doc)]
    pub fn build(self) -> Result<Listener<T>, JsValue> {
        let opts = self.build_opts()?;
        let (tx, rx) = mpsc::unbounded_channel();
        let closure = Closure::new(move |event| {
            let _ = tx.send(event);
        });

        Ok(Listener::new(closure, opts, rx))
    }

    fn build_opts(&self) -> Result<Option<js_sys::Object>, JsValue> {
        macro_rules! build {
            ($($opt: ident),+ $(,)?) => {
                if $(!self.$opt)&&+ {
                    Ok(None)
                } else {
                    let obj = js_sys::Object::new();
                    $(if self.$opt {
                        js_sys::Reflect::set(&obj, &stringify!($opt).into(), &true.into())?;
                    })+
                    Ok(Some(obj.unchecked_into()))
                }
            };
        }

        build!(passive, capture, once)
    }
}

impl<T> Listener<T> {
    /// Alias for [`ListenerBuilder::new`].
    pub const fn builder() -> ListenerBuilder<T>
    where
        T: FromWasmAbi + 'static,
    {
        ListenerBuilder::new()
    }
}

impl<T> Default for ListenerBuilder<T>
where
    T: FromWasmAbi + 'static,
{
    #[inline]
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
#[path = "builder_compat_tests.rs"]
mod tests;
