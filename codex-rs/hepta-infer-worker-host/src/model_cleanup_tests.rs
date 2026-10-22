use super::*;

#[test]
fn cleanup_owned_is_sticky_even_for_malformed_or_foreign_opaque_handles() {
    for fault in [Fault::Unknown, Fault::Error] {
        for cleanup_handle in [
            owned(/*sequence*/ 2),
            DriverLoadState::Owned(DriverModelHandle {
                opaque_id: "bad handle".to_string(),
                observed_memory_bytes: KIB,
            }),
            owned(/*sequence*/ 1),
        ] {
            let mut worker = worker(Fault::Owned);
            worker.grant.maximum_memory_bytes = 2 * KIB;
            worker.load_model(NOW_MS, manifest(), KIB).expect("first");
            let first = worker.models["model.1"].handle.clone();
            worker.driver.fault = fault;
            assert!(worker.load_model(NOW_MS, other(), KIB).is_err());
            let attempt = worker.models["model.2"].attempt.clone();
            worker.driver.reply = Some(cleanup_handle);
            assert!(worker.unload_model(NOW_MS, "model.2").is_err());
            worker.driver.reply = Some(DriverLoadState::NoEffect);
            assert!(worker.unload_model(NOW_MS, "model.2").is_err());
            assert_eq!(
                worker.models["model.2"].lifecycle,
                ModelLifecycle::LoadRejected
            );
            assert_eq!(worker.reconcile_load("model.2"), Err(Error::ActiveRequests));
            let third = ModelManifest {
                model_id: "model.3".to_string(),
                ..manifest()
            };
            assert_eq!(
                worker.load_model(NOW_MS, third.clone(), KIB),
                Err(Error::ActiveRequests)
            );
            assert_eq!(
                worker.driver.live.values().map(Vec::len).sum::<usize>(),
                2 * KIB as usize
            );
            assert_eq!(worker.driver.loads.len(), 2);
            assert_eq!(
                worker.driver.releases,
                vec![attempt.clone(), attempt.clone()]
            );
            assert_eq!(worker.models["model.1"].handle, first);
            worker.driver.reply = None;
            worker
                .unload_model(NOW_MS, "model.2")
                .expect("original Released");
            assert_eq!(
                worker.driver.releases,
                vec![attempt.clone(), attempt.clone(), attempt]
            );
            assert_eq!(
                worker.driver.live.keys().copied().collect::<Vec<_>>(),
                vec![1]
            );
            worker.driver.fault = Fault::Owned;
            worker
                .load_model(NOW_MS, third, KIB)
                .expect("budget released only now");
            assert_eq!(
                worker.driver.live.values().map(Vec::len).sum::<usize>(),
                2 * KIB as usize
            );
        }
    }
}
