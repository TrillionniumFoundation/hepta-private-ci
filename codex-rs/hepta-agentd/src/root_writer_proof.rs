//! Original internal paths retain the same canonical proof and pinned trust.
pub use codex_hepta_authority_client::AgentdRootAuthorityError;
pub use codex_hepta_authority_client::AgentdRootWriterTrust;
pub(crate) use codex_hepta_authority_client::VerifiedRootWriterProof;

#[cfg(test)]
#[path = "root_writer_proof_fixture.rs"]
pub(crate) mod tests;
