use std::io::BufRead;
use std::io::BufReader;
use std::io::ErrorKind;
use std::io::Write;
use std::os::unix::net::UnixListener;
use std::sync::mpsc::SyncSender;
use std::sync::mpsc::TryRecvError;
use std::sync::mpsc::sync_channel;
use std::time::Duration;

use codex_hepta_contracts::AgentId;
use pretty_assertions::assert_eq;

use super::AgentHealthProbeIdentity;
use super::HealthProbeObservation;
use super::health_diagnostics::HealthProbeDiagnostics;
use super::health_diagnostics::HealthProbeFailure;
use super::health_diagnostics::HealthProbeFailureKind;
use super::health_diagnostics::HealthProbeReport;
use super::health_diagnostics::try_enqueue_report;
use super::query_agent_health_once;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;

fn identity(temp: &tempfile::TempDir) -> TestResult<AgentHealthProbeIdentity> {
    Ok(AgentHealthProbeIdentity {
        agent_id: AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?,
        spawn_generation: 7,
        process_id: std::process::id(),
        workspace: temp.path().join("workspace"),
        home_root: temp.path().join("home"),
        run_root: temp.path().join("run"),
        control_socket: temp.path().join("probe.sock"),
    })
}

#[test]
fn unresponsive_health_socket_retains_timeout_failure() -> TestResult {
    let temp = tempfile::tempdir()?;
    let identity = identity(&temp)?;
    let listener = UnixListener::bind(&identity.control_socket)?;
    let (release, wait) = std::sync::mpsc::sync_channel(/*bound*/ 1);
    let worker = std::thread::spawn(move || -> std::io::Result<()> {
        let (stream, _) = listener.accept()?;
        stream.set_read_timeout(Some(Duration::from_secs(/*secs*/ 2)))?;
        let mut reader = BufReader::new(stream);
        let mut request = Vec::new();
        reader.read_until(b'\n', &mut request)?;
        // Retain the live socket without a response until the real probe's
        // unchanged IO deadline has expired; do not depend on a timed sleep.
        wait.recv_timeout(Duration::from_secs(/*secs*/ 2))
            .map_err(std::io::Error::other)?;
        drop(reader);
        Ok(())
    });

    let result = query_agent_health_once(&identity, /*request_id*/ 17);
    release.send(())?;
    worker
        .join()
        .map_err(|_| std::io::Error::other("health fixture thread panicked"))??;
    assert!(matches!(
        result,
        Err(HealthProbeFailure {
            kind: HealthProbeFailureKind::Io(ErrorKind::TimedOut | ErrorKind::WouldBlock),
            ..
        })
    ));
    Ok(())
}

#[test]
fn malformed_health_response_retains_json_failure() -> TestResult {
    let temp = tempfile::tempdir()?;
    let identity = identity(&temp)?;
    let listener = UnixListener::bind(&identity.control_socket)?;
    let worker = std::thread::spawn(move || -> std::io::Result<()> {
        let (stream, _) = listener.accept()?;
        stream.set_read_timeout(Some(Duration::from_secs(/*secs*/ 2)))?;
        let mut reader = BufReader::new(stream);
        let mut request = Vec::new();
        reader.read_until(b'\n', &mut request)?;
        reader.get_mut().write_all(b"{invalid-json}\n")
    });

    let result = query_agent_health_once(&identity, /*request_id*/ 23);
    worker
        .join()
        .map_err(|_| std::io::Error::other("health fixture thread panicked"))??;
    assert!(matches!(
        result,
        Err(HealthProbeFailure {
            kind: HealthProbeFailureKind::Json(serde_json::error::Category::Syntax),
            ..
        })
    ));
    Ok(())
}

fn queue_loss_report(
    diagnostics: &mut HealthProbeDiagnostics,
    agent_id: &AgentId,
    request_id: u64,
    sender: Option<&SyncSender<HealthProbeReport>>,
) {
    diagnostics.record_with(
        agent_id,
        request_id,
        Duration::from_micros(/*micros*/ 19),
        &Ok(HealthProbeObservation {
            exact_identity: true,
            ready: false,
        }),
        |report| try_enqueue_report(sender, report),
    );
}

#[test]
fn full_diagnostic_queue_drops_reports_and_consumes_attempts() -> TestResult {
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let (sender, receiver) = sync_channel(/*bound*/ 1);
    let mut diagnostics = HealthProbeDiagnostics::default();
    for request_id in 1..=8 {
        // With no receiving thread, a blocking send would never finish once
        // the first report occupies this single-slot queue.
        queue_loss_report(&mut diagnostics, &agent_id, request_id, Some(&sender));
    }
    let mut bytes = Vec::new();
    receiver.try_recv()?.write_to(&mut bytes)?;
    assert_eq!(
        String::from_utf8(bytes)?,
        format!(
            "hepta-health agent={agent_id} request_id=1 elapsed_us=19 exact_identity=true ready=false report=1/8\n"
        )
    );
    assert!(matches!(receiver.try_recv(), Err(TryRecvError::Empty)));
    queue_loss_report(
        &mut diagnostics,
        &agent_id,
        /*request_id*/ 9,
        Some(&sender),
    );
    assert!(matches!(receiver.try_recv(), Err(TryRecvError::Empty)));
    Ok(())
}

#[test]
fn available_diagnostic_queue_retains_only_eight_probe_reports() -> TestResult {
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let (sender, receiver) = sync_channel(/*bound*/ 16);
    let mut diagnostics = HealthProbeDiagnostics::default();
    for request_id in 1..=12 {
        queue_loss_report(&mut diagnostics, &agent_id, request_id, Some(&sender));
    }
    for request_id in 1..=8 {
        let mut bytes = Vec::new();
        receiver.try_recv()?.write_to(&mut bytes)?;
        assert_eq!(
            String::from_utf8(bytes)?,
            format!(
                "hepta-health agent={agent_id} request_id={request_id} elapsed_us=19 exact_identity=true ready=false report={request_id}/8\n"
            )
        );
    }
    assert!(matches!(receiver.try_recv(), Err(TryRecvError::Empty)));
    Ok(())
}

#[test]
fn disconnected_or_unavailable_diagnostics_are_dropped() -> TestResult {
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let (sender, receiver) = sync_channel(/*bound*/ 1);
    drop(receiver);
    let mut diagnostics = HealthProbeDiagnostics::default();
    for request_id in 1..=4 {
        queue_loss_report(&mut diagnostics, &agent_id, request_id, Some(&sender));
    }
    for request_id in 5..=8 {
        // None is also the permanently cached result of a failed reporter
        // thread creation; it must not cause output on the health caller.
        queue_loss_report(
            &mut diagnostics,
            &agent_id,
            request_id,
            /*sender*/ None,
        );
    }
    let (available_sender, available_receiver) = sync_channel(/*bound*/ 1);
    queue_loss_report(
        &mut diagnostics,
        &agent_id,
        /*request_id*/ 9,
        Some(&available_sender),
    );
    assert!(matches!(
        available_receiver.try_recv(),
        Err(TryRecvError::Empty)
    ));
    Ok(())
}

#[test]
fn queued_diagnostics_retain_only_local_fields_and_fixed_categories() -> TestResult {
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let private_marker = "health-private-error-must-not-be-emitted";
    let io_failure =
        HealthProbeFailure::from(std::io::Error::new(ErrorKind::TimedOut, private_marker));
    assert!(format!("{io_failure:?}").contains(private_marker));
    let json_failure = serde_json::from_slice::<serde_json::Value>(b"{invalid-json}\n")
        .expect_err("fixture must be malformed JSON");
    let observations = [
        Ok(HealthProbeObservation {
            exact_identity: true,
            ready: false,
        }),
        Ok(HealthProbeObservation {
            exact_identity: false,
            ready: false,
        }),
        Err(io_failure),
        Err(HealthProbeFailure::from(json_failure)),
    ];
    let (sender, receiver) = sync_channel(/*bound*/ 4);
    let mut diagnostics = HealthProbeDiagnostics::default();
    for (index, observation) in observations.iter().enumerate() {
        diagnostics.record_with(
            &agent_id,
            101 + index as u64,
            Duration::from_micros(123_456 + index as u64),
            observation,
            |report| try_enqueue_report(Some(&sender), report),
        );
    }
    let mut bytes = Vec::new();
    for _ in 0..4 {
        receiver.try_recv()?.write_to(&mut bytes)?;
    }
    assert!(matches!(receiver.try_recv(), Err(TryRecvError::Empty)));
    let output = String::from_utf8(bytes)?;
    let expected = [
        format!(
            "hepta-health agent={agent_id} request_id=101 elapsed_us=123456 exact_identity=true ready=false report=1/8\n"
        ),
        format!(
            "hepta-health agent={agent_id} request_id=102 elapsed_us=123457 exact_identity=false ready=false report=2/8\n"
        ),
        format!(
            "hepta-health agent={agent_id} request_id=103 elapsed_us=123458 io_kind=TimedOut report=3/8\n"
        ),
        format!(
            "hepta-health agent={agent_id} request_id=104 elapsed_us=123459 json_category=Syntax report=4/8\n"
        ),
    ]
    .concat();
    assert_eq!(output, expected);
    assert!(!output.contains(private_marker));
    Ok(())
}
