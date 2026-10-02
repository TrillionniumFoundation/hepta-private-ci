//! Native cross-thread channels; bounded, epoch-owned browser timeline streams.
//! Overflow invalidates the entire delta stream. Applying a suffix after dropping
//! one delta would corrupt UI state, so recovery explicitly requires resync.
#[cfg(not(target_family = "wasm"))]
pub use crossbeam_channel::{Receiver, Sender};
#[cfg(not(target_family = "wasm"))]
pub fn channel<T>() -> (Sender<T>, Receiver<T>) { crossbeam_channel::unbounded() }

#[cfg(any(target_family = "wasm", test))]
const CAPACITY: usize = 512;
#[cfg(any(target_family = "wasm", test))]
struct Buffer<T> {
    epoch: u64,
    pending: std::collections::VecDeque<T>,
    poisoned: bool,
    receiver_alive: bool,
}
#[cfg(any(target_family = "wasm", test))]
impl<T> Buffer<T> {
    fn new(epoch: u64) -> Self {
        Self { epoch, pending: std::collections::VecDeque::new(), poisoned: false, receiver_alive: true }
    }
    fn push(&mut self, origin: u64, current: u64, value: T) -> Result<(), T> {
        if origin != current { return Err(value); }
        if self.epoch != current || !self.receiver_alive || self.poisoned {
            self.pending.clear();
            return Err(value);
        }
        if self.pending.len() == CAPACITY {
            self.pending.clear();
            self.poisoned = true;
            return Err(value);
        }
        self.pending.push_back(value);
        Ok(())
    }
    fn pop(&mut self, current: u64) -> Result<T, crossbeam_channel::TryRecvError> {
        if self.epoch != current || self.poisoned {
            self.pending.clear();
            return Err(crossbeam_channel::TryRecvError::Disconnected);
        }
        self.pending.pop_front().ok_or(crossbeam_channel::TryRecvError::Empty)
    }
}

#[cfg(target_family = "wasm")]
mod browser {
    use super::*;
    use std::{cell::RefCell, rc::Rc};
    pub struct Sender<T>(Rc<RefCell<Buffer<T>>>);
    pub struct Receiver<T>(Rc<RefCell<Buffer<T>>>);
    impl<T> Clone for Sender<T> {
        fn clone(&self) -> Self { Self(self.0.clone()) }
    }
    impl<T> Sender<T> {
        pub fn send(&self, value: T) -> Result<(), crossbeam_channel::SendError<T>> {
            let (result, overflowed) = {
                let mut state = self.0.borrow_mut();
                let was_poisoned = state.poisoned;
                let result = state.push(crate::ui_dispatch::origin_epoch(), crate::ui_dispatch::current_epoch(), value);
                (result, !was_poisoned && state.poisoned)
            };
            if overflowed { crate::ui_dispatch::report_overflow(); }
            result.map_err(crossbeam_channel::SendError)
        }
    }
    impl<T> Receiver<T> {
        pub fn try_recv(&self) -> Result<T, crossbeam_channel::TryRecvError> {
            self.0.borrow_mut().pop(crate::ui_dispatch::current_epoch())
        }
    }
    impl<T> Drop for Receiver<T> {
        fn drop(&mut self) {
            let mut state = self.0.borrow_mut();
            state.receiver_alive = false;
            state.pending.clear();
        }
    }
    pub fn channel<T>() -> (Sender<T>, Receiver<T>) {
        let state = Rc::new(RefCell::new(Buffer::new(crate::ui_dispatch::origin_epoch())));
        (Sender(state.clone()), Receiver(state))
    }
}
#[cfg(target_family = "wasm")]
pub use browser::{channel, Receiver, Sender};

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn overflow_invalidates_the_whole_delta_stream() {
        let mut buffer = Buffer::new(7);
        for value in 0..CAPACITY { assert_eq!(buffer.push(7, 7, value), Ok(())); }
        assert_eq!(buffer.pending.len(), CAPACITY);
        assert_eq!(buffer.push(7, 7, CAPACITY), Err(CAPACITY));
        assert!(buffer.pending.is_empty());
        assert_eq!(buffer.pop(7), Err(crossbeam_channel::TryRecvError::Disconnected));
        assert_eq!(buffer.push(7, 7, 99), Err(99));
    }
    #[test]
    fn retired_channel_cannot_deliver_into_new_account() {
        let mut buffer = Buffer::new(3);
        assert_eq!(buffer.push(3, 3, "queued old"), Ok(()));
        assert_eq!(buffer.pop(4), Err(crossbeam_channel::TryRecvError::Disconnected));
        assert_eq!(buffer.push(3, 4, "late old"), Err("late old"));
        assert!(buffer.pending.is_empty());
    }
    #[test]
    fn current_stream_preserves_order() {
        let mut buffer = Buffer::new(2);
        assert_eq!(buffer.push(2, 2, 11), Ok(()));
        assert_eq!(buffer.push(2, 2, 12), Ok(()));
        assert_eq!(buffer.pop(2), Ok(11));
        assert_eq!(buffer.pop(2), Ok(12));
        assert_eq!(buffer.pop(2), Err(crossbeam_channel::TryRecvError::Empty));
    }
}

#[cfg(all(test, target_family = "wasm"))]
mod browser_tests {
    use super::*;
    use wasm_bindgen_test::wasm_bindgen_test;

    #[wasm_bindgen_test]
    fn poisoned_stream_blocks_requests_until_new_authority() {
        crate::ui_dispatch::advance_epoch();
        let (sender, receiver) = channel();
        for value in 0..CAPACITY { assert!(sender.send(value).is_ok()); }
        assert!(sender.send(CAPACITY).is_err());
        assert!(!crate::ui_dispatch::accepts_requests());
        assert_eq!(receiver.try_recv(), Err(crossbeam_channel::TryRecvError::Disconnected));
        crate::ui_dispatch::advance_epoch();
        assert!(crate::ui_dispatch::accepts_requests());
        assert!(sender.send(1).is_err());
        let (new_sender, new_receiver) = channel();
        assert!(new_sender.send(7).is_ok());
        assert_eq!(new_receiver.try_recv(), Ok(7));
    }
}
