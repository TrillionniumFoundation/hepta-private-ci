/// Concrete enrolled HTTPS client for a product host. The host still owns peer
/// enrollment and the kernel authority instance; constructing this type does not
/// enroll a peer, mint a grant, or activate federation by itself.
pub type ProductionFederationClientV3 =
    FederationClientV3<PinnedHttpsFederationTransportV3, SystemFederationClockV3>;

impl FederationClientV3<PinnedHttpsFederationTransportV3, SystemFederationClockV3> {
    pub fn new_pinned_https(
        authority: FinalUseAuthority,
        authority_key_id: String,
        registry: FederationPeerRegistryV3,
        cache_capacity: usize,
    ) -> Result<Self, FederationV3Error> {
        Self::new(
            authority,
            authority_key_id,
            registry,
            PinnedHttpsFederationTransportV3::default(),
            SystemFederationClockV3,
            cache_capacity,
        )
    }
}
