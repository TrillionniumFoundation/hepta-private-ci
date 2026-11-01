//! Standalone research CTMC executor. No production owner or cryptographic trust.
//! Checkpoints retain pending absolute jump time, destination, RNG, and counters.
use std::fs::OpenOptions;
use std::fs::{self};
use std::io::Write;

type Result<T> = std::result::Result<T, String>;

fn fingerprint(bytes: &[u8]) -> u64 {
    bytes.iter().fold(14695981039346656037, |h, b| {
        (h ^ u64::from(*b)).wrapping_mul(1099511628211)
    })
}
fn uint(s: &str) -> Result<u64> {
    s.parse().map_err(|_| "invalid integer".into())
}
fn hex(s: &str) -> Result<u64> {
    u64::from_str_radix(s, 16).map_err(|_| "invalid hexadecimal value".into())
}
fn real(s: &str) -> Result<f64> {
    let x = f64::from_bits(hex(s)?);
    if !x.is_finite() {
        return Err("nonfinite value".into());
    }
    Ok(x)
}
fn read(path: &str) -> Result<String> {
    let metadata = fs::metadata(path).map_err(|e| e.to_string())?;
    if metadata.len() > 100000 {
        return Err("oversized research input".into());
    }
    fs::read_to_string(path).map_err(|e| e.to_string())
}
fn create(path: &str, text: &str) -> Result<()> {
    let mut f = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|e| e.to_string())?;
    f.write_all(text.as_bytes()).map_err(|e| e.to_string())?;
    f.sync_all().map_err(|e| e.to_string())
}

struct Model {
    n: usize,
    active: usize,
    q: Vec<f64>,
    identity: u64,
}
impl Model {
    fn load(path: &str) -> Result<Self> {
        let source = read(path)?;
        let fields: Vec<_> = source.split_whitespace().collect();
        if fields.len() < 3 || fields[0] != "HCNR1" {
            return Err("bad model schema".into());
        }
        let n = uint(fields[1])? as usize;
        let active = uint(fields[2])? as usize;
        if !(5..=257).contains(&n) || active + 2 != n || fields.len() != 3 + n * n {
            return Err("invalid model dimensions".into());
        }
        let q: Vec<_> = fields[3..].iter().map(|s| real(s)).collect::<Result<_>>()?;
        for i in 0..n {
            let row = &q[i * n..(i + 1) * n];
            if row[i] >= 0. || row.iter().sum::<f64>().abs() > 2e-12 {
                return Err("invalid generator row".into());
            }
            for (j, rate) in row.iter().enumerate() {
                if i != j && (*rate < 0. || (i >= active && j >= active && *rate != 0.)) {
                    return Err("invalid generator edge".into());
                }
            }
        }
        Ok(Self {
            n,
            active,
            q,
            identity: fingerprint(source.as_bytes()),
        })
    }
}

struct PathState {
    time: f64,
    state: usize,
    rng: u64,
    pending: Option<(f64, usize)>,
    counts: [u64; 2],
    jumps: u64,
}
impl PathState {
    fn uniform(&mut self) -> f64 {
        let mut x = self.rng;
        x ^= x >> 12;
        x ^= x << 25;
        x ^= x >> 27;
        self.rng = x;
        let word = x.wrapping_mul(2685821657736338717);
        ((word >> 12) as f64 + 0.5) / 4503599627370496.0
    }
    fn advance(&mut self, model: &Model, until: f64) -> Result<String> {
        if !until.is_finite() || until < self.time || until > 1000000. {
            return Err("invalid target time".into());
        }
        let mut trace = String::new();
        loop {
            if self.pending.is_none() {
                let rate = -model.q[self.state * model.n + self.state];
                let at = self.time - self.uniform().ln() / rate;
                let u = self.uniform() * rate;
                let mut total = 0.;
                let mut target = None;
                for j in 0..model.n {
                    if j != self.state {
                        total += model.q[self.state * model.n + j];
                        if u < total {
                            target = Some(j);
                            break;
                        }
                    }
                }
                if !at.is_finite() || at <= self.time {
                    return Err("invalid sampled waiting time".into());
                }
                self.pending = Some((at, target.ok_or("invalid sampled edge")?));
            }
            let (at, next) = self.pending.ok_or("missing pending jump")?;
            if at > until {
                self.time = until;
                return Ok(trace);
            }
            let previous = self.state;
            self.time = at;
            self.state = next;
            self.pending = None;
            self.jumps += 1;
            if self.jumps > 10000000 {
                return Err("bounded jump budget exhausted".into());
            }
            if previous < model.active && next >= model.active {
                let side = next - model.active;
                self.counts[side] += 1;
                let sign = if side == 0 { -1 } else { 1 };
                trace.push_str(&format!("{{\"time\":{at:.17e},\"side\":{sign}}}\n"));
            }
            if trace.len() > 10000000 {
                return Err("bounded event trace budget exhausted".into());
            }
        }
    }
    fn encode(&self, model: &Model) -> Result<String> {
        let (at, target) = self
            .pending
            .ok_or("checkpoint requires scheduled successor")?;
        let body = format!(
            "HCNC1 {:016x} {} {} {:016x} {} {} {:016x} {} {} {} {}\n",
            model.identity,
            model.n,
            model.active,
            self.time.to_bits(),
            self.state,
            self.rng,
            at.to_bits(),
            target,
            self.counts[0],
            self.counts[1],
            self.jumps
        );
        Ok(format!("{body}{:016x}\n", fingerprint(body.as_bytes())))
    }
    fn decode(path: &str, model: &Model) -> Result<Self> {
        let source = read(path)?;
        let lines: Vec<_> = source.lines().collect();
        if lines.len() != 2 || fingerprint(format!("{}\n", lines[0]).as_bytes()) != hex(lines[1])? {
            return Err("checkpoint checksum mismatch".into());
        }
        let f: Vec<_> = lines[0].split_whitespace().collect();
        if f.len() != 12
            || f[0] != "HCNC1"
            || hex(f[1])? != model.identity
            || uint(f[2])? as usize != model.n
            || uint(f[3])? as usize != model.active
        {
            return Err("checkpoint model/schema mismatch".into());
        }
        let time = real(f[4])?;
        let state = uint(f[5])? as usize;
        let rng = uint(f[6])?;
        let at = real(f[7])?;
        let next = uint(f[8])? as usize;
        let counts = [uint(f[9])?, uint(f[10])?];
        let jumps = uint(f[11])?;
        if time < 0.
            || at <= time
            || state >= model.n
            || next >= model.n
            || state == next
            || rng == 0
            || jumps > 10000000
            || counts[0].checked_add(counts[1]).is_none_or(|n| n > jumps)
            || model.q[state * model.n + next] <= 0.
        {
            return Err("invalid checkpoint state".into());
        }
        Ok(Self {
            time,
            state,
            rng,
            pending: Some((at, next)),
            counts,
            jumps,
        })
    }
}

fn execute(args: &[String]) -> Result<()> {
    let (model, mut state, until, checkpoint, trace) = match args.get(1).map(String::as_str) {
        Some("new") if args.len() == 8 => {
            let model = Model::load(&args[2])?;
            let rng = uint(&args[3])?;
            let start = uint(&args[7])? as usize;
            if rng == 0 || start >= model.n { return Err("invalid initial state/seed".into()); }
            let state = PathState { time: 0., state: start, rng, pending: None, counts: [0, 0], jumps: 0 };
            (model, state, &args[4], &args[5], &args[6])
        }
        Some("resume") if args.len() == 7 => {
            let model = Model::load(&args[2])?;
            let state = PathState::decode(&args[3], &model)?;
            (model, state, &args[4], &args[5], &args[6])
        }
        Some("switch") if args.len() == 8 => {
            let old_model = Model::load(&args[2])?;
            let model = Model::load(&args[3])?;
            let mut state = PathState::decode(&args[4], &old_model)?;
            if model.n != old_model.n || model.active != old_model.active {
                return Err("cannot change state space".into());
            }
            if model.q != old_model.q { state.pending = None; }
            (model, state, &args[5], &args[6], &args[7])
        }
        _ => return Err("usage: new MODEL SEED UNTIL CHECKPOINT TRACE START; resume MODEL CHECKPOINT UNTIL NEXT TRACE; switch OLD_MODEL NEW_MODEL CHECKPOINT UNTIL NEXT TRACE".into()),
    };
    let until = until.parse().map_err(|_| "invalid target time")?;
    let events = state.advance(&model, until)?;
    create(trace, &events)?;
    create(checkpoint, &state.encode(&model)?)?;
    println!(
        "{{\"time\":{},\"state\":{},\"lower_events\":{},\"upper_events\":{},\"jumps\":{}}}",
        state.time, state.state, state.counts[0], state.counts[1], state.jumps
    );
    Ok(())
}
fn main() {
    if let Err(error) = execute(&std::env::args().collect::<Vec<_>>()) {
        eprintln!("{error}");
        std::process::exit(2);
    }
}
