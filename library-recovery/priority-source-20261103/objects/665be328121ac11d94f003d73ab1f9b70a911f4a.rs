//! Research-only std CPU timing, no GPU or physical energy instrument.
use hcsn_research_cpu::ToyCells;
use std::time::Instant;

fn percentile(values: &[f64], quantile: f64) -> f64 {
    let mut v = values.to_vec();
    v.sort_by(|a, b| a.total_cmp(b));
    let index = (((v.len() - 1) as f64) * quantile).ceil() as usize;
    v[index]
}

fn main() {
    for cells in [64, 256, 1024, 4096] {
        let mut runner = ToyCells::new(cells).expect("registered n");
        let mut latency_ms = Vec::new();
        for _ in 0..96 {
            let start = Instant::now();
            runner.step().expect("valid state");
            latency_ms.push(start.elapsed().as_secs_f64() * 1e3);
        }
        let wall_sec: f64 = latency_ms.iter().sum::<f64>() / 1e3;
        let p95_ms = percentile(&latency_ms, 0.95);
        let p99_ms = percentile(&latency_ms, 0.99);
        println!(
            "{{\"cells\":{},\"kernel\":\"unverified_rust_cpu_research\",\"cell_updates_per_s\":{:.2},\"p95_ms\":{:.5},\"p99_ms\":{:.5},\"events\":96,\"energy_joules\":null,\"gpu_kernel\":false,\"recovery_proven\":false}}",
            cells, (cells * latency_ms.len()) as f64 / wall_sec, p95_ms, p99_ms
        );
    }
}
