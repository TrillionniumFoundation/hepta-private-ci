/// Minimal crate-local compatibility surface for the single random capability
/// draw used by the Matrix claim owner. This deliberately avoids adding a new
/// direct dependency (and lockfile edge) to the durable store.
pub(crate) fn random<T>() -> T
where
    T: From<[u8; 32]>,
{
    T::from(codex_state::random_capability_bytes())
}
