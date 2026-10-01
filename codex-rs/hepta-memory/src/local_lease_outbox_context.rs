use super::LocalOutcomeState;

/// One outcome transition's payload and replay rules, applied together inside
/// the existing caller-owned transaction.
pub(super) struct OutcomeAppend<'a> {
    pub(super) kind: &'a str,
    pub(super) payload: String,
    pub(super) allowed: &'a [LocalOutcomeState],
    pub(super) resulting_state: LocalOutcomeState,
    pub(super) allow_exact_replay: bool,
}
