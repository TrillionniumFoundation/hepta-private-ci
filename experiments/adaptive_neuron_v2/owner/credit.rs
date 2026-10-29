//! Research resource account with native conserved-credit validation.
//! This sidecar is not the production LedgerWriter or a signature admission path.
use crate::Result;
use crate::original_credit::{
    AuthenticatedPrincipalV1, CreditAllocationBatchV1, CreditAllocationV1, finalize_credit_batch,
};
use codex_hepta_types::{Digest32, FixedQ32, StableId};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::BTreeSet;
use std::fs::{File, OpenOptions};
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Settings {
    pub eta: f64,
    pub pmax: f64,
    pub kappa: f64,
    pub balance_cap: f64,
    pub initial_balance: f64,
    pub initial_price: f64,
    pub frozen_price: f64,
    pub quote: f64,
}

impl Settings {
    pub fn validate(&self) -> Result<()> {
        if [
            self.eta,
            self.pmax,
            self.kappa,
            self.balance_cap,
            self.initial_balance,
            self.initial_price,
            self.frozen_price,
            self.quote,
        ]
        .iter()
        .any(|x| !x.is_finite())
            || self.eta <= 0.0
            || self.pmax <= 0.0
            || self.pmax > 1.0
            || self.kappa < 0.0
            || self.kappa >= 3.0
            || self.quote != 2.0
            || self.initial_balance < self.quote
            || self.balance_cap < self.initial_balance
            || self.balance_cap > 128.0
            || !(0.0..=self.pmax).contains(&self.initial_price)
            || !(0.0..=self.pmax).contains(&self.frozen_price)
        {
            return Err("Invalid resource credit contract".into());
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum CreditMode {
    Off,
    Frozen,
    Live,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct AccountState {
    pub sequence: usize,
    pub balance: f64,
    pub price: f64,
    pub head: String,
}

impl AccountState {
    pub fn used_price(&self, mode: CreditMode, settings: &Settings) -> f64 {
        match mode {
            CreditMode::Off => 0.0,
            CreditMode::Frozen => settings.frozen_price,
            CreditMode::Live => self.price,
        }
    }
}

pub struct Account {
    pub organ: String,
    pub state: AccountState,
    pub settings: Settings,
    records: Vec<Value>,
    path: PathBuf,
    reservation: PathBuf,
}

fn native_credit(case: &str, organ: &str, reward: f64, support: &str) -> Result<Value> {
    let support: Digest32 = support.parse()?;
    if support.is_zero() || ![-1.0, 0.05, 1.0].contains(&reward) {
        return Err("Invalid observed terminal reward".into());
    }
    let value = FixedQ32::from_raw((reward * ((1_u64 << 32) as f64)).round() as i64);
    let receipt = finalize_credit_batch(
        CreditAllocationBatchV1 {
            batch_id: StableId::new(format!("{case}.credit"))?,
            episode_id: StableId::new(case)?,
            outcome_id: StableId::new(format!("{case}.outcome"))?,
            allocator: AuthenticatedPrincipalV1 {
                principal_id: StableId::new("local-research-resource-allocator")?,
                credential_chain_digest: Digest32::of_bytes(b"local-research-explicit-permit"),
                signing_key_digest: Digest32::of_bytes(
                    b"research-identity-metadata-not-a-signature",
                ),
                scope_digest: Digest32::of_bytes(b"adaptive-neuron.local-synthetic-credit.v2"),
                authority_epoch: 1,
                authenticated_at: 0,
                expires_at: 1,
            },
            terminal_outcome: value,
            allocations: vec![CreditAllocationV1 {
                target_id: StableId::new(organ)?,
                credit: value,
            }],
            conservation_residual: FixedQ32::ZERO,
            support_digest: support,
            finalized: true,
        },
        1,
    )?;
    if receipt.authority.grants_any() {
        return Err("Unexpected credit authority".into());
    }
    Ok(
        json!({"native_function":"finalize_credit_batch", "batch_digest":receipt.batch_digest.to_string(),
        "allocation_count":receipt.allocation_count,"terminal_outcome_q32":value.raw(),
        "conservation_residual_q32":receipt.conservation_residual.raw(),"authority":"DENY_ALL",
        "signature_admission":false,"production_ledger_append":false}),
    )
}

fn write_record(file: &mut File, payload: &Value) -> Result<Value> {
    let payload_json = serde_json::to_string(payload)?;
    let digest = Digest32::of_bytes(payload_json.as_bytes()).to_string();
    let envelope = json!({"payload_json":payload_json,"record_digest":digest});
    writeln!(file, "{}", serde_json::to_string(&envelope)?)?;
    file.sync_all()?;
    Ok(envelope)
}

impl Account {
    pub fn load(root: &Path, organ: &str, settings: Settings) -> Result<Self> {
        StableId::new(organ)?;
        settings.validate()?;
        if !organ
            .chars()
            .all(|x| x.is_ascii_alphanumeric() || matches!(x, '.' | '-' | '_'))
        {
            return Err("Invalid organ identifier".into());
        }
        let path = root.join(format!("organ.{organ}.jsonl"));
        let reservation = root.join(format!("organ.{organ}.active.json"));
        let mut state = AccountState {
            sequence: 0,
            balance: settings.initial_balance,
            price: settings.initial_price,
            head: Digest32::ZERO.to_string(),
        };
        if !path.exists() {
            let mut file = OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(&path)?;
            let header = json!({"schema":"hepta.adaptive-neuron.resource-account.v2","organ":organ,"settings":settings});
            let envelope = write_record(&mut file, &header)?;
            state.head = envelope["record_digest"]
                .as_str()
                .ok_or("Header digest")?
                .to_owned();
            File::open(root)?.sync_all()?;
        }
        let bytes = std::fs::read(&path)?;
        if bytes.is_empty() || bytes.last() != Some(&b'\n') {
            return Err("Torn resource-account ledger".into());
        }
        let mut records = Vec::new();
        let mut cases = BTreeSet::new();
        for (index, line) in BufReader::new(bytes.as_slice()).lines().enumerate() {
            let envelope: Value = serde_json::from_str(&line?)?;
            let raw = envelope["payload_json"].as_str().ok_or("Account payload")?;
            if envelope["record_digest"] != Digest32::of_bytes(raw.as_bytes()).to_string() {
                return Err("Resource-account digest mismatch".into());
            }
            let payload: Value = serde_json::from_str(raw)?;
            if index == 0 {
                if payload
                    != json!({"schema":"hepta.adaptive-neuron.resource-account.v2","organ":organ,"settings":settings})
                {
                    return Err("Resource-account identity mismatch".into());
                }
                state.head = envelope["record_digest"]
                    .as_str()
                    .ok_or("Header digest")?
                    .to_owned();
            } else {
                if payload["before"] != serde_json::to_value(&state)? {
                    return Err("Resource-account predecessor mismatch".into());
                }
                let case = payload["case"].as_str().ok_or("Case identity")?;
                if payload["organ"] != organ || !cases.insert(case.to_owned()) {
                    return Err("Duplicate case or changed organ in resource account".into());
                }
                let reward = payload["reward"].as_f64().ok_or("Reward")?;
                let work = payload["actual_work"].as_f64().ok_or("Work")?;
                let budget = payload["budget"].as_f64().ok_or("Budget")?;
                let expected = Self::next(&settings, &state, work, budget, reward)?;
                let support = payload["support_digest"].as_str().ok_or("Support")?;
                if payload["after_balance"] != expected.balance
                    || payload["after_price"] != expected.price
                    || payload["balance_overflow"]
                        != (state.balance - work + budget + settings.kappa * reward
                            - settings.balance_cap)
                            .max(0.0)
                    || payload["native_credit"] != native_credit(case, organ, reward, support)?
                {
                    return Err("Resource-account settlement mismatch".into());
                }
                state = expected;
                state.head = envelope["record_digest"]
                    .as_str()
                    .ok_or("Record digest")?
                    .to_owned();
                records.push(envelope);
            }
        }
        Ok(Self {
            organ: organ.to_owned(),
            state,
            settings,
            records,
            path,
            reservation,
        })
    }

    fn next(
        settings: &Settings,
        before: &AccountState,
        work: f64,
        budget: f64,
        reward: f64,
    ) -> Result<AccountState> {
        if !work.is_finite()
            || work < 0.0
            || work > before.balance + 1e-12
            || ![3.0, 7.0].contains(&budget)
            || ![-1.0, 0.05, 1.0].contains(&reward)
        {
            return Err("Invalid or overdrawn resource settlement".into());
        }
        Ok(AccountState {
            sequence: before.sequence + 1,
            balance: (before.balance - work + budget + settings.kappa * reward)
                .min(settings.balance_cap),
            price: (before.price + settings.eta * (work - budget - settings.kappa * reward))
                .clamp(0.0, settings.pmax),
            head: before.head.clone(),
        })
    }

    fn release_reservation(&self, case: &str) -> Result<()> {
        if self.reservation.exists() {
            let active: Value = serde_json::from_slice(&std::fs::read(&self.reservation)?)?;
            if active == json!({"case":case}) {
                std::fs::remove_file(&self.reservation)?;
                File::open(self.path.parent().ok_or("Account directory")?)?.sync_all()?;
            }
        }
        Ok(())
    }

    pub fn reserve(&self, case: &str, restore: bool) -> Result<()> {
        let already = self.settlement(case)?.is_some();
        if restore && already {
            self.release_reservation(case)?;
            return Ok(());
        }
        if self.reservation.exists() {
            if !restore
                || serde_json::from_slice::<Value>(&std::fs::read(&self.reservation)?)?
                    != json!({"case":case})
            {
                return Err("Organ already has an unsettled task".into());
            }
        } else {
            if restore {
                return Err("Missing active resource reservation".into());
            }
            let mut f = OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(&self.reservation)?;
            f.write_all(&serde_json::to_vec(&json!({"case":case}))?)?;
            f.sync_all()?;
            File::open(self.path.parent().ok_or("Account directory")?)?.sync_all()?;
        }
        Ok(())
    }

    pub fn validated_records(&self) -> usize {
        self.records.len()
    }
    pub fn verify_initial(&self, case: &str, initial: &AccountState) -> Result<()> {
        if let Some(record) = self.settlement(case)? {
            let payload: Value =
                serde_json::from_str(record["payload_json"].as_str().ok_or("Account payload")?)?;
            if payload["before"] != serde_json::to_value(initial)? {
                return Err("Historical account input mismatch".into());
            }
        } else if initial != &self.state {
            return Err("Active account input mismatch".into());
        }
        Ok(())
    }

    pub fn settlement(&self, case: &str) -> Result<Option<Value>> {
        for value in &self.records {
            let payload: Value =
                serde_json::from_str(value["payload_json"].as_str().ok_or("Account payload")?)?;
            if payload["case"] == case {
                return Ok(Some(value.clone()));
            }
        }
        Ok(None)
    }

    pub fn settle(
        &mut self,
        case: &str,
        before: &AccountState,
        work: f64,
        budget: f64,
        reward: f64,
        support: &str,
        checkpoint: &str,
    ) -> Result<Value> {
        let next = Self::next(&self.settings, before, work, budget, reward)?;
        let payload = json!({"case":case,"organ":self.organ,"before":before,"actual_work":work,"budget":budget,"reward":reward,
            "support_digest":support,"owner_checkpoint":checkpoint,"after_balance":next.balance,"after_price":next.price,"balance_overflow":(before.balance-work+budget+self.settings.kappa*reward-self.settings.balance_cap).max(0.0),
            "native_credit":native_credit(case,&self.organ,reward,support)?});
        if let Some(old) = self.settlement(case)? {
            let stored: Value =
                serde_json::from_str(old["payload_json"].as_str().ok_or("Account payload")?)?;
            if stored != payload {
                return Err("Conflicting settlement retry".into());
            }
            self.release_reservation(case)?;
            return Ok(
                json!({"record":old,"duplicate_settlement_ignored":true,"native_credit_finalizations":1,"new_credit_records":0}),
            );
        }
        if &self.state != before {
            return Err("Resource-account advanced before settlement".into());
        }
        let mut f = OpenOptions::new().append(true).open(&self.path)?;
        let envelope = write_record(&mut f, &payload)?;
        self.state = next;
        self.state.head = envelope["record_digest"]
            .as_str()
            .ok_or("Record digest")?
            .to_owned();
        self.records.push(envelope.clone());
        self.release_reservation(case)?;
        Ok(
            json!({"record":envelope,"duplicate_settlement_ignored":false,"native_credit_finalizations":1,"new_credit_records":1}),
        )
    }
}
