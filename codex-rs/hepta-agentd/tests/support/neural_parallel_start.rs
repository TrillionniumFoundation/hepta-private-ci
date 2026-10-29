//! Two bounded, independent starts inside the original comparison's clock.
//! This composition neither admits a model nor owns its terminal receipt.

pub fn start_pair<T, L, R, S>(left: L, right: R, mut shutdown: S) -> Result<(T, T), String>
where
    T: Send,
    L: FnOnce() -> Result<T, String> + Send,
    R: FnOnce() -> Result<T, String>,
    S: FnMut(&mut T) -> Result<(), String>,
{
    std::thread::scope(|scope| {
        // Creation failure precedes either start. Model Child ownership remains
        // with each original Session's separately preborn custodian.
        let left = std::thread::Builder::new()
            .name("hepta-comparison-start".to_owned())
            .stack_size(1024 * 1024)
            .spawn_scoped(scope, left)
            .map_err(|error| format!("comparison initializer unavailable: {error}"))?;
        let right = std::panic::catch_unwind(std::panic::AssertUnwindSafe(right))
            .unwrap_or_else(|_| Err("right comparison startup panicked".to_owned()));
        let left = left
            .join()
            .unwrap_or_else(|_| Err("left comparison startup panicked".to_owned()));
        // Observe both outcomes before returning. A surviving model still owes
        // the original explicit unload, even when its peer failed or panicked.
        match (left, right) {
            (Ok(left), Ok(right)) => Ok((left, right)),
            (Err(left), Err(right)) => Err(format!("comparison starts failed: {left}; {right}")),
            (Err(error), Ok(mut survivor)) | (Ok(mut survivor), Err(error)) => {
                let terminal = shutdown(&mut survivor);
                Err(match terminal {
                    Ok(()) => format!("comparison startup failed: {error}; survivor unloaded"),
                    Err(terminal) => format!(
                        "comparison startup failed: {error}; survivor unload unresolved: {terminal}"
                    ),
                })
            }
        }
    })
}

#[cfg(test)]
#[path = "neural_parallel_start_tests.rs"]
mod tests;
