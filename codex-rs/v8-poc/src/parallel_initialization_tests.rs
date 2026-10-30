use pretty_assertions::assert_eq;
use std::sync::Barrier;

#[test]
fn parallel_isolates_allocate_backing_stores_after_initialization() {
    let barrier = Barrier::new(4);
    std::thread::scope(|scope| {
        let workers: Vec<_> = (0..4)
            .map(|_| {
                scope.spawn(|| {
                    barrier.wait();
                    super::tests::evaluate_expression(
                        "(() => { const bytes = new Uint8Array(4096); bytes[4095] = 37; return bytes[4095]; })()",
                    )
                })
            })
            .collect();
        for worker in workers {
            assert_eq!(worker.join().expect("isolate worker should finish"), "37");
        }
    });
}
