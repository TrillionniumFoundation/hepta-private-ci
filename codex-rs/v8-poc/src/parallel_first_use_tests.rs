use std::sync::Arc;
use std::sync::Barrier;

use pretty_assertions::assert_eq;

#[test]
fn concurrent_first_isolates_evaluate_successfully() {
    // Other unit tests may already have initialized V8; execute this case in a fresh process.
    const CHILD: &str = "HEPTA_V8_FIRST_USE_CHILD";
    if std::env::var_os(CHILD).is_none() {
        let output = std::process::Command::new(std::env::current_exe().expect("test executable"))
            .args([
                "--exact",
                "parallel_first_use_tests::concurrent_first_isolates_evaluate_successfully",
                "--nocapture",
            ])
            .env(CHILD, "1")
            .output()
            .expect("run cold V8 process");
        assert!(
            output.status.success(),
            "cold process failed: {} {}",
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        );
        assert!(
            String::from_utf8_lossy(&output.stdout)
                .contains("hepta-v8-cold-first-use: 8 buffers verified")
        );
        return;
    }
    let barrier = Arc::new(Barrier::new(/*n*/ 8));
    let workers = (0..8)
        .map(|_| {
            let barrier = Arc::clone(&barrier);
            std::thread::spawn(move || {
                barrier.wait();
                super::tests::initialize_v8();
                barrier.wait();
                super::tests::evaluate_expression(
                    "const a = new Uint8Array(new ArrayBuffer(16)); a[0] = 3; a[0]",
                )
            })
        })
        .collect::<Vec<_>>();
    let results = workers
        .into_iter()
        .map(|worker| worker.join().expect("worker completes"))
        .collect::<Vec<_>>();
    assert_eq!(results, vec!["3".to_string(); 8]);
    println!("hepta-v8-cold-first-use: 8 buffers verified");
}
