//! Mock implementation of `std::sync::atomic`.

#[allow(clippy::module_inception)]
mod atomic;
use self::atomic::Atomic;

mod bool;
pub use self::bool::AtomicBool;

mod int;
pub use self::int::AtomicI16;
pub use self::int::AtomicI32;
pub use self::int::AtomicI64;
pub use self::int::AtomicI8;
pub use self::int::AtomicIsize;
pub use self::int::AtomicU16;
pub use self::int::AtomicU32;
pub use self::int::AtomicU64;
pub use self::int::AtomicU8;
pub use self::int::AtomicUsize;

mod ptr;
pub use self::ptr::AtomicPtr;

#[doc(no_inline)]
pub use std::sync::atomic::Ordering;

/// Signals the processor that it is entering a busy-wait spin-loop.
pub fn spin_loop_hint() {
    crate::thread::yield_now();
}

/// An atomic fence.
pub fn fence(order: Ordering) {
    crate::rt::fence(order);
}
