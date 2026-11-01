//! Prepared finite-model C ABI. Caller supplies valid aligned buffer lengths.
//! Outputs change only on success; handles are checked and never reused.
mod core;
mod prepared;
mod sha256;

use core::Failure;
use prepared::Model;
use prepared::Transition;
use prepared::Workspace;
use std::cell::RefCell;
use std::collections::HashMap;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::OnceLock;

static MODELS: OnceLock<Mutex<HashMap<u64, Arc<Model>>>> = OnceLock::new();
static NEXT_HANDLE: AtomicU64 = AtomicU64::new(1);
thread_local! { static WORK: RefCell<Workspace> = RefCell::new(Workspace::default()); }

fn registry() -> &'static Mutex<HashMap<u64, Arc<Model>>> {
    MODELS.get_or_init(|| Mutex::new(HashMap::new()))
}

fn model(handle: u64, version: u64) -> Result<Arc<Model>, Failure> {
    let value = registry()
        .lock()
        .map_err(|_| Failure::Panic)?
        .get(&handle)
        .cloned()
        .ok_or(Failure::Handle)?;
    if value.version != version {
        return Err(Failure::Version);
    }
    Ok(value)
}

fn guarded(operation: impl FnOnce() -> Result<(), Failure>) -> i32 {
    match std::panic::catch_unwind(std::panic::AssertUnwindSafe(operation)) {
        Ok(Ok(())) => 0,
        Ok(Err(error)) => error as i32,
        Err(_) => Failure::Panic as i32,
    }
}

fn elements(n: usize, batch: usize) -> Result<usize, Failure> {
    if batch == 0 || batch > 4096 || n * batch > 8_388_608 {
        return Err(Failure::Dimension);
    }
    Ok(n * batch)
}

#[no_mangle]
pub unsafe extern "C" fn hcsn_model_create(
    n: usize,
    q: *const f64,
    version: u64,
    out: *mut u64,
) -> i32 {
    guarded(|| {
        if n == 0 || n > prepared::MAX_PREPARED_DIMENSION {
            return Err(Failure::Dimension);
        }
        if q.is_null() || out.is_null() {
            return Err(Failure::NullPointer);
        }
        let value = Model::new(n, unsafe { std::slice::from_raw_parts(q, n * n) }, version)?;
        let mut registry = registry().lock().map_err(|_| Failure::Panic)?;
        if registry.len() >= 128 {
            return Err(Failure::WorkLimit);
        }
        let handle = NEXT_HANDLE
            .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |n| n.checked_add(1))
            .map_err(|_| Failure::WorkLimit)?;
        registry.insert(handle, Arc::new(value));
        unsafe {
            out.write(handle);
        }
        Ok(())
    })
}

#[no_mangle]
pub extern "C" fn hcsn_model_release(handle: u64) -> i32 {
    guarded(|| {
        registry()
            .lock()
            .map_err(|_| Failure::Panic)?
            .remove(&handle)
            .map(|_| ())
            .ok_or(Failure::Handle)
    })
}

#[no_mangle]
pub unsafe extern "C" fn hcsn_model_identity(handle: u64, version: u64, out: *mut u8) -> i32 {
    guarded(|| {
        if out.is_null() {
            return Err(Failure::NullPointer);
        }
        let value = model(handle, version)?;
        unsafe {
            std::ptr::copy_nonoverlapping(value.identity.as_ptr(), out, 64);
        }
        Ok(())
    })
}

#[no_mangle]
pub extern "C" fn hcsn_prepare(handle: u64, version: u64, dt: f64, mode: u32) -> i32 {
    guarded(|| {
        model(handle, version)?.prepare(dt, mode)?;
        Ok(())
    })
}

#[no_mangle]
pub extern "C" fn hcsn_cache_clear(handle: u64, version: u64) -> i32 {
    guarded(|| model(handle, version)?.clear_cache())
}

#[no_mangle]
pub unsafe extern "C" fn hcsn_cache_statistics(handle: u64, version: u64, out: *mut u64) -> i32 {
    guarded(|| {
        if out.is_null() {
            return Err(Failure::NullPointer);
        }
        let counts = model(handle, version)?.statistics()?;
        unsafe {
            std::ptr::copy_nonoverlapping(counts.as_ptr(), out, 4);
        }
        Ok(())
    })
}

#[no_mangle]
pub unsafe extern "C" fn hcsn_transition(handle: u64, version: u64, dt: f64, out: *mut f64) -> i32 {
    guarded(|| {
        if out.is_null() {
            return Err(Failure::NullPointer);
        }
        let value = model(handle, version)?;
        let plan = value.prepare(dt, 1)?;
        let Transition::Dense(kernel) = plan.as_ref() else {
            return Err(Failure::Numerical);
        };
        unsafe {
            std::ptr::copy_nonoverlapping(kernel.as_ptr(), out, kernel.len());
        }
        Ok(())
    })
}

#[no_mangle]
pub unsafe extern "C" fn hcsn_propagate_batch(
    handle: u64,
    version: u64,
    dt: f64,
    mode: u32,
    batch: usize,
    p: *const f64,
    out: *mut f64,
) -> i32 {
    guarded(|| {
        if p.is_null() || out.is_null() {
            return Err(Failure::NullPointer);
        }
        let value = model(handle, version)?;
        let count = elements(value.n, batch)?;
        let plan = value.prepare(dt, mode)?;
        let input = unsafe { std::slice::from_raw_parts(p, count) };
        WORK.with(|work| {
            let mut work = work.try_borrow_mut().map_err(|_| Failure::Panic)?;
            value.apply(&plan, input, &mut work)?;
            unsafe {
                std::ptr::copy_nonoverlapping(work.output.as_ptr(), out, count);
            }
            Ok(())
        })
    })
}

#[no_mangle]
pub unsafe extern "C" fn hcsn_observe_batch(
    handle: u64,
    version: u64,
    batch: usize,
    p: *const f64,
    likelihood: *const f64,
    likelihood_rows: usize,
    out: *mut f64,
) -> i32 {
    guarded(|| {
        if p.is_null() || likelihood.is_null() || out.is_null() {
            return Err(Failure::NullPointer);
        }
        let value = model(handle, version)?;
        let count = elements(value.n, batch)?;
        if likelihood_rows != 1 && likelihood_rows != batch {
            return Err(Failure::Dimension);
        }
        let input = unsafe { std::slice::from_raw_parts(p, count) };
        let likelihood =
            unsafe { std::slice::from_raw_parts(likelihood, likelihood_rows * value.n) };
        if likelihood.iter().any(|x| !x.is_finite() || *x < 0.0) {
            return Err(Failure::Domain);
        }
        WORK.with(|work| {
            let mut work = work.try_borrow_mut().map_err(|_| Failure::Panic)?;
            work.output.resize(count, 0.0);
            for (i, prior) in input.chunks_exact(value.n).enumerate() {
                core::probability_mass(prior)?;
                let row = if likelihood_rows == 1 { 0 } else { i };
                let like = &likelihood[row * value.n..(row + 1) * value.n];
                let scale = like.iter().copied().fold(0.0, f64::max);
                if scale == 0.0 {
                    return Err(Failure::Normalization);
                }
                let target = &mut work.output[i * value.n..(i + 1) * value.n];
                for ((out, p), l) in target.iter_mut().zip(prior).zip(like) {
                    *out = p * (l / scale);
                }
                let evidence = core::compensated_sum(target.iter().copied());
                if !evidence.is_finite() || evidence <= 0.0 {
                    return Err(Failure::Normalization);
                }
                target.iter_mut().for_each(|x| *x /= evidence);
                core::probability_mass(target)?;
            }
            unsafe {
                std::ptr::copy_nonoverlapping(work.output.as_ptr(), out, count);
            }
            Ok(())
        })
    })
}
