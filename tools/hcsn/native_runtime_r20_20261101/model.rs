//! Public frozen model and causal action plan; no provider token tape is read here.
use crate::common::{Result, checksum, ensure, read, unseal};
use crate::numeric::{Matrix, N, State, belief, validate};
use std::collections::BTreeSet;
use std::path::Path;

const NUMERICAL_SEMANTICS_ABI: &str = "hcsn-r20-fp64-uniformization160-mu8-reset-before-propagate-v1";

pub struct Model {
    pub q: Matrix,
    pub emissions: Vec<Vec<f64>>,
    pub prior: State,
    pub id: u64,
}
pub struct Operation {
    pub action: String,
    pub ns: u64,
    pub opid: String,
    pub fee: u64,
}
impl Operation {
    pub fn paid(&self) -> bool {
        self.action == "READ" || self.action == "REFRESH"
    }
}
pub struct Plan {
    pub run: String,
    pub id: u64,
    pub operations: Vec<Operation>,
}
impl Model {
    fn bound(q: Matrix, emissions: Vec<Vec<f64>>, prior: State, text: &str) -> Result<Self> {
        let executable = std::env::current_exe()?;
        ensure(std::fs::metadata(&executable)?.len() <= 64 * 1024 * 1024, "executable capacity")?;
        let executable = std::fs::read(executable)?;
        let mut identity = NUMERICAL_SEMANTICS_ABI.as_bytes().to_vec();
        identity.extend_from_slice(&(text.len() as u64).to_be_bytes());
        identity.extend_from_slice(text.as_bytes());
        for value in q.iter().flatten().chain(emissions.iter().flatten()).chain(prior.iter()) {
            identity.extend_from_slice(&value.to_bits().to_be_bytes());
        }
        identity.extend_from_slice(&checksum(&executable).to_be_bytes());
        Ok(Self { q, emissions, prior, id: checksum(&identity) })
    }
    pub fn open(path: &Path) -> Result<Self> {
        let text = read(path)?;
        let mut fields = text.split_whitespace();
        let schema = fields.next().ok_or("model schema")?;
        let numbers: Vec<f64> = fields
            .map(str::parse)
            .collect::<std::result::Result<_, _>>()?;
        if schema == "HCSN_FINANCIAL_3_V1" {
            ensure(numbers.len() == 3 && numbers.iter().all(|x| x.is_finite()), "financial parameter dimension")?;
            let native = crate::financial::construct(numbers[0], numbers[1], numbers[2])?;
            ensure(native.boundary.is_finite() && native.boundary > 0.0, "financial boundary")?;
            let emissions: Vec<_> = native.read.into_iter().map(Vec::from)
                .chain(native.refresh.into_iter().map(Vec::from)).collect();
            validate(&native.q, &emissions)?;
            belief(&native.prior)?;
            return Self::bound(native.q, emissions, native.prior, &text);
        }
        ensure(schema == "HCSN_FINITE_40_V1", "model schema")?;
        ensure(
            numbers.len() == 2000 && numbers.iter().all(|x| x.is_finite()),
            "model dimension or finite numbers",
        )?;
        let mut q = [[0.0; N]; N];
        for (i, row) in q.iter_mut().enumerate() {
            row.copy_from_slice(&numbers[i * N..(i + 1) * N]);
        }
        let mut emissions = Vec::new();
        for (offset, columns) in [(1600, 5), (1800, 4)] {
            for i in 0..N {
                emissions.push(numbers[offset + i * columns..offset + (i + 1) * columns].to_vec());
            }
        }
        let mut prior = [0.0; N];
        prior.copy_from_slice(&numbers[1960..]);
        validate(&q, &emissions)?;
        belief(&prior)?;
        Self::bound(q, emissions, prior, &text)
    }
}
impl Plan {
    pub fn open(path: &Path, model: &Model) -> Result<Self> {
        let text = read(path)?;
        let mut lines = unseal(&text)?.lines();
        let h: Vec<_> = lines
            .next()
            .ok_or("missing plan header")?
            .split('\t')
            .collect();
        ensure(
            h.len() == 3
                && h[0] == "PLAN"
                && h[1].len() == 64
                && h[1].bytes().all(|x| x.is_ascii_hexdigit()),
            "plan header",
        )?;
        ensure(
            u64::from_str_radix(h[2], 16)? == model.id,
            "plan model binding",
        )?;
        let mut operations = Vec::new();
        let mut ids = BTreeSet::new();
        for line in lines {
            let v: Vec<_> = line.split('\t').collect();
            ensure(
                v.len() == 6
                    && v[0] == "CMD"
                    && v[1].parse::<usize>()? == operations.len()
                    && operations.len() < 64,
                "plan cursor or capacity",
            )?;
            let operation = Operation {
                action: v[2].into(),
                ns: v[3].parse()?,
                opid: v[4].into(),
                fee: v[5].parse()?,
            };
            ensure(
                operation.ns <= 20_000_000_000 && operation.fee <= 1_000_000_000_000,
                "plan resource bound",
            )?;
            ensure(
                matches!(
                    operation.action.as_str(),
                    "PROP" | "READ" | "REFRESH" | "RESET" | "MISSING"
                ),
                "plan action",
            )?;
            if operation.paid() {
                ensure(
                    !operation.opid.is_empty()
                        && operation.opid.len() <= 64
                        && operation
                            .opid
                            .bytes()
                            .all(|x| x.is_ascii_alphanumeric() || x == b'-'),
                    "plan opid",
                )?;
                ensure(ids.insert(operation.opid.clone()), "duplicate opid")?;
            } else {
                ensure(
                    operation.opid == "-" && operation.fee == 0,
                    "unpaid metadata",
                )?;
            }
            operations.push(operation);
        }
        ensure(!operations.is_empty(), "empty plan")?;
        Ok(Self {
            run: h[1].into(),
            id: checksum(text.as_bytes()),
            operations,
        })
    }
    pub fn binding(&self, model: &Model) -> String {
        format!("{}\t{:016x}\t{:016x}", self.run, model.id, self.id)
    }
}

pub fn apply(model: &Model, p: &State, op: &Operation, token: Option<usize>) -> Result<State> {
    let mut initial = *p;
    if op.action == "RESET" {
        initial = [0.0; N];
        for (i, value) in p.iter().enumerate() {
            initial[32 + i % 4] += value;
        }
    }
    let mut next = crate::numeric::evolve(&model.q, &initial, op.ns as f64 / 1e9, &[0.0; N])?.0;
    match op.action.as_str() {
        "READ" | "REFRESH" => {
            let (offset, columns) = if op.action == "READ" { (0, 5) } else { (N, 4) };
            let token = token.ok_or("missing receipt token")?;
            ensure(token < columns, "receipt token")?;
            let mut evidence = 0.0;
            for (i, value) in next.iter_mut().enumerate() {
                *value *= model.emissions[offset + i][token];
                evidence += *value;
            }
            ensure(
                evidence > 0.0 && evidence.is_finite(),
                "zero or underflowed receipt evidence",
            )?;
            for value in &mut next {
                *value /= evidence;
            }
        }
        "RESET" | "PROP" | "MISSING" => {}
        _ => return Err("unsupported action".into()),
    }
    belief(&next)?;
    Ok(next)
}
