# N256 exact runtime identity admission

This independent candidate turns the #6890/#6892 runtime lineage mismatch into a fail-closed admission boundary. It reads the already committed oracle receipt and installed package metadata using only the Python standard library. It never imports NumPy, SciPy, or Torch and never calls the candidate, a dynamic step, or an exponential action.

The result is an admission receipt, not a numerical pass. A mismatch rejects numerical execution before it begins. A match only proves the runtime identity gate and still grants no N256, full-state, finite-domain, C2, HPCA, or production qualification.

The original 665/69728 RED, all earlier OOM/cancelled/UNKNOWN states, C2 full replay 0/6, HPCA NoUpdate, global HOLD, and `all_closed=false` remain unchanged.

