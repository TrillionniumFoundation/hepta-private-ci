#[path = "../examples/memory_cell_lab/data.rs"]
mod data;
#[path = "../examples/memory_cell_lab/model.rs"]
mod model;
#[path = "../examples/memory_cell_lab/retrieval.rs"]
mod retrieval;
#[path = "../examples/memory_cell_lab/controls.rs"]
mod controls;
#[path = "../examples/memory_cell_lab/report.rs"]
mod report;
use std::fs;
use std::process::Command;

#[test]
fn cluster_intervals_do_not_count_copied_episodes_as_new_evidence() {
    let score = report::Score { root: "one-source".into(), semantic: true, procedure: true,
        confidence: 0.8, nll: 0.2, brier: 0.1, latency_ns: 100, read_ops: 5, evidence_count: 0, scanned: 0 };
    let single = report::summarize(std::slice::from_ref(&score)).unwrap();
    let copies = report::summarize(&vec![score; 1000]).unwrap();
    assert_eq!((single.roots, single.lower, single.upper), (copies.roots, copies.lower, copies.upper));
    assert_ne!(single.rows, copies.rows);
    assert!(report::summarize(&[]).is_err());
}

#[test]
fn report_never_promotes_a_fixture_and_contains_all_controls() {
    let rows = data::parse(&data::smoke_corpus()).unwrap();
    let arms = controls::train_arms(&rows).unwrap();
    let text = report::experiment_report(&arms, &rows, 123, true).unwrap();
    assert!(text.contains("\"production_qualified\":false"));
    assert!(text.contains("\"citation_entailment_precision\":null"));
    assert_eq!(text.matches("\"arm\":").count(), 7);
    assert_eq!(text.matches("\"simultaneous_95_interval\":").count(), 21);
}

#[test]
fn clean_agent_transfer_uses_only_immutable_parameters_in_a_new_process() {
    let rows = data::parse(&data::smoke_corpus()).unwrap();
    let mut bundle = model::Bundle::new("lab-public".into(), &[4, 4]).unwrap();
    bundle.train(&rows, &mut model::Meter::default(), 1_000_000).unwrap();
    let dir = std::env::temp_dir().join(format!("hepta-clean-agent-{}", std::process::id()));
    fs::create_dir(&dir).unwrap();
    let path = dir.join("model.bundle");
    fs::write(&path, bundle.encode()).unwrap();
    let output = dir.join("prediction.txt");
    let query = &rows[128].query;
    let status = Command::new(std::env::current_exe().unwrap())
        .args(["--exact", "clean_agent_worker", "--ignored", "--nocapture"])
        .env("MCELL_BUNDLE", &path).env("MCELL_RESULT", &output)
        .env("MCELL_SCOPE", &query.scope).env("MCELL_DOMAIN", query.domain.to_string())
        .env("MCELL_QUERY", &query.text).status().unwrap();
    assert!(status.success());
    let p = bundle.infer(query).unwrap();
    let expected = format!("{} {}", model::argmax(&p[0]), model::argmax(&p[1]));
    assert_eq!(fs::read_to_string(&output).unwrap(), expected);
    // The worker receives neither the corpus nor predecessor working state.
    assert_eq!(fs::read_dir(&dir).unwrap().count(), 2);
    fs::remove_dir_all(dir).unwrap();
}

#[test]
#[ignore = "invoked explicitly in an isolated child process by the transfer test"]
fn clean_agent_worker() {
    let bundle = model::Bundle::decode(&fs::read_to_string(std::env::var("MCELL_BUNDLE").unwrap()).unwrap()).unwrap();
    let q = data::Query { scope: std::env::var("MCELL_SCOPE").unwrap(),
        domain: std::env::var("MCELL_DOMAIN").unwrap().parse().unwrap(),
        text: std::env::var("MCELL_QUERY").unwrap() };
    let p = bundle.infer(&q).unwrap();
    fs::write(std::env::var("MCELL_RESULT").unwrap(), format!("{} {}", model::argmax(&p[0]), model::argmax(&p[1]))).unwrap();
}
