use super::*;

#[test]
fn unknown_feature_transient_peaks_accumulate_and_overflow_fails_closed() {
    for first_transient in [2_048, u64::MAX - 1_024] {
        let mut resource_grant = grant();
        let second_transient = if first_transient == 2_048 {
            2_048
        } else {
            resource_grant.maximum_memory_bytes = u64::MAX;
            1
        };
        let driver = Driver {
            indeterminate: true,
            feature_transient_bytes: Some(first_transient),
            ..Driver::default()
        };
        let mut worker = InferenceWorker::new(
            /*now_ms*/ 100,
            "worker.pending-peak".to_string(),
            /*generation*/ 3,
            resource_grant,
            driver,
        )
        .expect("worker");
        worker.load_model(/*now_ms*/ 100, manifest()).expect("load");
        assert_eq!(
            worker
                .run_neuron_features(/*now_ms*/ 100, "model.1", neuron_feature_request())
                .expect("first unknown feature")
                .status,
            ExecutionStatus::Indeterminate
        );
        worker.driver.feature_transient_bytes = Some(second_transient);
        let mut second = neuron_feature_request();
        second.authorization.request_id = "request.2".to_string();
        assert_eq!(
            worker.run_neuron_features(/*now_ms*/ 100, "model.1", second),
            Err(Error::ModelCapacity)
        );
        assert_eq!(
            worker.active_requests,
            BTreeMap::from([
                ("request.1".to_string(), first_transient),
                ("request.2".to_string(), second_transient),
            ])
        );
        assert_eq!(
            worker.run(/*now_ms*/ 100, "model.1", request()),
            Err(Error::ModelCapacity)
        );
        assert_eq!(
            worker.unload_model(/*_now_ms*/ 100, "model.1"),
            Err(Error::ActiveRequests)
        );
        assert_eq!(worker.driver.feature_calls, 2);
    }
}

#[test]
fn unknown_feature_transient_charge_reduces_later_model_load_budget() {
    let mut resource_grant = grant();
    resource_grant.maximum_models = 3;
    let driver = Driver {
        indeterminate: true,
        ..Driver::default()
    };
    let mut worker = InferenceWorker::new(
        /*now_ms*/ 100,
        "worker.pending-load".to_string(),
        /*generation*/ 3,
        resource_grant,
        driver,
    )
    .expect("worker");
    worker.load_model(/*now_ms*/ 100, manifest()).expect("load");
    worker
        .run_neuron_features(/*now_ms*/ 100, "model.1", neuron_feature_request())
        .expect("unknown feature");
    let mut second = manifest();
    second.model_id = "model.2".to_string();
    worker
        .load_model(/*now_ms*/ 100, second)
        .expect("resident plus unknown transient fits exactly");
    let mut third = manifest();
    third.model_id = "model.3".to_string();
    assert_eq!(
        worker.load_model(/*now_ms*/ 100, third),
        Err(Error::ModelCapacity)
    );
    assert_eq!(worker.driver.loaded, 2);
    assert_eq!(worker.driver.unload_calls, 1);
    worker
        .unload_model(grant().expires_at_ms, "model.2")
        .expect("idle cleanup does not release another request's charge");
    assert_eq!(
        worker.active_requests,
        BTreeMap::from([("request.1".to_string(), 2_048)])
    );
    assert_eq!(
        worker.unload_model(grant().expires_at_ms, "model.1"),
        Err(Error::ActiveRequests)
    );
}

#[test]
fn unknown_feature_transient_charge_applies_to_terminal_run_and_feature_peaks() {
    for feature_call in [false, true] {
        let driver = Driver {
            indeterminate: true,
            ..Driver::default()
        };
        let mut worker = InferenceWorker::new(
            /*now_ms*/ 100,
            "worker.pending-observation".to_string(),
            /*generation*/ 3,
            grant(),
            driver,
        )
        .expect("worker");
        worker.load_model(/*now_ms*/ 100, manifest()).expect("load");
        worker
            .run_neuron_features(/*now_ms*/ 100, "model.1", neuron_feature_request())
            .expect("unknown feature");
        worker.driver.indeterminate = false;
        if feature_call {
            worker.driver.feature_transient_bytes = Some(2_049);
            let mut second = neuron_feature_request();
            second.authorization.request_id = "request.2".to_string();
            assert_eq!(
                worker.run_neuron_features(/*now_ms*/ 100, "model.1", second),
                Err(Error::ModelCapacity)
            );
        } else {
            worker.driver.run_memory_bytes = Some(2_049);
            let mut second = request();
            second.request_id = "request.2".to_string();
            assert_eq!(
                worker.run(/*now_ms*/ 100, "model.1", second),
                Err(Error::ModelCapacity)
            );
        }
        assert_eq!(
            worker.active_requests,
            BTreeMap::from([("request.1".to_string(), 2_048)])
        );
        assert_eq!(
            worker.models.get("model.1").expect("model").active_requests,
            1
        );
        assert_eq!(
            worker.unload_model(/*_now_ms*/ 100, "model.1"),
            Err(Error::ActiveRequests)
        );
        assert!(worker.resource_fenced);
    }
}

#[test]
fn terminal_feature_releases_only_its_own_transient_peak() {
    let driver = Driver {
        indeterminate: true,
        ..Driver::default()
    };
    let mut worker = InferenceWorker::new(
        /*now_ms*/ 100,
        "worker.terminal-peak".to_string(),
        /*generation*/ 3,
        grant(),
        driver,
    )
    .expect("worker");
    worker.load_model(/*now_ms*/ 100, manifest()).expect("load");
    worker
        .run_neuron_features(/*now_ms*/ 100, "model.1", neuron_feature_request())
        .expect("unknown feature");
    worker.driver.indeterminate = false;
    worker.driver.feature_transient_bytes = Some(1_024);
    let mut second = neuron_feature_request();
    second.authorization.request_id = "request.2".to_string();
    assert_eq!(
        worker
            .run_neuron_features(/*now_ms*/ 100, "model.1", second)
            .expect("terminal peak fits with unknown request")
            .status,
        ExecutionStatus::Succeeded
    );
    assert_eq!(
        worker.active_requests,
        BTreeMap::from([("request.1".to_string(), 2_048)])
    );
    let mut next_model = manifest();
    next_model.model_id = "model.2".to_string();
    worker
        .load_model(/*now_ms*/ 100, next_model)
        .expect("terminal invocation no longer consumes transient budget");
    assert_eq!(worker.driver.loaded, 2);
    assert!(!worker.resource_fenced);
}

#[test]
fn feature_errors_and_short_circuits_preserve_unknown_transient_charge() {
    let driver = Driver {
        indeterminate: true,
        ..Driver::default()
    };
    let mut worker = InferenceWorker::new(
        /*now_ms*/ 100,
        "worker.pending-short-circuit".to_string(),
        /*generation*/ 3,
        grant(),
        driver,
    )
    .expect("worker");
    worker.load_model(/*now_ms*/ 100, manifest()).expect("load");
    worker
        .run_neuron_features(/*now_ms*/ 100, "model.1", neuron_feature_request())
        .expect("unknown feature");
    worker.driver.fail_run = true;
    let mut second = neuron_feature_request();
    second.authorization.request_id = "request.2".to_string();
    assert_eq!(
        worker.run_neuron_features(/*now_ms*/ 100, "model.1", second),
        Err(Error::DriverFailure("unknown feature outcome".to_string()))
    );
    let mut duplicate = neuron_feature_request();
    duplicate.authorization.cancelled = true;
    assert_eq!(
        worker.run_neuron_features(/*now_ms*/ 100, "model.1", duplicate),
        Err(Error::RequestCapacity)
    );
    assert_eq!(
        worker.run_neuron_features(request().deadline_ms, "model.1", neuron_feature_request()),
        Err(Error::DeadlineExpired)
    );
    let mut cancelled = neuron_feature_request();
    cancelled.authorization.request_id = "request.3".to_string();
    cancelled.authorization.cancelled = true;
    assert_eq!(
        worker
            .run_neuron_features(/*now_ms*/ 100, "model.1", cancelled)
            .expect("new cancelled request has no invocation")
            .status,
        ExecutionStatus::Cancelled
    );
    assert_eq!(
        worker.run_neuron_features(grant().expires_at_ms, "model.1", neuron_feature_request()),
        Err(Error::GrantExpired)
    );
    assert_eq!(
        worker.active_requests,
        BTreeMap::from([
            ("request.1".to_string(), 2_048),
            ("request.2".to_string(), 0),
        ])
    );
    assert_eq!(
        worker.models.get("model.1").expect("model").active_requests,
        2
    );
    assert_eq!(worker.driver.feature_calls, 2);
}
