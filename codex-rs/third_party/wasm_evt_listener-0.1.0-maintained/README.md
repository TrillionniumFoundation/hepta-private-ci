<!-- cargo-rdme start -->

A smart Future-based WASM event listener that cleans up after itself on drop.

# Features

- `passive`, `once` & `capture` listener options
- [`Stream`](futures_core::Stream) support (required `streams` feature)
- Automatically [remove](https://developer.mozilla.org/en-US/docs/Web/API/EventTarget/removeEventListener) listeners
  on drop

# Usage

```rust
use wasm_evt_listener::Listener;
use web_sys::{Event, EventTarget};
use tokio_util::sync::CancellationToken;
use std::borrow::Cow;

/// The listener is simply a Closure and an unbounded Receiver - it needs to get attached
/// to some elements.
fn create_listener() -> Listener {
  Listener::builder()
    .with_once(true)
    .with_capture(true)
    .with_passive(true)
    .build()
    .unwrap()
}

async fn example_1(target: &EventTarget, cancellation: &CancellationToken) {
  let mut listener = create_listener();

  // Here we listen for click events without automatically removing the
  // listener from the target on drop
  let _: () = listener.add_to("click", target).unwrap();

  loop {
     let event: Event = tokio::select! {
         e = listener.recv() => e,
         () = cancellation.cancelled() => break,
     };

     do_things_with(event);
  }
}

async fn example_2(target: &EventTarget, cancellation: &CancellationToken) {
  let listener = create_listener();

  // Here listen for click events but, once `attached` is dropped, we'll
  // rermove the JS event listener off `target`
  let mut attached = listener.attach("click", Cow::Borrowed(target)).unwrap();

  loop {
     let event: Event = tokio::select! {
         e = attached.recv() => e,
         () = cancellation.cancelled() => break,
     };

     do_things_with(event);
  }

  // `removeEventListener` gets called on JS' end at this point
}

async fn example_3(tgt1: &EventTarget, tgt2: &EventTarget, cancellation: &CancellationToken) {
  let listener = create_listener();

  // Here we listen for "click" & "keyup" events on target 1, "foo" & "bar" events on target 2,
  // all with the same options.
  // Since all JS events extends Event, our web_sys::Event listener is valid for all of the
  // combinations.
  let mut attached = listener.attach_multi([
    ("click".into(), tgt1),
    ("keyup".into(), tgt1),
    ("foo".into(), tgt2),
    ("bar".into(), tgt2),
  ]).unwrap();

  loop {
     let event: Event = tokio::select! {
         e = attached.recv() => e,
         () = cancellation.cancelled() => break,
     };

     do_things_with(event);
  }
}

```

<!-- cargo-rdme end -->
