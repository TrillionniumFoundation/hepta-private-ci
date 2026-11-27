// Newly authored tests for the current native-control API. The historical b1be
// test intents are recorded in the review receipt; these are not recovered
// historical qualification or real model execution.
#[cfg(test)]
mod tests {
    use super::*;

    include!("test_helpers.rs");
    include!("test_contracts.rs");
    include!("test_lifecycle.rs");
    include!("test_admission.rs");
}
