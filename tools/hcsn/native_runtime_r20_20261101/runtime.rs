//! One-host durable numeric owner and token provider; no network authentication.
use crate::common::{Result, atomic, checksum, ensure, fault, lock, read, seal, unseal};
use crate::model::{Model, Plan, apply};
use crate::numeric::{N, State, belief};
use crate::wire;
use std::collections::BTreeMap;
use std::net::TcpListener;
use std::path::Path;
use std::time::Duration;

#[derive(Clone)]
struct Receipt {
    index: usize,
    token: usize,
    ordinal: usize,
    text: String,
}
impl Receipt {
    fn parse(line: &str, model: &Model, plan: &Plan) -> Result<Self> {
        let v: Vec<_> = line.split('\t').collect();
        ensure(
            v.len() == 10 && v[0] == "EFFECT" && v[1..4].join("\t") == plan.binding(model),
            "receipt context",
        )?;
        let index: usize = v[4].parse()?;
        let token: usize = v[7].parse()?;
        let ordinal: usize = v[9].parse()?;
        let op = plan.operations.get(index).ok_or("receipt index")?;
        ensure(
            op.paid() && v[5] == op.opid && v[6] == op.action && v[8].parse::<u64>()? == op.fee,
            "receipt operation binding",
        )?;
        ensure(
            token < if op.action == "READ" { 5 } else { 4 },
            "receipt token range",
        )?;
        ensure(ordinal > 0 && ordinal <= 64, "receipt ordinal")?;
        let text = format!(
            "EFFECT\t{}\t{index}\t{}\t{}\t{token}\t{}\t{ordinal}",
            plan.binding(model),
            op.opid,
            op.action,
            op.fee
        );
        ensure(text == line, "noncanonical receipt")?;
        Ok(Self {
            index,
            token,
            ordinal,
            text,
        })
    }
}
fn ledger(lines: impl Iterator<Item = String>, model: &Model, plan: &Plan) -> Result<Vec<Receipt>> {
    let expected: Vec<_> = plan
        .operations
        .iter()
        .enumerate()
        .filter(|(_, op)| op.paid())
        .map(|(i, _)| i)
        .collect();
    let mut result = Vec::new();
    for line in lines {
        let receipt = Receipt::parse(&line, model, plan)?;
        ensure(
            expected.get(result.len()) == Some(&receipt.index)
                && receipt.ordinal == result.len() + 1,
            "ledger prefix",
        )?;
        result.push(receipt);
    }
    Ok(result)
}
fn fees(receipts: &[Receipt], plan: &Plan) -> Result<u64> {
    receipts.iter().try_fold(0_u64, |total, item| {
        total
            .checked_add(plan.operations[item.index].fee)
            .ok_or_else(|| "fee overflow".into())
    })
}
fn stop(stage: &str, index: usize, requested: &str, marker: &Path) -> Result<()> {
    if requested == stage || requested == format!("{stage}:{index}") {
        fault(requested, requested, marker)?;
    }
    Ok(())
}

struct Owned {
    p: State,
    cursor: usize,
    time: u64,
    charged: u64,
    pending: Option<usize>,
    receipts: Vec<Receipt>,
}
impl Owned {
    fn open(path: &Path, model: &Model, plan: &Plan) -> Result<Self> {
        if !path.exists() {
            return Ok(Self {
                p: model.prior,
                cursor: 0,
                time: 0,
                charged: 0,
                pending: None,
                receipts: Vec::new(),
            });
        }
        let text = read(path)?;
        let mut lines = unseal(&text)?.lines();
        let v: Vec<_> = lines.next().ok_or("owner header")?.split('\t').collect();
        ensure(
            v.len() == 8 && v[0] == "OWNER" && v[1..4].join("\t") == plan.binding(model),
            "owner context",
        )?;
        let cursor: usize = v[4].parse()?;
        let time: u64 = v[5].parse()?;
        let charged: u64 = v[6].parse()?;
        let pending = if v[7] == "-" {
            None
        } else {
            Some(v[7].parse::<usize>()?)
        };
        let words: Vec<_> = lines.next().ok_or("owner posterior")?.split('\t').collect();
        ensure(
            words.len() == N + 1 && words[0] == "STATE",
            "owner posterior shape",
        )?;
        let mut p = [0.0; N];
        for (i, word) in words[1..].iter().enumerate() {
            p[i] = f64::from_bits(u64::from_str_radix(word, 16)?);
        }
        belief(&p)?;
        let receipts = ledger(lines.map(String::from), model, plan)?;
        ensure(cursor <= plan.operations.len(), "owner cursor")?;
        let expected: Vec<_> = plan
            .operations
            .iter()
            .enumerate()
            .take(cursor)
            .filter(|(_, op)| op.paid())
            .map(|(i, _)| i)
            .collect();
        ensure(
            receipts.iter().map(|r| r.index).collect::<Vec<_>>() == expected,
            "owner receipt coverage",
        )?;
        ensure(
            time == plan.operations[..cursor].iter().map(|op| op.ns).sum()
                && charged == fees(&receipts, plan)?,
            "owner time or billing",
        )?;
        if let Some(index) = pending {
            ensure(
                index == cursor && plan.operations.get(index).is_some_and(|op| op.paid()),
                "owner pending cursor",
            )?;
        }
        Ok(Self {
            p,
            cursor,
            time,
            charged,
            pending,
            receipts,
        })
    }
    fn persist(&self, path: &Path, model: &Model, plan: &Plan) -> Result<()> {
        let pending = self
            .pending
            .map_or_else(|| "-".into(), |index| index.to_string());
        let words = self
            .p
            .iter()
            .map(|x| format!("{:016x}", x.to_bits()))
            .collect::<Vec<_>>()
            .join("\t");
        let mut text = format!(
            "OWNER\t{}\t{}\t{}\t{}\t{pending}\nSTATE\t{words}\n",
            plan.binding(model),
            self.cursor,
            self.time,
            self.charged
        );
        for r in &self.receipts {
            text.push_str(&format!("{}\n", r.text));
        }
        atomic(path, &seal(&text))
    }
}

pub fn owner(
    model: &Model,
    plan: &Plan,
    path: &Path,
    endpoint: &Path,
    requested: &str,
    marker: &Path,
) -> Result<()> {
    let _lock = lock(&path.with_extension("lock"))?;
    let existed = path.exists();
    let mut state = Owned::open(path, model, plan)?;
    let status = wire::rpc(endpoint, &format!("SYNC\t{}\n", plan.binding(model)))?;
    let mut lines = status.lines();
    let h: Vec<_> = lines.next().ok_or("status header")?.split('\t').collect();
    ensure(
        h.len() == 6 && h[0] == "STATUS" && h[1..4].join("\t") == plan.binding(model),
        "status context",
    )?;
    let remote = ledger(lines.map(String::from), model, plan)?;
    ensure(
        h[4].parse::<usize>()? == remote.len() && h[5].parse::<u64>()? == fees(&remote, plan)?,
        "status accounting",
    )?;
    ensure(
        existed || remote.is_empty(),
        "missing owner state with paid effects",
    )?;
    ensure(
        remote.len() >= state.receipts.len()
            && remote.len() <= state.receipts.len() + usize::from(state.pending.is_some()),
        "owner provider ledger gap",
    )?;
    for (owned, actual) in state.receipts.iter().zip(&remote) {
        ensure(
            owned.text == actual.text,
            "owner provider receipt disagreement",
        )?;
    }
    if remote.len() > state.receipts.len() {
        ensure(
            state.pending == Some(remote.last().ok_or("remote receipt")?.index),
            "unowned provider effect",
        )?;
    }
    if !existed {
        state.persist(path, model, plan)?;
        stop("owner_initialized", 0, requested, marker)?;
    }
    while state.cursor < plan.operations.len() {
        let index = state.cursor;
        let op = &plan.operations[index];
        let receipt = if op.paid() {
            if state.pending.is_none() {
                state.pending = Some(index);
                state.persist(path, model, plan)?;
            }
            stop("owner_prepared", index, requested, marker)?;
            let response = wire::rpc(
                endpoint,
                &format!(
                    "CALL\t{}\t{index}\t{}\t{}\t{}\n",
                    plan.binding(model),
                    op.opid,
                    op.action,
                    op.fee
                ),
            )?;
            let receipt = Receipt::parse(response.trim_end(), model, plan)?;
            ensure(
                receipt.index == index && receipt.ordinal == state.receipts.len() + 1,
                "reply cursor binding",
            )?;
            stop("owner_received", index, requested, marker)?;
            Some(receipt)
        } else {
            None
        };
        let next = apply(model, &state.p, op, receipt.as_ref().map(|r| r.token))?;
        stop("owner_computed", index, requested, marker)?;
        state.p = next;
        state.cursor += 1;
        state.time = state.time.checked_add(op.ns).ok_or("clock overflow")?;
        if let Some(receipt) = receipt {
            state.charged = state
                .charged
                .checked_add(op.fee)
                .ok_or("billing overflow")?;
            state.receipts.push(receipt);
        }
        state.pending = None;
        state.persist(path, model, plan)?;
        stop("owner_committed", index, requested, marker)?;
    }
    println!(
        "COMPLETE\t{}\t{}\t{}",
        state.cursor, state.time, state.charged
    );
    Ok(())
}

pub fn provider(
    model: &Model,
    plan: &Plan,
    catalog_path: &Path,
    path: &Path,
    endpoint: &Path,
    requested: &str,
    marker: &Path,
) -> Result<()> {
    let _lock = lock(&path.with_extension("lock"))?;
    let catalog_text = read(catalog_path)?;
    let catalog_id = checksum(catalog_text.as_bytes());
    let mut lines = unseal(&catalog_text)?.lines();
    ensure(
        lines.next() == Some(format!("CATALOG\t{}", plan.binding(model)).as_str()),
        "catalog context",
    )?;
    let mut tokens = BTreeMap::new();
    for line in lines {
        let v: Vec<_> = line.split('\t').collect();
        ensure(v.len() == 4 && v[0] == "TOKEN", "catalog token shape")?;
        let index: usize = v[1].parse()?;
        let token: usize = v[3].parse()?;
        let op = plan.operations.get(index).ok_or("catalog index")?;
        ensure(
            op.paid() && v[2] == op.opid && token < if op.action == "READ" { 5 } else { 4 },
            "catalog operation",
        )?;
        ensure(
            tokens.insert(index, token).is_none(),
            "duplicate catalog token",
        )?;
    }
    ensure(
        tokens.len() == plan.operations.iter().filter(|op| op.paid()).count(),
        "catalog coverage",
    )?;
    let mut receipts = Vec::new();
    if path.exists() {
        let text = read(path)?;
        let mut lines = unseal(&text)?.lines();
        let h: Vec<_> = lines.next().ok_or("provider header")?.split('\t').collect();
        ensure(
            h.len() == 7
                && h[0] == "PROVIDER"
                && h[1..4].join("\t") == plan.binding(model)
                && u64::from_str_radix(h[4], 16)? == catalog_id,
            "provider context",
        )?;
        receipts = ledger(lines.map(String::from), model, plan)?;
        ensure(
            h[5].parse::<usize>()? == receipts.len()
                && h[6].parse::<u64>()? == fees(&receipts, plan)?,
            "provider accounting",
        )?;
        for r in &receipts {
            ensure(
                tokens.get(&r.index) == Some(&r.token),
                "provider cached token disagreement",
            )?;
        }
    }
    persist_provider(path, model, plan, catalog_id, &receipts)?;
    let listener = TcpListener::bind(("127.0.0.1", 0))?;
    atomic(endpoint, &format!("{}\n", listener.local_addr()?))?;
    for connection in listener.incoming() {
        let mut stream = connection?;
        stream.set_read_timeout(Some(Duration::from_millis(500)))?;
        stream.set_write_timeout(Some(Duration::from_millis(500)))?;
        let request = match wire::receive(&mut stream) {
            Ok(value) => value,
            Err(error) => {
                eprintln!("rejected wire: {error}");
                continue;
            }
        };
        let result = (|| -> Result<Option<Receipt>> {
            let v: Vec<_> = request.trim_end().split('\t').collect();
            ensure(
                v.len() >= 4 && v[1..4].join("\t") == plan.binding(model),
                "request context",
            )?;
            if v[0] == "SYNC" {
                ensure(v.len() == 4, "sync shape")?;
                return Ok(None);
            }
            ensure(v.len() == 8 && v[0] == "CALL", "call shape")?;
            let index: usize = v[4].parse()?;
            let op = plan.operations.get(index).ok_or("call index")?;
            ensure(
                op.paid() && v[5] == op.opid && v[6] == op.action && v[7].parse::<u64>()? == op.fee,
                "call operation binding",
            )?;
            if let Some(receipt) = receipts.iter().find(|r| r.index == index) {
                return Ok(Some(receipt.clone()));
            }
            let expected = plan
                .operations
                .iter()
                .enumerate()
                .filter(|(_, op)| op.paid())
                .nth(receipts.len())
                .map(|(i, _)| i);
            ensure(expected == Some(index), "call paid prefix")?;
            let token = *tokens.get(&index).ok_or("missing provider token")?;
            let ordinal = receipts.len() + 1;
            Receipt::parse(
                &format!(
                    "EFFECT\t{}\t{index}\t{}\t{}\t{token}\t{}\t{ordinal}",
                    plan.binding(model),
                    op.opid,
                    op.action,
                    op.fee
                ),
                model,
                plan,
            )
            .map(Some)
        })();
        match result {
            Err(error) => {
                let _ = wire::send(&mut stream, &format!("ERR\t{error}\n"));
            }
            Ok(None) => {
                let mut response = format!(
                    "STATUS\t{}\t{}\t{}\n",
                    plan.binding(model),
                    receipts.len(),
                    fees(&receipts, plan)?
                );
                for r in &receipts {
                    response.push_str(&format!("{}\n", r.text));
                }
                let _ = wire::send(&mut stream, &response);
            }
            Ok(Some(receipt)) => {
                if receipt.ordinal > receipts.len() {
                    let mut candidate = receipts.clone();
                    candidate.push(receipt.clone());
                    persist_provider(path, model, plan, catalog_id, &candidate)?;
                    receipts = candidate;
                    stop(
                        "provider_effect_committed",
                        receipt.index,
                        requested,
                        marker,
                    )?;
                }
                let delivered = wire::send(&mut stream, &format!("{}\n", receipt.text)).is_ok();
                if delivered {
                    stop("provider_reply_published", receipt.index, requested, marker)?;
                }
            }
        }
    }
    Ok(())
}

fn persist_provider(
    path: &Path,
    model: &Model,
    plan: &Plan,
    catalog: u64,
    receipts: &[Receipt],
) -> Result<()> {
    let mut text = format!(
        "PROVIDER\t{}\t{catalog:016x}\t{}\t{}\n",
        plan.binding(model),
        receipts.len(),
        fees(receipts, plan)?
    );
    for r in receipts {
        text.push_str(&format!("{}\n", r.text));
    }
    atomic(path, &seal(&text))
}
