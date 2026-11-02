//! Forecast once, then own the physical observation protocol separately.
use crate::common::{Result, atomic, ensure, fault, lock, read, seal, unseal};
use crate::mailbox::rpc;
use crate::model::{Beliefs, Decision, Model};
use std::path::Path;
struct State {
    run: String,
    identity: String,
    checkpoint: String,
    generation: u64,
    q: usize,
    phase: String,
    key: usize,
    dt: f64,
    start: f64,
    deadline: f64,
    scale: f64,
    model_clock: f64,
    physical_clock: f64,
    step: usize,
    fee: u64,
    total_fee: u64,
    token: i32,
    answer: usize,
    read: bool,
    beliefs: Beliefs,
    details: [f32; 43],
    rows: Vec<String>,
}
impl State {
    fn new(run: &str, model: &Model) -> Self {
        Self {
            run: run.into(),
            identity: model.identity.clone(),
            checkpoint: model.checkpoint_sha.clone(),
            generation: 0,
            q: 0,
            phase: "open".into(),
            key: 0,
            dt: 0.,
            start: 0.,
            deadline: 0.,
            scale: 0.,
            model_clock: 0.,
            physical_clock: 0.,
            step: 0,
            fee: 0,
            total_fee: 0,
            token: -1,
            answer: 0,
            read: false,
            beliefs: [[0.; 40]; 4],
            details: [0.; 43],
            rows: Vec::new(),
        }
    }
    fn text(&self) -> String {
        let mut s = format!(
            "LEARNED_OWNER\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{:.17e}\t{:.17e}\t{:.17e}\t{:.17e}\t{:.17e}\t{:.17e}\t{}\t{}\t{}\t{}\t{}\t{}\n",
            self.run,
            self.identity,
            self.checkpoint,
            self.generation,
            self.q,
            self.phase,
            self.key,
            self.dt,
            self.start,
            self.deadline,
            self.scale,
            self.model_clock,
            self.physical_clock,
            self.step,
            self.fee,
            self.total_fee,
            self.token,
            self.answer,
            u8::from(self.read)
        );
        s.push_str("BELIEFS");
        for row in self.beliefs {
            for v in row {
                s.push_str(&format!("\t{v:.17e}"));
            }
        }
        s.push_str("\nDETAILS");
        for v in self.details {
            s.push_str(&format!("\t{v:.9e}"));
        }
        s.push('\n');
        for row in &self.rows {
            s.push_str(row);
            s.push('\n');
        }
        seal(&s)
    }
    fn load(path: &Path, run: &str, model: &Model) -> Result<Self> {
        if !path.exists() {
            return Ok(Self::new(run, model));
        }
        let text = read(path)?;
        let mut lines = unseal(&text)?.lines();
        let h: Vec<_> = lines.next().ok_or("owner header")?.split('\t').collect();
        ensure(
            h.len() == 20
                && h[0] == "LEARNED_OWNER"
                && h[1] == run
                && h[2] == model.identity
                && h[3] == model.checkpoint_sha,
            "trained owner context",
        )?;
        let mut s = Self::new(run, model);
        s.generation = h[4].parse()?;
        s.q = h[5].parse()?;
        s.phase = h[6].into();
        s.key = h[7].parse()?;
        s.dt = h[8].parse()?;
        s.start = h[9].parse()?;
        s.deadline = h[10].parse()?;
        s.scale = h[11].parse()?;
        s.model_clock = h[12].parse()?;
        s.physical_clock = h[13].parse()?;
        s.step = h[14].parse()?;
        s.fee = h[15].parse()?;
        s.total_fee = h[16].parse()?;
        s.token = h[17].parse()?;
        s.answer = h[18].parse()?;
        let bought: u8 = h[19].parse()?;
        ensure(bought <= 1, "read boolean")?;
        s.read = bought == 1;
        let p: Vec<_> = lines.next().ok_or("beliefs")?.split('\t').collect();
        ensure(p.len() == 161 && p[0] == "BELIEFS", "belief shape")?;
        for i in 0..4 {
            for j in 0..40 {
                s.beliefs[i][j] = p[1 + i * 40 + j].parse()?;
            }
        }
        let d: Vec<_> = lines.next().ok_or("decision")?.split('\t').collect();
        ensure(d.len() == 44 && d[0] == "DETAILS", "decision shape")?;
        for i in 0..43 {
            s.details[i] = d[i + 1].parse()?;
        }
        s.rows = lines.map(str::to_string).collect();
        ensure(
            s.q <= 6 && s.key < 4 && s.step <= 3 && s.answer < 4 && s.rows.len() <= 6,
            "owner bounds",
        )?;
        ensure(
            s.rows.len() == s.q + usize::from(s.phase == "submit") && s.total_fee >= s.fee,
            "trained cursor/row/fee consistency",
        )?;
        ensure(
            [
                s.dt,
                s.start,
                s.deadline,
                s.scale,
                s.model_clock,
                s.physical_clock,
            ]
            .iter()
            .all(|v| v.is_finite() && *v >= 0.)
                && s.details.iter().all(|v| v.is_finite()),
            "nonfinite trained state",
        )?;
        ensure(
            matches!(
                s.phase.as_str(),
                "open"
                    | "opened"
                    | "forecasted"
                    | "wait_pending"
                    | "refresh_pending"
                    | "observed"
                    | "submit"
            ),
            "trained owner phase",
        )?;
        for row in &s.beliefs {
            let initial = s.q == 0 && s.phase == "open" && row.iter().all(|v| *v == 0.);
            // Preserve the original FP32 symbol-softmax mass; do not renormalize.
            ensure(
                row.iter().all(|v| v.is_finite() && *v >= 0.)
                    && (initial || (row.iter().sum::<f64>() - 1.).abs() <= 1e-6),
                "trained belief profile",
            )?;
        }
        let near = |a: f64, b: f64| (a - b).abs() <= 1e-10;
        let clocks = match s.phase.as_str() {
            "open" => near(s.model_clock, s.physical_clock),
            "opened" => {
                s.step == 0 && near(s.model_clock, s.start) && near(s.physical_clock, s.start)
            }
            "forecasted" | "wait_pending" => {
                s.step == 0 && near(s.model_clock, s.deadline) && near(s.physical_clock, s.start)
            }
            "refresh_pending" => {
                s.step == 1
                    && near(s.model_clock, s.deadline)
                    && near(s.physical_clock, s.start + s.dt)
            }
            "observed" => {
                s.read
                    && s.step == 3
                    && near(s.model_clock, s.deadline)
                    && near(s.physical_clock, s.deadline)
            }
            "submit" => {
                near(s.model_clock, s.deadline)
                    && if s.read {
                        s.step == 3 && near(s.physical_clock, s.deadline)
                    } else {
                        s.step == 0 && near(s.physical_clock, s.start)
                    }
            }
            _ => false,
        };
        ensure(clocks, "trained model/physical clock phase mismatch")?;
        Ok(s)
    }
    fn remember(&mut self, d: &Decision) {
        self.read = d.read;
        self.answer = d.answer_before;
        let mut i = 0;
        for v in d
            .pre_logits
            .into_iter()
            .chain(d.pre_prob)
            .chain(d.post_logits.into_iter().flatten())
            .chain(d.post_prob.into_iter().flatten())
            .chain([d.read_value, d.action_gap, d.min_head_gap])
        {
            self.details[i] = v;
            i += 1;
        }
    }
    fn record(&mut self) {
        let mut row = format!("ROW\t{}\t{}\t{}", self.q, u8::from(self.read), self.answer);
        for belief in self.beliefs {
            for v in belief {
                row.push_str(&format!("\t{v:.17e}"));
            }
        }
        for v in self.details {
            row.push_str(&format!("\t{v:.9e}"));
        }
        self.rows.push(row);
    }
}
fn request(s: &State, kind: &str, extra: &str) -> String {
    format!("{kind}\t{}\t{}\t{extra}", s.run, s.generation)
}
fn action(
    s: &State,
    mailbox: &Path,
    kind: &str,
    from: usize,
    name: &str,
) -> Result<(i32, f64, u64)> {
    let opid = format!("{}:{}:{name}", s.run, s.q);
    let reply = rpc(
        mailbox,
        &request(s, "ACT", &format!("{}\t{from}\t{kind}\t{opid}", s.q)),
    )?;
    let p: Vec<_> = reply.split('\t').collect();
    let to = from + if kind == "REFRESH" { 2 } else { 1 };
    ensure(
        p.len() == 7
            && p[0] == "ACT"
            && p[1].parse::<usize>()? == s.q
            && p[2].parse::<usize>()? == to
            && p[6] == opid,
        "trained actual completion",
    )?;
    let at: f64 = p[4].parse()?;
    ensure(
        at.is_finite() && (at - (s.start + to as f64 * s.dt)).abs() < 1e-10,
        "trained observation clock",
    )?;
    Ok((p[3].parse()?, at, p[5].parse()?))
}
pub fn run(
    profile: &Path,
    path: &Path,
    mailbox: &Path,
    run: &str,
    stop: &str,
    marker: &Path,
) -> Result<()> {
    let mut model = Model::open(profile)?;
    let lock_path = path.with_extension("lock");
    let lease_guard = lock(&lock_path)?;
    let mut s = State::load(path, run, &model)?;
    let reply = rpc(mailbox, &format!("LEASE\t{run}"))?;
    let p: Vec<_> = reply.split('\t').collect();
    ensure(p.len() == 2 && p[0] == "LEASE", "trained lease")?;
    s.generation = p[1].parse()?;
    atomic(path, &s.text())?;
    drop(lease_guard);
    while s.q < 6 {
        let guard = lock(&lock_path)?;
        let current = State::load(path, run, &model)?;
        ensure(
            current.generation == s.generation && current.q == s.q && current.phase == s.phase,
            "stale trained owner",
        )?;
        rpc(mailbox, &format!("CHECK\t{run}\t{}", s.generation))?;
        let stage = match s.phase.as_str() {
            "open" => {
                let reply = rpc(mailbox, &request(&s, "OPEN", &s.q.to_string()))?;
                let p: Vec<_> = reply.split('\t').collect();
                ensure(
                    p.len() == 9 && p[0] == "OPEN" && p[1].parse::<usize>()? == s.q,
                    "trained public query",
                )?;
                s.key = p[2].parse()?;
                s.dt = p[3].parse()?;
                s.start = p[4].parse()?;
                s.deadline = p[5].parse()?;
                s.scale = p[6].parse()?;
                ensure(
                    s.key < 4
                        && s.dt.is_finite()
                        && s.dt > 0.
                        && s.start.is_finite()
                        && s.start >= 0.
                        && s.deadline.is_finite()
                        && s.deadline >= s.start
                        && s.scale.is_finite()
                        && s.scale >= 0.
                        && (s.deadline - (s.start + 3. * s.dt)).abs() < 1e-10,
                    "invalid trained public query metadata",
                )?;
                ensure(
                    (s.model_clock - s.start).abs() < 1e-10
                        && (s.physical_clock - s.start).abs() < 1e-10,
                    "trained query clocks",
                )?;
                if s.q == 0 {
                    let v: Vec<usize> = p[7]
                        .split(',')
                        .map(str::parse)
                        .collect::<std::result::Result<_, _>>()?;
                    ensure(v.len() == 4, "trained initial values")?;
                    s.beliefs = model.initial([v[0], v[1], v[2], v[3]])?;
                }
                if p[8] != "-" {
                    for write in p[8].split(',') {
                        let v: Vec<_> = write.split(':').collect();
                        ensure(v.len() == 2, "trained public write")?;
                        model.write(&mut s.beliefs, v[0].parse()?, v[1].parse()?)?;
                    }
                }
                s.step = 0;
                s.fee = 0;
                s.token = -1;
                s.phase = "opened".into();
                "opened"
            }
            "opened" => {
                model.advance(&mut s.beliefs, 3. * s.dt)?;
                s.model_clock = s.deadline;
                fault("forecast_before_commit", stop, marker)?;
                s.phase = "forecasted".into();
                "forecasted"
            }
            "forecasted" => {
                let fee = (0.07 * s.scale + 0.003 * 3. * s.dt) as f32;
                let d = model.choose(&s.beliefs, s.key, fee)?;
                s.remember(&d);
                if s.read {
                    s.phase = "wait_pending".into();
                } else {
                    s.answer = model.answer(&s.beliefs, s.key)?.0;
                    s.record();
                    s.phase = "submit".into();
                }
                "chosen"
            }
            "wait_pending" => {
                let (token, at, purchase) = action(&s, mailbox, "WAIT", 0, "wait")?;
                ensure(token == -1 && purchase == 0, "trained WAIT receipt")?;
                fault("wait_response_before_commit", stop, marker)?;
                s.step = 1;
                s.physical_clock = at;
                let time = (0.003 * s.dt * 1e6).round() as u64;
                s.fee += time;
                s.total_fee += time;
                s.phase = "refresh_pending".into();
                "wait_committed"
            }
            "refresh_pending" => {
                let (token, at, purchase) = action(&s, mailbox, "REFRESH", 1, "refresh")?;
                ensure((0..4).contains(&token), "trained READ token")?;
                ensure(
                    purchase == (0.07 * s.scale * 1e6).round() as u64,
                    "trained purchase price",
                )?;
                fault("refresh_response_before_commit", stop, marker)?;
                s.token = token;
                s.step = 3;
                s.physical_clock = at;
                let time = (0.003 * 2. * s.dt * 1e6).round() as u64;
                s.fee += time + purchase;
                s.total_fee += time + purchase;
                s.phase = "observed".into();
                "refresh_inbox"
            }
            "observed" => {
                model.apply_read(&mut s.beliefs, s.key, s.token as usize)?;
                s.answer = model.answer(&s.beliefs, s.key)?.0;
                fault("read_apply_before_commit", stop, marker)?;
                s.record();
                s.phase = "submit".into();
                "read_applied"
            }
            "submit" => {
                let opid = format!("{}:{}:submit", s.run, s.q);
                let reply = rpc(
                    mailbox,
                    &request(
                        &s,
                        "SUBMIT",
                        &format!("{}\t{}\t{}\t{opid}", s.q, s.step, s.answer),
                    ),
                )?;
                ensure(
                    reply == format!("ACK\t{}\t{opid}", s.q),
                    "trained submit ack",
                )?;
                fault("submit_response_before_commit", stop, marker)?;
                s.physical_clock = s.deadline;
                s.q += 1;
                s.phase = "open".into();
                "boundary"
            }
            _ => return Err("unknown trained owner phase".into()),
        };
        atomic(path, &s.text())?;
        drop(guard);
        fault(stage, stop, marker)?;
    }
    println!(
        "COMPLETE\t{}\t{}\t{}",
        s.checkpoint, s.generation, s.total_fee
    );
    Ok(())
}
