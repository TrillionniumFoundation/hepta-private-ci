//! Typed joint observation/credit records; hashes detect damage, not a hostile writer.
use crate::contract::Action;
use crate::contract::LIMIT;
use crate::contract::Phase;
use crate::contract::Request;
use crate::contract::ZERO;
use crate::contract::digest;
use crate::contract::hash;
use crate::native;
use crate::store::Store;
use serde::Deserialize;
use serde::Serialize;

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub enum Terminal {
    Cancelled,
    Deadline,
    Stopped,
    BudgetExhausted,
    PriceLimited,
    NativeAbstained,
    ReadFailed,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(tag = "kind", deny_unknown_fields)]
pub enum Observation {
    None,
    Read {
        source_digest: String,
        bytes: usize,
        answer: Option<String>,
    },
    Failed {
        error: String,
    },
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Body {
    pub request: Request,
    pub request_digest: String,
    pub data_root: String,
    pub native: native::Receipt,
    pub attempts: u64,
    pub total_spent: u64,
    pub price_before_micros: i64,
    pub price_after_micros: i64,
    pub price_before_residue: i64,
    pub price_after_residue: i64,
    pub admission_price_micros: i64,
    pub admission_price_residue: i64,
    pub terminal: Option<Terminal>,
    pub observation: Observation,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Record {
    pub digest: String,
    pub body: Body,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Dispatch {
    pub request_digest: String,
}

pub fn validate_outcome(body: &Body, prior_spent: u64) -> Result<(), String> {
    let r = &body.request;
    let guard = if r
        .checkpoint
        .cancellation
        .at_us
        .is_some_and(|t| r.checkpoint.time_us >= t)
    {
        Some(Terminal::Cancelled)
    } else if r.checkpoint.time_us >= r.config.deadline_us {
        Some(Terminal::Deadline)
    } else {
        match &r.action {
            Action::Stop => Some(Terminal::Stopped),
            Action::Wait => None,
            Action::Read { .. } => {
                if !matches!(r.checkpoint.phase, Phase::Active) {
                    return Err("settled read during refractory".into());
                }
                if prior_spent >= r.config.read_budget {
                    Some(Terminal::BudgetExhausted)
                } else if !r
                    .config
                    .credit
                    .permits(body.admission_price_micros, body.admission_price_residue)
                {
                    Some(Terminal::PriceLimited)
                } else if body.native.abstain {
                    Some(Terminal::NativeAbstained)
                } else {
                    None
                }
            }
        }
    };
    if guard.is_some() || matches!(r.action, Action::Wait) {
        if body.terminal != guard || body.attempts != 0 || body.observation != Observation::None {
            return Err("guarded outcome contradicts action/accounting".into());
        }
        return Ok(());
    }
    match (&body.terminal, &body.observation) {
        (
            None,
            Observation::Read {
                source_digest,
                bytes,
                answer,
            },
        ) if body.attempts == 1
            && *bytes <= 65_536
            && answer.as_ref().is_none_or(|v| v.len() <= *bytes) =>
        {
            if digest(source_digest)?.is_zero() {
                return Err("missing source identity".into());
            }
        }
        (Some(Terminal::ReadFailed), Observation::Failed { error })
            if body.attempts <= 1 && !error.is_empty() && error.len() <= 4096 => {}
        _ => return Err("read outcome contradicts action/accounting".into()),
    }
    Ok(())
}

pub fn history(store: &Store) -> Result<Vec<Record>, String> {
    let mut rows: Vec<Record> = Vec::new();
    let mut missing = false;
    for index in 1..=LIMIT {
        let Some(row) = store.read::<Record>(&format!("settled-{index:04}.json"))? else {
            missing = true;
            continue;
        };
        if missing {
            return Err("noncontiguous settlement history".into());
        }
        let prior = rows.last();
        row.body.request.validate(prior.map(|r| &r.body.request))?;
        let prior_digest = prior.map_or(ZERO, |r| r.digest.as_str());
        let prior_native = prior.map_or(ZERO, |r| r.body.native.after.as_str());
        let spent = prior.map_or(0, |r| r.body.total_spent);
        let price = prior.map_or(row.body.request.config.credit.initial_micros, |r| {
            r.body.price_after_micros
        });
        let residue = prior.map_or(0, |r| r.body.price_after_residue);
        let elapsed_us = row.body.request.checkpoint.time_us
            - prior.map_or(0, |r| r.body.request.checkpoint.time_us);
        let admission = row
            .body
            .request
            .config
            .credit
            .next(price, residue, 0, elapsed_us);
        if row.digest != hash(&row.body)?
            || row.body.request_digest != hash(&row.body.request)?
            || row.body.request.sequence != index
            || row.body.request.predecessor != prior_digest
            || row.body.native.before != prior_native
            || row.body.native.sequence != index
            || digest(&row.body.native.after)?.is_zero()
            || row.body.attempts > 1
            || row.body.total_spent != spent + row.body.attempts
            || row.body.total_spent > row.body.request.config.read_budget
            || row.body.price_before_micros != price
            || row.body.request.expected_price_micros != price
            || row.body.price_before_residue != residue
            || row.body.request.expected_price_residue != residue
            || (
                row.body.admission_price_micros,
                row.body.admission_price_residue,
            ) != admission
            || (row.body.price_after_micros, row.body.price_after_residue)
                != row.body.request.config.credit.next(
                    price,
                    residue,
                    row.body.attempts,
                    elapsed_us,
                )
            || prior.is_some_and(|r| {
                r.body.terminal.is_some() || r.body.data_root != row.body.data_root
            })
        {
            return Err("settlement chain/accounting mismatch".into());
        }
        validate_outcome(&row.body, spent)?;
        let prepared: Request = store
            .read(&format!("prepared-{index:04}.json"))?
            .ok_or("missing prepared request")?;
        let dispatch: Dispatch = store
            .read(&format!("dispatch-{index:04}.json"))?
            .ok_or("missing dispatch fence")?;
        if prepared != row.body.request || dispatch.request_digest != row.body.request_digest {
            return Err("settlement lacks original dispatch binding".into());
        }
        rows.push(row);
    }
    Ok(rows)
}
