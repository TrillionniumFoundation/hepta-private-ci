use super::*;
use codex_hepta_paths::HeptaFleetRoot;
use codex_utils_absolute_path::AbsolutePathBuf;

#[tokio::test]
async fn exact_current_cut_recovers_both_native_and_verbatim_root_spellings() {
    for use_verbatim in [false, true] {
        let temp = TempDir::new().expect("temp dir");
        let owner = agent_id(232);
        let (store, _, _) = seeded(&temp, &owner).await;
        let anchor = store
            .recovery_anchor()
            .await
            .expect("trusted current witness");
        store.pool.close().await;
        drop(store);

        let native = AbsolutePathBuf::from_absolute_path(temp.path())
            .expect("absolute owned temporary root")
            .canonicalize()
            .expect("native temporary root")
            .join("fleet");
        let verbatim = native.as_path().canonicalize().expect("verbatim fleet");
        assert_ne!(native.as_path().as_os_str(), verbatim.as_os_str());
        let root = if use_verbatim {
            verbatim
        } else {
            native.as_path().to_path_buf()
        };
        let layout = HeptaFleetRoot::parse(root)
            .expect("owned fleet spelling")
            .layout()
            .agent(&owner);
        let recovered = CognitiveStore::open_with_recovery(
            &layout,
            CognitiveRecoveryRequirement::ExactCurrentCut(&anchor),
            &recovery_authority(&owner),
            &RecoveryVerifier,
        )
        .await
        .expect("original retained recovery admission");
        assert_eq!(
            recovered
                .recovery_anchor()
                .await
                .expect("recovered current witness"),
            anchor
        );
        recovered.pool.close().await;
        drop(recovered);
    }
}
