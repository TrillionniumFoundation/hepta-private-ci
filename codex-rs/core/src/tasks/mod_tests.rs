use super::TASK_COMPACT_METRIC;
use super::emit_compact_metric;
use super::emit_turn_memory_metric;
use super::emit_turn_network_proxy_metric;
use super::qualification_admission_identity;
use codex_otel::MetricsClient;
use codex_otel::MetricsConfig;
use codex_otel::SessionTelemetry;
use codex_otel::TURN_MEMORY_METRIC;
use codex_otel::TURN_NETWORK_PROXY_METRIC;
use codex_protocol::AgentPath;
use codex_protocol::ThreadId;
use codex_protocol::protocol::InterAgentCommunication;
use codex_protocol::protocol::SessionSource;
use codex_protocol::user_input::UserInput;
use opentelemetry::KeyValue;
use opentelemetry_sdk::metrics::InMemoryMetricExporter;
use opentelemetry_sdk::metrics::data::AggregatedMetrics;
use opentelemetry_sdk::metrics::data::Metric;
use opentelemetry_sdk::metrics::data::MetricData;
use opentelemetry_sdk::metrics::data::ResourceMetrics;
use pretty_assertions::assert_eq;
use std::collections::BTreeMap;

use super::TurnInput;

#[tokio::test]
async fn terminal_publication_requires_exact_registry_owner_and_occurs_once() {
    use crate::session::tests::make_session_and_context_with_rx;
    use crate::state::StartTransitionCompletion;
    use crate::state::TaskTerminalizationKind;
    use std::cell::Cell;
    use std::sync::Arc;

    #[derive(Clone, Copy)]
    enum Registry {
        Start,
        Task,
    }

    for registry in [Registry::Start, Registry::Task] {
        let (session, _context, _rx) = make_session_and_context_with_rx().await;
        let identity = Arc::new(());
        let completion = StartTransitionCompletion::new();
        let published = Cell::new(0);
        let _active = session.active_turn.lock().await;
        match registry {
            Registry::Start => session.register_start_transition(
                Arc::clone(&identity),
                Arc::clone(&completion),
                Arc::new(std::sync::Mutex::new(None)),
            ),
            Registry::Task => session.register_task_terminalization(
                Arc::clone(&identity),
                Arc::clone(&completion),
                TaskTerminalizationKind::Finish,
                /*suspension_handoff*/ None,
                /*abort_handoff*/ None,
                /*finish_handoff*/ None,
            ),
        }
        let retire = |candidate_identity: &Arc<()>,
                      candidate_completion: &Arc<StartTransitionCompletion>| {
            let publish = || {
                assert!(
                    !completion.is_complete(),
                    "publication must precede shutdown's completion signal"
                );
                published.set(published.get() + 1);
            };
            match registry {
                Registry::Start => session.finish_start_transition_with_publication(
                    candidate_identity,
                    candidate_completion,
                    publish,
                ),
                Registry::Task => session.finish_task_terminalization_with_publication(
                    candidate_identity,
                    candidate_completion,
                    publish,
                ),
            }
        };
        assert!(!retire(&Arc::new(()), &completion));
        assert!(!retire(&identity, &StartTransitionCompletion::new()));
        assert_eq!(
            (
                published.get(),
                completion.is_complete(),
                session.has_pending_admission_fence()
            ),
            (0, false, true)
        );
        assert!(retire(&identity, &completion));
        assert!(
            !retire(&identity, &completion),
            "a retired owner must not publish twice"
        );
        assert_eq!(
            (
                published.get(),
                completion.is_complete(),
                session.has_pending_admission_fence()
            ),
            (1, true, false)
        );
    }
}

#[test]
fn qualification_admission_identity_requires_one_client_bound_user_input() {
    let content = vec![UserInput::Text {
        text: "hello".to_string(),
        text_elements: Vec::new(),
    }];
    let input = vec![TurnInput::UserInput {
        content: content.clone(),
        client_id: Some("client-1".to_string()),
    }];
    let identity = qualification_admission_identity("thread-1", &input).expect("durable identity");
    assert_eq!(identity.thread_scope_key, "thread-1");
    assert_eq!(identity.client_user_message_id, "client-1");
    assert_eq!(
        identity.payload_sha256,
        codex_protocol::user_input::user_input_payload_sha256(&content).expect("payload digest")
    );

    let without_client = vec![TurnInput::UserInput {
        content: content.clone(),
        client_id: None,
    }];
    assert!(qualification_admission_identity("thread-1", &without_client).is_none());

    let empty = vec![TurnInput::UserInput {
        content: Vec::new(),
        client_id: Some("client-1".to_string()),
    }];
    assert!(qualification_admission_identity("thread-1", &empty).is_none());

    let duplicate = vec![
        TurnInput::UserInput {
            content: content.clone(),
            client_id: Some("client-1".to_string()),
        },
        TurnInput::UserInput {
            content,
            client_id: Some("client-2".to_string()),
        },
    ];
    assert!(qualification_admission_identity("thread-1", &duplicate).is_none());

    let mixed_mailbox = vec![
        TurnInput::InterAgentCommunication(InterAgentCommunication::new(
            AgentPath::root(),
            AgentPath::root(),
            Vec::new(),
            "mailbox payload".to_string(),
            /*trigger_turn*/ true,
        )),
        TurnInput::UserInput {
            content: vec![UserInput::Text {
                text: "hello after mailbox".to_string(),
                text_elements: Vec::new(),
            }],
            client_id: Some("client-3".to_string()),
        },
    ];
    assert!(
        qualification_admission_identity("thread-1", &mixed_mailbox).is_none(),
        "mixed mailbox and user input must remain outside qualification admission"
    );
}

fn test_session_telemetry() -> SessionTelemetry {
    let exporter = InMemoryMetricExporter::default();
    let metrics = MetricsClient::new(
        MetricsConfig::in_memory("test", "codex-core", env!("CARGO_PKG_VERSION"), exporter)
            .with_runtime_reader(),
    )
    .expect("in-memory metrics client");
    SessionTelemetry::new(
        ThreadId::new(),
        "gpt-5.4",
        "gpt-5.4",
        /*account_id*/ None,
        /*account_email*/ None,
        /*auth_mode*/ None,
        "test_originator".to_string(),
        /*log_user_prompts*/ false,
        "tty".to_string(),
        SessionSource::Cli,
    )
    .with_metrics_without_metadata_tags(metrics)
}

fn find_metric<'a>(resource_metrics: &'a ResourceMetrics, name: &str) -> &'a Metric {
    for scope_metrics in resource_metrics.scope_metrics() {
        for metric in scope_metrics.metrics() {
            if metric.name() == name {
                return metric;
            }
        }
    }
    panic!("metric {name} missing");
}

fn attributes_to_map<'a>(
    attributes: impl Iterator<Item = &'a KeyValue>,
) -> BTreeMap<String, String> {
    attributes
        .map(|kv| (kv.key.as_str().to_string(), kv.value.as_str().to_string()))
        .collect()
}

fn metric_point(resource_metrics: &ResourceMetrics, name: &str) -> (BTreeMap<String, String>, u64) {
    let metric = find_metric(resource_metrics, name);
    match metric.data() {
        AggregatedMetrics::U64(data) => match data {
            MetricData::Sum(sum) => {
                let points: Vec<_> = sum.data_points().collect();
                assert_eq!(points.len(), 1);
                let point = points[0];
                (attributes_to_map(point.attributes()), point.value())
            }
            _ => panic!("unexpected counter aggregation"),
        },
        _ => panic!("unexpected counter data type"),
    }
}

#[test]
fn emit_turn_network_proxy_metric_records_active_turn() {
    let session_telemetry = test_session_telemetry();

    emit_turn_network_proxy_metric(
        &session_telemetry,
        /*network_proxy_active*/ true,
        ("tmp_mem_enabled", "true"),
    );

    let snapshot = session_telemetry
        .snapshot_metrics()
        .expect("runtime metrics snapshot");
    let (attrs, value) = metric_point(&snapshot, TURN_NETWORK_PROXY_METRIC);

    assert_eq!(value, 1);
    assert_eq!(
        attrs,
        BTreeMap::from([
            ("active".to_string(), "true".to_string()),
            ("tmp_mem_enabled".to_string(), "true".to_string()),
        ])
    );
}

#[test]
fn emit_turn_network_proxy_metric_records_inactive_turn() {
    let session_telemetry = test_session_telemetry();

    emit_turn_network_proxy_metric(
        &session_telemetry,
        /*network_proxy_active*/ false,
        ("tmp_mem_enabled", "false"),
    );

    let snapshot = session_telemetry
        .snapshot_metrics()
        .expect("runtime metrics snapshot");
    let (attrs, value) = metric_point(&snapshot, TURN_NETWORK_PROXY_METRIC);

    assert_eq!(value, 1);
    assert_eq!(
        attrs,
        BTreeMap::from([
            ("active".to_string(), "false".to_string()),
            ("tmp_mem_enabled".to_string(), "false".to_string()),
        ])
    );
}

#[test]
fn emit_turn_memory_metric_records_read_allowed_with_citations() {
    let session_telemetry = test_session_telemetry();

    emit_turn_memory_metric(
        &session_telemetry,
        /*feature_enabled*/ true,
        /*config_enabled*/ true,
        /*has_citations*/ true,
    );

    let snapshot = session_telemetry
        .snapshot_metrics()
        .expect("runtime metrics snapshot");
    let (attrs, value) = metric_point(&snapshot, TURN_MEMORY_METRIC);

    assert_eq!(value, 1);
    assert_eq!(
        attrs,
        BTreeMap::from([
            ("config_use_memories".to_string(), "true".to_string()),
            ("feature_enabled".to_string(), "true".to_string()),
            ("has_citations".to_string(), "true".to_string()),
            ("read_allowed".to_string(), "true".to_string()),
        ])
    );
}

#[test]
fn emit_turn_memory_metric_records_config_disabled_without_citations() {
    let session_telemetry = test_session_telemetry();

    emit_turn_memory_metric(
        &session_telemetry,
        /*feature_enabled*/ true,
        /*config_enabled*/ false,
        /*has_citations*/ false,
    );

    let snapshot = session_telemetry
        .snapshot_metrics()
        .expect("runtime metrics snapshot");
    let (attrs, value) = metric_point(&snapshot, TURN_MEMORY_METRIC);

    assert_eq!(value, 1);
    assert_eq!(
        attrs,
        BTreeMap::from([
            ("config_use_memories".to_string(), "false".to_string()),
            ("feature_enabled".to_string(), "true".to_string()),
            ("has_citations".to_string(), "false".to_string()),
            ("read_allowed".to_string(), "false".to_string()),
        ])
    );
}

#[test]
fn emit_compact_metric_records_manual_remote_v2() {
    let session_telemetry = test_session_telemetry();

    emit_compact_metric(&session_telemetry, "remote_v2", /*manual*/ true);

    let snapshot = session_telemetry
        .snapshot_metrics()
        .expect("runtime metrics snapshot");
    let (attrs, value) = metric_point(&snapshot, TASK_COMPACT_METRIC);

    assert_eq!(value, 1);
    assert_eq!(
        attrs,
        BTreeMap::from([
            ("manual".to_string(), "true".to_string()),
            ("type".to_string(), "remote_v2".to_string()),
        ])
    );
}

#[test]
fn emit_compact_metric_records_auto_local() {
    let session_telemetry = test_session_telemetry();

    emit_compact_metric(&session_telemetry, "local", /*manual*/ false);

    let snapshot = session_telemetry
        .snapshot_metrics()
        .expect("runtime metrics snapshot");
    let (attrs, value) = metric_point(&snapshot, TASK_COMPACT_METRIC);

    assert_eq!(value, 1);
    assert_eq!(
        attrs,
        BTreeMap::from([
            ("manual".to_string(), "false".to_string()),
            ("type".to_string(), "local".to_string()),
        ])
    );
}
