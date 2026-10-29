//! Trained spiking inference and explicit stopping through the native port.
use crate::credit::{AccountState, CreditMode, Settings};
use crate::decision::{Action, Boundary, ReadoutKind};
use crate::neural::{Neural, NeuralState};
use crate::{Q, Result, measure};
use codex_hepta_infer_core::{
    NeuronFeatureObservationV1, NeuronFeatureReceiptV1, NeuronFeatureRequestV1,
    NeuronFeatureTerminalStatusV1, NeuronModelRuntimeTupleV1, build_neuron_feature_receipt_v1,
};
use codex_hepta_neuron::{NeuronInferenceControlPort, NeuronModelError, NeuronRuntimeConfigV1};
use serde::{Deserialize, Serialize};
use std::time::Instant;

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Context {
    pub reliability_ppm: u32,
    pub cost_ppm: u32,
    pub deadline: usize,
}
impl Context {
    pub fn validate(&self) -> Result<()> {
        if self.reliability_ppm <= 500_000
            || self.reliability_ppm > 950_000
            || self.cost_ppm > 200_000
            || self.deadline == 0
            || self.deadline > 16
        {
            return Err("Context outside registered numeric domain".into());
        }
        Ok(())
    }
    pub fn reliability(&self) -> f64 {
        f64::from(self.reliability_ppm) / 1_000_000.0
    }
    pub fn cost(&self) -> f64 {
        f64::from(self.cost_ppm) / 1_000_000.0
    }
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Policy {
    pub readout: ReadoutKind,
    pub credit: CreditMode,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Model {
    pub schema: String,
    pub neural: Neural,
    pub credit: Settings,
    pub grid_points: usize,
}
impl Model {
    pub fn validate(&self) -> Result<()> {
        self.neural.validate()?;
        self.credit.validate()?;
        if self.schema != "hepta.adaptive-neuron.readout.v2"
            || self.grid_points < 101
            || self.grid_points > 2001
            || self.grid_points % 2 == 0
        {
            return Err("Unsupported trained readout profile".into());
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct State {
    pub neural: NeuralState,
    pub balance: f64,
    pub work: f64,
    pub spikes: usize,
    pub cell_updates: usize,
}
impl State {
    pub fn initial(account: &AccountState) -> Self {
        Self {
            neural: NeuralState::zero(),
            balance: account.balance,
            work: 0.0,
            spikes: 0,
            cell_updates: 0,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Readout {
    pub action: Action,
    pub logit: f64,
    pub immediate: f64,
    pub continuation: f64,
    pub used_price: f64,
    pub effective_cost: f64,
    pub spikes: usize,
    pub actual_snn_cell_updates: usize,
    pub input_multiply_accumulates: usize,
    pub readout_multiply_accumulates: usize,
    pub actual_work: f64,
    pub budget_forced_abstention: bool,
    pub bellman_query_terms: usize,
    pub state_after: State,
}

pub fn features(context: &Context, value: i32, elapsed: usize, price: f64) -> Result<Vec<i64>> {
    context.validate()?;
    if ![-1, 1].contains(&value)
        || elapsed == 0
        || elapsed > context.deadline
        || !price.is_finite()
        || !(0.0..=1.0).contains(&price)
    {
        return Err("Invalid causal evidence observation".into());
    }
    Ok(vec![
        i64::from(value),
        i64::from(context.reliability_ppm),
        i64::from(context.cost_ppm),
        context.deadline as i64,
        elapsed as i64,
        (price * Q as f64).round() as i64,
    ])
}

pub fn step(
    model: &Model,
    context: &Context,
    policy: &Policy,
    boundary: &Boundary,
    state: &mut State,
    value: i32,
    elapsed: usize,
    price: f64,
) -> Result<Readout> {
    if elapsed != state.neural.elapsed + 1 || state.balance + 1e-12 < model.credit.quote {
        return Err("Out-of-order or unreserved resource observation".into());
    }
    let r = context.reliability();
    let evidence = f64::from(value) * (r / (1.0 - r)).ln();
    let input = [
        f64::from(value),
        evidence,
        (r - 0.65) * 4.0,
        context.cost() / 0.04,
        context.deadline as f64 / 16.0,
        elapsed as f64 / context.deadline as f64,
    ];
    state.neural.raw_logit += evidence;
    let (logit, spikes, cells) = if policy.readout == ReadoutKind::Snn {
        let (l, s) = model.neural.step(&mut state.neural, &input)?;
        (l, s, 8)
    } else {
        (state.neural.raw_logit, 0, 0)
    };
    state.neural.elapsed = elapsed;
    let work = 1.0 + spikes as f64 / 8.0;
    state.balance -= work;
    state.work += work;
    state.spikes += spikes;
    state.cell_updates += cells;
    if state.balance < -1e-12 {
        return Err("Resource credit overdraw".into());
    }
    let remaining = context.deadline - elapsed;
    let (mut action, immediate, continuation) =
        boundary.action(logit, remaining, policy.readout)?;
    let budget_forced_abstention =
        action == Action::Continue && state.balance + 1e-12 < model.credit.quote;
    if budget_forced_abstention {
        action = Action::Abstain;
    }
    Ok(Readout {
        action,
        logit,
        immediate,
        continuation,
        used_price: price,
        effective_cost: context.cost() + price * model.credit.quote,
        spikes,
        actual_snn_cell_updates: cells,
        input_multiply_accumulates: cells * 6,
        readout_multiply_accumulates: cells,
        actual_work: work,
        budget_forced_abstention,
        bellman_query_terms: if remaining == 0 { 0 } else { 2 },
        state_after: state.clone(),
    })
}

pub fn drive(readout: &Readout) -> Vec<i64> {
    let z = (readout.logit.clamp(-7.0, 7.0) * Q as f64).round() as i64;
    let mut drive = vec![0; 10];
    drive[0] = z.max(0);
    drive[1] = (-z).max(0);
    drive[2] = Q / 4;
    drive[3] = readout.spikes as i64 * Q / 8;
    drive
}

pub struct Port {
    pub config: NeuronRuntimeConfigV1,
    pub model: Model,
    pub context: Context,
    pub policy: Policy,
    pub state: State,
    pub price: f64,
    pub boundary: Boundary,
    pub last: Option<Readout>,
}
impl NeuronInferenceControlPort for Port {
    fn execute_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> std::result::Result<NeuronFeatureReceiptV1, NeuronModelError> {
        let started = Instant::now();
        let baseline = measure::start_window();
        let c = &self.config;
        let x = &request.feature_vector_q24;
        if request.generation != c.generation
            || request.model_id != c.model_id
            || request.encoder_digest != c.encoder_digest
            || request.head_digest != c.head_digest
            || request.weights_digest != c.weights_digest
            || request.expected_output_width != 10
            || x.len() != 6
        {
            return Err(NeuronModelError::Rejected);
        }
        let expected = features(&self.context, x[0] as i32, x[4] as usize, self.price)
            .map_err(|_| NeuronModelError::Rejected)?;
        if *x != expected {
            return Err(NeuronModelError::Rejected);
        }
        let readout = step(
            &self.model,
            &self.context,
            &self.policy,
            &self.boundary,
            &mut self.state,
            x[0] as i32,
            x[4] as usize,
            self.price,
        )
        .map_err(|_| NeuronModelError::Rejected)?;
        let encoded = drive(&readout);
        self.last = Some(readout);
        build_neuron_feature_receipt_v1(
            request,
            NeuronModelRuntimeTupleV1 {
                model_id: c.model_id.clone(),
                model_manifest_digest: c.model_manifest_digest,
                weights_digest: c.weights_digest,
                tokenizer_digest: c.tokenizer_digest,
                preprocessor_digest: c.preprocessor_digest,
                quantization_digest: c.quantization_digest,
                runtime_digest: c.runtime_digest,
                device_digest: c.device_digest,
            },
            NeuronFeatureObservationV1 {
                encoder_digest: c.encoder_digest,
                head_digest: c.head_digest,
                drive_q24: encoded.clone(),
                prediction_q24: encoded,
                observed_memory_bytes: measure::live_bytes() as u64,
                transient_allocation_bytes: measure::peak_delta(baseline) as u64,
                queue_age_micros: 0,
                latency_micros: started.elapsed().as_micros() as u64,
                status: NeuronFeatureTerminalStatusV1::Succeeded,
            },
        )
        .map_err(|_| NeuronModelError::Rejected)
    }
}
