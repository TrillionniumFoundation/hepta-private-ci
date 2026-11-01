//! C ABI for independently implemented finite CTMC propagation and observations.
mod core;

use core::Failure;
use core::MAX_DIMENSION;

/// Q is n*n row-major, p is a row distribution, out has n writable doubles.
/// Caller owns valid, correctly aligned memory; invalid pointers cannot be
/// diagnosed by Rust. Inputs must not race with other writes. Output is only
/// changed on success. Numeric/domain failures return stable nonzero codes.
#[no_mangle]
pub unsafe extern "C" fn propagate(
    n: usize,
    q_ptr: *const f64,
    dt: f64,
    p_ptr: *const f64,
    out_ptr: *mut f64,
) -> i32 {
    if n == 0 || n > MAX_DIMENSION {
        return Failure::Dimension as i32;
    }
    if q_ptr.is_null() || p_ptr.is_null() || out_ptr.is_null() {
        return Failure::NullPointer as i32;
    }
    let outcome = std::panic::catch_unwind(|| {
        let q = unsafe { std::slice::from_raw_parts(q_ptr, n * n) };
        let p = unsafe { std::slice::from_raw_parts(p_ptr, n) };
        core::propagate_row(n, q, dt, p)
    });
    match outcome {
        Ok(Ok(result)) => {
            unsafe { std::ptr::copy_nonoverlapping(result.as_ptr(), out_ptr, n) };
            0
        }
        Ok(Err(error)) => error as i32,
        Err(_) => Failure::Panic as i32,
    }
}

/// Bayesian observation update. Nonnegative likelihoods may be densities >1.
/// Impossible observations (zero represented normalization) are rejected.
#[no_mangle]
pub unsafe extern "C" fn observe(
    n: usize,
    prior_ptr: *const f64,
    likelihood_ptr: *const f64,
    out_ptr: *mut f64,
) -> i32 {
    if n == 0 || n > MAX_DIMENSION {
        return Failure::Dimension as i32;
    }
    if prior_ptr.is_null() || likelihood_ptr.is_null() || out_ptr.is_null() {
        return Failure::NullPointer as i32;
    }
    let outcome = std::panic::catch_unwind(|| {
        let p = unsafe { std::slice::from_raw_parts(prior_ptr, n) };
        let likelihood = unsafe { std::slice::from_raw_parts(likelihood_ptr, n) };
        core::observe_row(p, likelihood)
    });
    match outcome {
        Ok(Ok(result)) => {
            unsafe { std::ptr::copy_nonoverlapping(result.as_ptr(), out_ptr, n) };
            0
        }
        Ok(Err(error)) => error as i32,
        Err(_) => Failure::Panic as i32,
    }
}
