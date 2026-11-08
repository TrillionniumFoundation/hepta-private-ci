//! Mock implementation of `std::sync`.

mod arc;
pub mod atomic;
mod barrier;
mod condvar;
pub mod mpsc;
mod mutex;
mod notify;
mod rwlock;

pub use self::arc::Arc;
pub use self::barrier::Barrier;
pub use self::condvar::Condvar;
pub use self::condvar::WaitTimeoutResult;
pub use self::mutex::Mutex;
pub use self::mutex::MutexGuard;
pub use self::notify::Notify;
pub use self::rwlock::RwLock;
pub use self::rwlock::RwLockReadGuard;
pub use self::rwlock::RwLockWriteGuard;

#[doc(no_inline)]
pub use std::sync::LockResult;
#[doc(no_inline)]
pub use std::sync::TryLockResult;
