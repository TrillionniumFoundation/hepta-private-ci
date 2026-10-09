//! Fixed-horizon, one-sided exact binomial check on source-family outcomes.
//!
//! One outcome is true only when EVERY citation in an already coalesced family
//! is entailed. This additional family-complete reliability requirement is not
//! a confidence interval on citation-count-weighted micro precision. Actual
//! independence, exchangeability and the frozen sampling horizon must be supplied
//! by the existing selection/observer owners; hashing does not establish them.

/// Test H0: family-complete reliability <= 0.99, at one-sided alpha 0.05.
/// Equivalent to requiring the exact Clopper-Pearson lower bound above 0.99.
/// A fixed 20,000-family limit matches the owning census bound. Log-space
/// evaluation avoids underflow without introducing a statistics dependency.
pub(super) fn passes_99_at_95(good: usize, total: usize) -> bool {
    if total == 0 || total > 20_000 || good > total {
        return false;
    }
    let log_good = 0.99_f64.ln();
    let log_bad = 0.01_f64.ln();
    let mut term = total as f64 * log_good;
    let mut sum = term;
    for failures in 1..=(total - good) {
        term += ((total - failures + 1) as f64).ln() - (failures as f64).ln() + log_bad - log_good;
        let larger = sum.max(term);
        sum = larger + ((sum - larger).exp() + (term - larger).exp()).ln();
    }
    // Leave boundary-rounding uncertainty on the rejecting side.
    sum < 0.05_f64.ln() - 1e-12
}

#[cfg(test)]
#[path = "citation_confidence_tests.rs"]
mod tests;
