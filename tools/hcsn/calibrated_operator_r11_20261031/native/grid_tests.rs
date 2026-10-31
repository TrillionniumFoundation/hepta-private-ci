use crate::grid::Grid;
use crate::task::Public;

fn public() -> Public {
    Public {
        id: "fixture".into(),
        deadline: 6,
        budget: 2,
        reliability: vec![vec![0.9; 6]; 2],
        price: vec![vec![0.01; 6]; 2],
        duration: vec![1.; 6],
        packets: vec![vec![String::new(); 6]; 2],
        packet_sha256: vec![vec![String::new(); 6]; 2],
        multiplier: 1.,
        latency_price: 0.01,
    }
}

#[test]
fn last_slot_has_only_stop_and_fire_and_stop_is_zero() {
    let g = Grid::new(&public(), [[0.99, 0.01], [0.01, 0.99]], 129).unwrap();
    let q = g.q(1, 5, 2, 0.8);
    assert_eq!(q[0], 0.);
    assert!(q[1].is_infinite() && q[2].is_infinite());
    assert!((q[3] - 0.59).abs() < 1e-12);
}

#[test]
fn fire_preserves_later_job_value_and_skip_preserves_budget() {
    let mut p = public();
    p.reliability[0][0] = 0.5;
    let g = Grid::new(&p, [[0.99, 0.01], [0.01, 0.99]], 129).unwrap();
    let q = g.q(0, 0, 2, 0.5);
    assert!(q[3] > 0.5, "future job must survive FIRE");
    assert!(q[1] > q[2], "uninformative paid READ must lose to SKIP");
    let mut expensive = p;
    expensive.latency_price = 10.;
    let g = Grid::new(&expensive, [[0.99, 0.01], [0.01, 0.99]], 129).unwrap();
    assert_eq!(g.q(0, 0, 2, 0.5).into_iter().fold(0., f64::max), 0.);
}
