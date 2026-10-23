use crate::hmi_fixture::ANSWER;
use crate::hmi_fixture::Fixture;
use crate::hmi_fixture::Profile;
use crate::hmi_fixture::sends;
use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use core_test_support::responses;
use serde::Serialize;
use serde_json::json;
use std::time::Duration;
use std::time::Instant;
use tokio::io::AsyncWriteExt;
use wiremock::Mock;
use wiremock::ResponseTemplate;
use wiremock::matchers::method;
use wiremock::matchers::path_regex;

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn owner_rejects_32_competing_inputs_and_oversize_frames_then_accepts_a_fresh_session()
-> Result<()> {
    let model = responses::start_mock_server().await;
    Mock::given(method("POST"))
        .and(path_regex(".*/responses$"))
        .respond_with(
            ResponseTemplate::new(200)
                .insert_header("content-type", "text/event-stream")
                .set_body_string(responses::sse(vec![
                    responses::ev_assistant_message("pressure-held", ANSWER),
                    responses::ev_completed("pressure-held-response"),
                ]))
                .set_delay(Duration::from_secs(30)),
        )
        .mount(&model)
        .await;
    let fixture = Fixture::new(&model, Profile::Text).await?;
    let mut ui = fixture.ui().await?;
    ui.send(json!({"type":"submit","request":fixture.request(1)?}))
        .await?;
    ui.until("admission").await?;
    tokio::time::timeout(Duration::from_secs(10), async {
        while sends(&model).await != 1 {
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await?;
    for sequence in 2..=33 {
        ui.send(json!({"type":"submit","request":fixture.request(sequence)?}))
            .await?;
        loop {
            let event = ui.next().await?;
            ensure!(
                event["type"] != "sessionError" && event["type"] != "admission",
                "pressure admitted an extra input or lost the session: {event}"
            );
            if event["type"] == "inputError" {
                ensure!(
                    event["error"]
                        .as_str()
                        .context("pressure reason")?
                        .contains("Busy"),
                    "{event}"
                );
                break;
            }
        }
    }
    ensure!(sends(&model).await == 1);
    ui.send(json!({"type":"interrupt"})).await?;
    ui.until("outputRetired").await?;
    ui.until("interruptRequested").await?;
    loop {
        let event = ui.next().await?;
        if event["type"] == "output" && event["outcome"]["event"]["kind"]["type"] == "terminal" {
            ensure!(
                event["outcome"]["event"]["kind"]["outcome"]["status"] == "interrupted",
                "{event}"
            );
            break;
        }
    }
    ui.send(json!({"type":"stop"})).await?;
    ui.until("sessionTerminal").await?;
    drop(ui);
    let mut oversize = fixture.ui().await?;
    oversize.write.write_all(&vec![b' '; 65537]).await?;
    let rejected = oversize.next().await?;
    ensure!(
        rejected["type"] == "sessionError"
            && rejected["error"]
                .as_str()
                .context("frame bound")?
                .contains("64 KiB"),
        "{rejected}"
    );
    drop(oversize);
    let mut fresh = fixture.ui().await?;
    fresh
        .send(json!({"type":"attach","request":fixture.request(2)?}))
        .await?;
    fresh.until("attached").await?;
    fresh.send(json!({"type":"stop"})).await?;
    fresh.until("sessionTerminal").await?;
    ensure!(sends(&model).await == 1);
    // Also exercise the existing principal registry, independently of device policy.
    crate::authbus_fixture::write_trust(
        &fixture.trust,
        &fixture.agent.agent_id,
        &fixture.key,
        std::slice::from_ref(&fixture.thread),
        /*revoked*/ true,
    )?;
    let mut revoked = fixture.ui().await?;
    revoked
        .send(json!({"type":"attach","request":fixture.request(2)?}))
        .await?;
    ensure!(revoked.next().await?["type"] == "sessionError");
    println!(
        "HMI_SOFTWARE_PRESSURE={{\"competingInputsRejected\":32,\"oversizeBytesRejected\":65537,\"modelRequests\":1,\"freshSessionAccepted\":true}}"
    );
    Ok(())
}

#[cfg(target_os = "linux")]
#[derive(Debug, Serialize)]
struct ResourceSample {
    turns: u64,
    rss_bytes: u64,
    open_fds: usize,
    threads: u64,
    evidence_bytes: u64,
    media_bytes: u64,
}
#[cfg(target_os = "linux")]
fn resource(fixture: &Fixture, turns: u64) -> Result<ResourceSample> {
    let status = std::fs::read_to_string(format!("/proc/{}/status", fixture.pid))?;
    let number = |name: &str| -> Result<u64> {
        Ok(status
            .lines()
            .find(|l| l.starts_with(name))
            .context("process metric")?
            .split_whitespace()
            .nth(1)
            .context("metric value")?
            .parse()?)
    };
    let evidence = fixture
        .agent
        .layout
        .home_root()
        .join(codex_hepta_evidence::EVIDENCE_DATABASE_LINEAGE);
    let evidence_bytes = [
        evidence.clone(),
        std::path::PathBuf::from(format!("{}-wal", evidence.display())),
        std::path::PathBuf::from(format!("{}-shm", evidence.display())),
    ]
    .iter()
    .filter_map(|p| std::fs::metadata(p).ok().map(|m| m.len()))
    .sum();
    let media_bytes = std::fs::read_dir(fixture.agent.layout.home_root().join("media"))?
        .map(|e| Ok(e?.metadata()?.len()))
        .sum::<Result<u64>>()?;
    Ok(ResourceSample {
        turns,
        rss_bytes: number("VmRSS:")? * 1024,
        threads: number("Threads:")?,
        open_fds: std::fs::read_dir(format!("/proc/{}/fd", fixture.pid))?.count(),
        evidence_bytes,
        media_bytes,
    })
}

#[cfg(target_os = "linux")]
#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn forty_audio_observations_bound_software_resources_after_warmup_without_losing_history()
-> Result<()> {
    const WARMUP: u64 = 8;
    const MEASURED: u64 = 32;
    let model = responses::start_mock_server().await;
    Mock::given(method("POST"))
        .and(path_regex(".*/responses$"))
        .respond_with(
            ResponseTemplate::new(200)
                .insert_header("content-type", "text/event-stream")
                .set_body_string(responses::sse(vec![
                    responses::ev_assistant_message("resource-answer", ANSWER),
                    responses::ev_completed("resource-response"),
                ])),
        )
        .mount(&model)
        .await;
    let fixture = Fixture::new(&model, Profile::TemporaryAudio).await?;
    let mut samples = Vec::new();
    let mut latency = Vec::new();
    for sequence in 1..=WARMUP + MEASURED {
        let request = fixture.audio(sequence, &[0; 3200])?;
        let mut ui = fixture.ui().await?;
        let started = Instant::now();
        ui.send(json!({"type":"submitAudio","request":request}))
            .await?;
        ui.until("admission").await?;
        ui.completed().await?;
        if sequence > WARMUP {
            latency.push(u64::try_from(started.elapsed().as_micros())?);
        }
        ui.send(json!({"type":"stop"})).await?;
        ui.until("sessionTerminal").await?;
        drop(ui);
        if sequence >= WARMUP && sequence % 8 == 0 {
            tokio::time::sleep(Duration::from_millis(50)).await;
            samples.push(resource(&fixture, sequence)?);
        }
    }
    let baseline = samples.first().context("warmup resource baseline")?;
    for sample in &samples[1..] {
        ensure!(
            sample.rss_bytes <= baseline.rss_bytes + 32 * 1024 * 1024,
            "RSS grew more than the declared 32 MiB regression allowance: {samples:?}"
        );
        ensure!(
            sample.open_fds <= baseline.open_fds + 4,
            "owner leaked descriptors across connection retirement: {samples:?}"
        );
        ensure!(
            sample.threads <= baseline.threads + 4,
            "owner leaked workers across connection retirement: {samples:?}"
        );
    }
    ensure!(sends(&model).await == usize::try_from(WARMUP + MEASURED)?);
    let thread = fixture.read_thread().await?;
    ensure!(thread.thread.turns.len() == usize::try_from(WARMUP + MEASURED)?);
    ensure!(
        samples.last().context("last resource sample")?.media_bytes == 3200 * (WARMUP + MEASURED),
        "retained audio has incorrect expected growth"
    );
    let pool = fixture.evidence_pool().await?;
    let rows: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM authbus_outbox")
        .fetch_one(&pool)
        .await?;
    ensure!(
        rows == i64::try_from(WARMUP + MEASURED)?
            && rows < codex_hepta_evidence::AUTHBUS_OUTBOX_MAX_ROWS
    );
    pool.close().await;
    latency.sort_unstable();
    let percentile = |p: usize| latency[(latency.len() * p).div_ceil(100) - 1];
    println!(
        "HMI_SOFTWARE_RESOURCE={}",
        json!({"scope":"actual Agentd and embedded App Server, temporary signed PCM observations, HTTP SSE fixture; not physical audio or long-run product acceptance",
        "warmupTurns":WARMUP,"measuredTurns":MEASURED,"samples":samples,"canonicalRows":rows,"outboxRowBound":codex_hepta_evidence::AUTHBUS_OUTBOX_MAX_ROWS,
        "sendToTerminalMicroseconds":{"p50":percentile(50),"p95":percentile(95),"p99":percentile(99),"samples":latency}})
    );
    ensure!(
        thread
            .thread
            .turns
            .iter()
            .flat_map(|t| t.items.iter())
            .filter(|item| matches!(
                item,
                codex_app_server_protocol::ThreadItem::UserMessage { .. }
            ))
            .count()
            == usize::try_from(WARMUP + MEASURED)?
    );
    Ok(())
}
