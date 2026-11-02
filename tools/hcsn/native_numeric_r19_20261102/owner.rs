//! Native filter/controller owns state; the provider exposes only legal observations.
use crate::common::{Result, atomic, ensure, fault, lock, read, seal, unseal};
use crate::mailbox::rpc;
use crate::numeric::{self, Matrix, Model, N, Vector};
use std::path::Path;
#[derive(Clone)]
struct State {
    run: String,
    model: String,
    rep: String,
    generation: u64,
    q: usize,
    phase: String,
    key: usize,
    dt: f64,
    start: f64,
    deadline: f64,
    scale: f64,
    clock: f64,
    anchors: [f64; 4],
    beliefs: [Vector; 4],
    completed: usize,
    actions: usize,
    fee: u64,
    total_fee: u64,
    pending: usize,
    token: i32,
    purchase: u64,
    answer: usize,
    min_gap: f64,
    min_answer_gap: f64,
    trace: Vec<String>,
}
impl State {
    fn fresh(run: &str, model: &str, rep: &str) -> Self {
        Self {
            run: run.into(),
            model: model.into(),
            rep: rep.into(),
            generation: 0,
            q: 0,
            phase: "open".into(),
            key: 0,
            dt: 0.,
            start: 0.,
            deadline: 0.,
            scale: 0.,
            clock: 0.,
            anchors: [0.; 4],
            beliefs: [[0.; N]; 4],
            completed: 0,
            actions: 0,
            fee: 0,
            total_fee: 0,
            pending: 0,
            token: -1,
            purchase: 0,
            answer: 0,
            min_gap: 1.,
            min_answer_gap: 1.,
            trace: Vec::new(),
        }
    }
    fn text(&self) -> String {
        let mut s = format!(
            "STATE\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{:.17e}\t{:.17e}\t{:.17e}\t{:.17e}\t{:.17e}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{:.17e}\t{:.17e}\n",
            self.run,
            self.model,
            self.rep,
            self.generation,
            self.q,
            self.phase,
            self.key,
            self.dt,
            self.start,
            self.deadline,
            self.scale,
            self.clock,
            self.completed,
            self.actions,
            self.fee,
            self.total_fee,
            self.pending,
            self.token,
            self.purchase,
            self.answer,
            self.min_gap,
            self.min_answer_gap
        );
        s.push_str("ANCHORS");
        for x in self.anchors {
            s.push_str(&format!("\t{x:.17e}"));
        }
        s.push_str("\nBELIEFS");
        for p in self.beliefs {
            for x in p {
                s.push_str(&format!("\t{x:.17e}"));
            }
        }
        s.push('\n');
        for line in &self.trace {
            s.push_str(line);
            s.push('\n');
        }
        seal(&s)
    }
    fn open(path: &Path, run: &str, model: &str, rep: &str) -> Result<Self> {
        if !path.exists() {
            return Ok(Self::fresh(run, model, rep));
        }
        let text = read(path)?;
        let mut lines = unseal(&text)?.lines();
        let p: Vec<_> = lines.next().ok_or("state header")?.split('\t').collect();
        ensure(
            p.len() == 23 && p[0] == "STATE" && p[1] == run && p[2] == model && p[3] == rep,
            "state context",
        )?;
        let mut s = Self::fresh(run, model, rep);
        s.generation = p[4].parse()?;
        s.q = p[5].parse()?;
        s.phase = p[6].into();
        s.key = p[7].parse()?;
        s.dt = p[8].parse()?;
        s.start = p[9].parse()?;
        s.deadline = p[10].parse()?;
        s.scale = p[11].parse()?;
        s.clock = p[12].parse()?;
        s.completed = p[13].parse()?;
        s.actions = p[14].parse()?;
        s.fee = p[15].parse()?;
        s.total_fee = p[16].parse()?;
        s.pending = p[17].parse()?;
        s.token = p[18].parse()?;
        s.purchase = p[19].parse()?;
        s.answer = p[20].parse()?;
        s.min_gap = p[21].parse()?;
        s.min_answer_gap = p[22].parse()?;
        let anchors: Vec<_> = lines.next().ok_or("anchors")?.split('\t').collect();
        ensure(anchors.len() == 5 && anchors[0] == "ANCHORS", "anchors")?;
        for i in 0..4 {
            s.anchors[i] = anchors[i + 1].parse()?;
        }
        let beliefs: Vec<_> = lines.next().ok_or("beliefs")?.split('\t').collect();
        ensure(
            beliefs.len() == 161 && beliefs[0] == "BELIEFS",
            "belief shape",
        )?;
        for i in 0..4 {
            for j in 0..N {
                s.beliefs[i][j] = beliefs[1 + i * N + j].parse()?;
            }
        }
        s.trace = lines.map(str::to_string).collect();
        ensure(
            s.q <= 6 && s.key < 4 && s.completed <= 3 && s.trace.len() <= 128,
            "state bounds",
        )?;
        ensure(
            [
                s.dt,
                s.start,
                s.deadline,
                s.scale,
                s.clock,
                s.min_gap,
                s.min_answer_gap,
            ]
            .iter()
            .all(|x| x.is_finite() && *x >= 0.)
                && s.anchors
                    .iter()
                    .all(|x| x.is_finite() && *x >= 0. && *x <= s.clock)
                && matches!(
                    s.phase.as_str(),
                    "open" | "choose" | "prepared" | "elapsed" | "received" | "submit"
                ),
            "invalid owned clock/anchor/phase",
        )?;
        for p in &s.beliefs {
            let uninitialized = s.q == 0 && s.phase == "open" && p.iter().all(|v| *v == 0.);
            ensure(
                p.iter().all(|v| v.is_finite() && *v >= 0.)
                    && (uninitialized || (p.iter().sum::<f64>() - 1.).abs() <= 1e-8),
                "invalid owned probability",
            )?;
        }
        Ok(s)
    }
    fn materialize(&self, model: &mut Model, key: usize) -> Result<Vector> {
        if self.rep == "anchored" {
            Ok(numeric::row(
                &self.beliefs[key],
                &model.transition(self.clock - self.anchors[key])?,
            ))
        } else {
            Ok(self.beliefs[key])
        }
    }
    fn advance(&mut self, model: &mut Model, dt: f64) -> Result<()> {
        if dt > 0. {
            if self.rep == "full" {
                let p = model.transition(dt)?;
                for x in &mut self.beliefs {
                    *x = numeric::row(x, &p);
                }
            }
            self.clock += dt;
        }
        Ok(())
    }
    fn write(&mut self, model: &mut Model, key: usize, value: usize) -> Result<()> {
        ensure(key < 4 && value < 4, "write")?;
        let p = self.materialize(model, key)?;
        let mut out = [0.; N];
        for phase in 0..10 {
            out[phase * 4 + value] = p[phase * 4..phase * 4 + 4].iter().sum();
        }
        self.beliefs[key] = if self.rep == "anchored" {
            numeric::project(&out)
        } else {
            out
        };
        self.anchors[key] = self.clock;
        Ok(())
    }
}
const ACTIONS: [&str; 4] = ["STOP", "WAIT", "READ", "REFRESH"];
fn request(s: &State, kind: &str, extra: &str) -> String {
    format!("{kind}\t{}\t{}\t{extra}", s.run, s.generation)
}
pub fn run(
    model_path: &Path,
    path: &Path,
    mailbox: &Path,
    run: &str,
    rep: &str,
    stop: &str,
    marker: &Path,
) -> Result<()> {
    ensure(rep == "full" || rep == "anchored", "representation")?;
    let mut model = Model::open(model_path)?;
    let lock_path = path.with_extension("lock");
    let lease = lock(&lock_path)?;
    let mut s = State::open(path, run, &model.id, rep)?;
    let response = rpc(mailbox, &format!("LEASE\t{run}"))?;
    let r: Vec<_> = response.split('\t').collect();
    ensure(r.len() == 2 && r[0] == "LEASE", "lease")?;
    s.generation = r[1].parse()?;
    atomic(path, &s.text())?;
    drop(lease);
    while s.q < 6 {
        let guard = lock(&lock_path)?;
        let observed = State::open(path, run, &model.id, rep)?;
        ensure(
            observed.generation == s.generation && observed.q == s.q && observed.phase == s.phase,
            "stale native owner",
        )?;
        rpc(mailbox, &format!("CHECK\t{run}\t{}", s.generation))?;
        let stage = match s.phase.as_str() {
            "open" => {
                let response = rpc(mailbox, &request(&s, "OPEN", &s.q.to_string()))?;
                let r: Vec<_> = response.split('\t').collect();
                ensure(
                    r.len() == 9 && r[0] == "OPEN" && r[1].parse::<usize>()? == s.q,
                    "public query",
                )?;
                s.key = r[2].parse()?;
                s.dt = r[3].parse()?;
                s.start = r[4].parse()?;
                s.deadline = r[5].parse()?;
                s.scale = r[6].parse()?;
                ensure(
                    (s.clock - s.start).abs() < 1e-10 && s.dt > 0.,
                    "query clock",
                )?;
                if s.q == 0 {
                    let initial: Vec<_> = r[7]
                        .split(',')
                        .map(str::parse::<usize>)
                        .collect::<std::result::Result<_, _>>()?;
                    ensure(initial.len() == 4, "initial public writes")?;
                    for key in 0..4 {
                        s.beliefs[key] = if rep == "anchored" {
                            numeric::project(&model.prior)
                        } else {
                            model.prior
                        };
                        s.write(&mut model, key, initial[key])?;
                    }
                }
                if r[8] != "-" {
                    for pair in r[8].split(',') {
                        let p: Vec<_> = pair.split(':').collect();
                        ensure(p.len() == 2, "typed write")?;
                        s.write(&mut model, p[0].parse()?, p[1].parse()?)?;
                    }
                }
                s.completed = 0;
                s.actions = 0;
                s.fee = 0;
                s.phase = "choose".into();
                "opened"
            }
            "choose" => {
                let p = s.materialize(&mut model, s.key)?;
                let remaining = 3 - s.completed;
                let mut ps: [Matrix; 4] = [numeric::identity(); 4];
                for h in 1..4 {
                    ps[h] = model.transition(h as f64 * s.dt)?;
                }
                let values = numeric::values(
                    &model,
                    &p,
                    remaining,
                    s.dt,
                    0.025 * s.scale,
                    0.07 * s.scale,
                    rep == "anchored",
                    &ps,
                );
                let mut chosen = 0;
                for i in 1..4 {
                    if values[i] > values[chosen] {
                        chosen = i;
                    }
                }
                if remaining > 0 {
                    let second = values
                        .iter()
                        .enumerate()
                        .filter(|(i, _)| *i != chosen)
                        .map(|(_, v)| *v)
                        .fold(f64::NEG_INFINITY, f64::max);
                    let gap = values[chosen] - second;
                    s.min_gap = s.min_gap.min(gap);
                    ensure(
                        gap > 1e-7,
                        "UNCERTIFIED_ACTION_GAP: require independent reference fallback",
                    )?;
                }
                if chosen == 0 {
                    let (answer, answer_gap) = numeric::answer(&p, &ps[remaining]);
                    s.min_answer_gap = s.min_answer_gap.min(answer_gap);
                    ensure(
                        answer_gap > 1e-7,
                        "UNCERTIFIED_ANSWER_GAP: require independent reference fallback",
                    )?;
                    s.answer = answer;
                    s.advance(&mut model, remaining as f64 * s.dt)?;
                    s.phase = "submit".into();
                } else {
                    s.pending = chosen;
                    s.phase = "prepared".into();
                }
                "chosen"
            }
            "prepared" => {
                let slots = if s.pending == 3 { 2 } else { 1 };
                s.advance(&mut model, slots as f64 * s.dt)?;
                s.completed += slots;
                let fee = (0.003 * slots as f64 * s.dt * 1e6).round() as u64;
                s.fee += fee;
                s.total_fee += fee;
                s.phase = "elapsed".into();
                "elapsed"
            }
            "elapsed" => {
                let slots = if s.pending == 3 { 2 } else { 1 };
                let opid = format!("{}:{}:{}", s.run, s.q, s.actions);
                let response = rpc(
                    mailbox,
                    &request(
                        &s,
                        "ACT",
                        &format!(
                            "{}\t{}\t{}\t{opid}",
                            s.q,
                            s.completed - slots,
                            ACTIONS[s.pending]
                        ),
                    ),
                )?;
                let r: Vec<_> = response.split('\t').collect();
                ensure(
                    r.len() == 7
                        && r[0] == "ACT"
                        && r[1].parse::<usize>()? == s.q
                        && r[2].parse::<usize>()? == s.completed
                        && r[6] == opid,
                    "actual completion",
                )?;
                s.token = r[3].parse()?;
                ensure(
                    (r[4].parse::<f64>()? - s.clock).abs() < 1e-10,
                    "actual observation time",
                )?;
                s.purchase = r[5].parse()?;
                fault("received_before_commit", stop, marker)?;
                s.phase = "received".into();
                "received"
            }
            "received" => {
                if s.pending >= 2 {
                    let p = s.materialize(&mut model, s.key)?;
                    let posterior = model.observe(&p, s.token as usize, s.pending)?;
                    s.beliefs[s.key] = if rep == "anchored" {
                        numeric::project(&posterior)
                    } else {
                        posterior
                    };
                    s.anchors[s.key] = s.clock;
                } else {
                    ensure(s.token == -1 && s.purchase == 0, "WAIT completion")?;
                }
                s.fee += s.purchase;
                s.total_fee += s.purchase;
                s.trace.push(format!(
                    "ACTION\t{}\t{}\t{}\t{}\t{:.17e}\t{}",
                    s.q, ACTIONS[s.pending], s.completed, s.token, s.clock, s.purchase
                ));
                s.actions += 1;
                s.phase = "choose".into();
                "applied"
            }
            "submit" => {
                let opid = format!("{}:{}:submit", s.run, s.q);
                let response = rpc(
                    mailbox,
                    &request(
                        &s,
                        "SUBMIT",
                        &format!("{}\t{}\t{}\t{opid}", s.q, s.completed, s.answer),
                    ),
                )?;
                ensure(
                    response == format!("ACK\t{}\t{opid}", s.q),
                    "submission ack",
                )?;
                s.trace.push(format!(
                    "SUBMIT\t{}\t{}\t{}\t{}",
                    s.q, s.completed, s.answer, s.fee
                ));
                s.q += 1;
                s.phase = "open".into();
                "boundary"
            }
            _ => return Err("unknown native phase".into()),
        };
        atomic(path, &s.text())?;
        drop(guard);
        fault(stage, stop, marker)?;
    }
    println!(
        "COMPLETE\t{}\t{}\t{:.17e}\t{:.17e}\t{:.17e}",
        s.total_fee, s.generation, s.min_gap, model.max_tail, model.max_roundoff
    );
    Ok(())
}
