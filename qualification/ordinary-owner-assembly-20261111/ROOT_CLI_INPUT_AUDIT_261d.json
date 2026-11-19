{
  "schema": 1,
  "source_commit": "261d54cfba2d639ff3622924dfce583da6012486",
  "status": "SOURCE_AUDIT_NO_NATIVE_EXECUTION",
  "source_files": [
    {
      "path": "codex-rs/hepta-agentd/src/bin/hepta-authority-host.rs",
      "git_blob": "0848e5d2f2f621211713b0e7c7807ee68a250803",
      "sha256": "dddd3d75ea950c17b6bfc06ae23f9fa929d1761dbed03be865d47305125bd203",
      "bytes": 15600
    },
    {
      "path": "codex-rs/hepta-agentd/src/authority_host_generation_publication_session.rs",
      "git_blob": "b812ab27679ffe323c80bc04a85da29b182ebb4c",
      "sha256": "41b93c7fa45e3706fb6171e56db532cc7b752504ef279acd694257f794afcc4c",
      "bytes": 8874
    },
    {
      "path": "codex-rs/hepta-agentd/src/authority_host_generation_publication_enrollment.rs",
      "git_blob": "be684c1565564c969d0e3c58c6f3f799c26f9414",
      "sha256": "8799df996f246e3cffd906d55456c0ccc090caf4c8160258cbea6e6bac846b94",
      "bytes": 23087
    },
    {
      "path": "codex-rs/hepta-agentd/src/authority_host_config.rs",
      "git_blob": "24c49866fdd994f8bc2c1b9fdc40342149525bca",
      "sha256": "d940d9ed0cd645bb911c7545a1094cdb6168949972859e4e27cee1f1e65c2d62",
      "bytes": 7060
    }
  ],
  "existing_root_cli": {
    "open_or_fresh": true,
    "installs_original_learning_and_optional_model": true,
    "current_ready_callback_sends": [
      "original Learning offer",
      "original Model factory offer"
    ],
    "publication_enable_called": false,
    "original_publication_registration_capability_retained": false,
    "publication_offer_sent": false,
    "same_process_late_registration_trigger_defined": false,
    "deployment_input_contract_defined": false
  },
  "registration_constraint": {
    "type": "RootGenerationPublicationEnrollmentCapabilityV1",
    "creation": "PreparedHostAuthoritySession::enable_generation_publication(&mut self)",
    "consumption": "RootGenerationPublicationEnrollmentCapabilityV1::register(self, RootGenerationPublicationEnrollmentV1)",
    "checks": [
      "actual UID0",
      "exact original Root PID",
      "same boot id",
      "same Root process start ticks",
      "ACTIVE -> CONSUMED once",
      "bounded same-service submission and acknowledgement",
      "same original live learning backend enforces its actual Cell decision"
    ],
    "impossible_shortcut": "A separate register subcommand cannot consume the original opaque capability; another process fails PID/incarnation and has no original channel.",
    "semantics": "Enabling/sending an offer does not enroll CURRENT. The capability must remain in a same-PID worker while the original Prepared session is serving."
  },
  "exact_required_inputs": [
    {
      "field": "mode",
      "type": "RootGenerationPublicationModeV1::{Reserve,Recover}",
      "already_defined_by_current_cli": false,
      "reason": "Cognitive fresh/open session is not the publication record's reserve/recover lifecycle. Missing state cannot silently select Reserve."
    },
    {
      "field": "current_directory",
      "type": "Arc<RootAuthorityDirectory>",
      "already_defined_by_current_cli": false,
      "required_source": "Actual existing CURRENT protected directory for the original A binding; open the real Root owner, never initialize a replacement.",
      "reason": "HostAuthorityServiceConfig.state_dir identifies the authority service, not necessarily the existing generation CURRENT domain."
    },
    {
      "field": "previous",
      "type": "RootGenerationJournalInputsV1 {journal: File,witness: File,config: CellGenerationObserverConfigV1}",
      "already_defined_by_current_cli": false,
      "required_source": "Retained read-only original A journal and its independent physical witness with exact generation/record/schema context.",
      "reason": "Learning request digests and profile do not identify file descriptors, inodes or witness configuration."
    },
    {
      "field": "target",
      "type": "RootGenerationJournalInputsV1 {journal: File,witness: File,config: CellGenerationObserverConfigV1}",
      "already_defined_by_current_cli": false,
      "required_source": "Actual target files/config for the same selected manifest and successor operation; preserve the real pre-genesis/prepared lifecycle.",
      "reason": "A placeholder path, copied witness, newly fabricated config or already-filled fixture cannot substitute the original target."
    },
    {
      "field": "artifacts.root/trust/retained_current/storage_binding/withdrawal_floor",
      "type": "RootArtifactPublicationInputsV1 fields: PathBuf, ArtifactOwnerTrustV1, SignedCurrentArtifactHeadV1, Digest32, DatasetWithdrawalRegistry",
      "already_defined_by_current_cli": false,
      "required_source": "Original Artifact deployment trust and retained frontier/floor from its actual owner/read side.",
      "reason": "The Root issuer key and Learning/Model profile do not define Artifact publisher trust or the independent rollback floor; latest physical files alone are not an independent retained floor."
    },
    {
      "field": "artifacts.selector/signed_selection/files",
      "type": "ArtifactSelectionVerifierV1, SignedArtifactSelectionV1, AgentdGenerationSelectionFilesV1 {registry_snapshot: File,payload: File}",
      "already_defined_by_current_cli": false,
      "required_source": "Actual separately authorized Artifact selector trust/signature and the original verified registry/payload files after B or a legitimate retained decision.",
      "reason": "LocalDecision is a different protocol observation. Serialized opaque selection, signature bytes without original trust/files, or caller booleans cannot supply this capability."
    },
    {
      "field": "consumer/consumer_state_root/issuer_keys",
      "type": "RootPublicationFinalUseConsumerV1::{Device,Notes}, PathBuf, Vec<FinalUseIssuerTrustKey>",
      "already_defined_by_current_cli": "partly",
      "required_source": "One actual original consumer's non-Root schema3 store and full exact issuer keyring including retained rotation keys.",
      "reason": "Existing config identifies Root consumer frontier stores. Those paths are not the non-Root local schema3 root. The current issuer public key does not reconstruct a deployed full historical keyring."
    }
  ],
  "minimum_next_code_interface": {
    "same_process_worker": "Retain the returned original enrollment capability before Prepared is consumed; a bounded same-PID worker submits the actual typed enrollment once while serving is ACTIVE.",
    "trusted_material_source": "Define an explicit trusted Root deployment/material transfer contract for the fields above, preserving real descriptors, original trust/frontier pins and exact reserve/recover mode.",
    "late_material_event": "Define how that same Root receives the actual completed selection/material event after B without caller-selected paths/trust on the CURRENT request wire.",
    "ready_order": "Enable original route before serve, send its sealed offer only from the original ready callback, continue original five-lane/learning/Model services, and register only from actual later original inputs.",
    "failure": "Consume once, preserve uncertain acknowledgement and original source/fence outcomes; do not re-sign, re-enroll or substitute a new operation.",
    "not_implemented_in_this_delta": true
  },
  "conclusion": "The missing default Root CLI layer is a concrete code/input-contract gap, not a claim of insufficient user authorization. Existing Root-only library constructors and same-service submission can implement it once the original deployment material source is explicitly defined. This delta completes daemon FD custody and deferred consumption; it deliberately adds no nonfunctional offer-only Root CLI path and no fabricated authority.",
  "authority_granted": false,
  "ordinary_chain_pass": false
}
