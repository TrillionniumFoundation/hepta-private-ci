//! Versioned complete content state; independent of production neuron V1.
use crate::codec::{Packet, Result};
use crate::model::Model;
#[derive(Clone, Debug, PartialEq)]
pub struct State {
    pub context: Vec<f64>,
    pub shared: Vec<f64>,
    pub slots: Vec<f64>,
    pub core: Vec<[Vec<f64>; 4]>,
    pub feedback: Vec<f64>,
    pub steps: usize,
    pub stopped: bool,
    pub verified: bool,
    pub content_revision: usize,
    pub verified_revision: i64,
}
impl State {
    pub fn packet(&self) -> Packet {
        let mut p = Packet::default();
        p.meta
            .insert("kind".into(), "joint-generator-state-v3".into());
        for (k, v) in [
            ("steps", self.steps.to_string()),
            ("stopped", self.stopped.to_string()),
            ("verified", self.verified.to_string()),
            ("content_revision", self.content_revision.to_string()),
            ("verified_revision", self.verified_revision.to_string()),
        ] {
            p.meta.insert(k.into(), v);
        }
        for (k, v) in [
            ("context", &self.context),
            ("shared", &self.shared),
            ("slots", &self.slots),
            ("feedback", &self.feedback),
        ] {
            p.vector(k, v.clone());
        }
        for (l, state) in self.core.iter().enumerate() {
            for (i, name) in ["content", "voltage", "adaptation", "event"]
                .iter()
                .enumerate()
            {
                p.vector(&format!("core.{l}.{name}"), state[i].clone());
            }
        }
        p
    }
    pub fn read(p: &Packet, model: &Model) -> Result<Self> {
        let vector = |name: &str, n: usize| -> Result<Vec<f64>> {
            let x = p.get(name)?;
            if x.len() != n {
                return Err(format!("state shape {name}"));
            }
            Ok(x.to_vec())
        };
        let mut core = Vec::new();
        for l in 0..model.depth {
            core.push([
                vector(&format!("core.{l}.content"), model.width)?,
                vector(&format!("core.{l}.voltage"), model.width)?,
                vector(&format!("core.{l}.adaptation"), model.width)?,
                vector(&format!("core.{l}.event"), model.width)?,
            ]);
        }
        let steps = p
            .text("steps")?
            .parse::<usize>()
            .map_err(|e| e.to_string())?;
        if steps > 7 {
            return Err("state horizon".into());
        }
        let stopped = p
            .text("stopped")?
            .parse::<bool>()
            .map_err(|e| e.to_string())?;
        let verified = p
            .text("verified")?
            .parse::<bool>()
            .map_err(|e| e.to_string())?;
        let content_revision = p
            .text("content_revision")?
            .parse::<usize>()
            .map_err(|e| e.to_string())?;
        let verified_revision = p
            .text("verified_revision")?
            .parse::<i64>()
            .map_err(|e| e.to_string())?;
        if content_revision > steps
            || verified_revision < -1
            || verified_revision > content_revision as i64
            || verified != (verified_revision == content_revision as i64)
        {
            return Err("invalid content/verification revision".into());
        }
        Ok(Self {
            context: vector("context", model.width)?,
            shared: vector("shared", model.width)?,
            slots: vector("slots", 4 * model.width)?,
            feedback: vector("feedback", 3)?,
            core,
            steps,
            stopped,
            verified,
            content_revision,
            verified_revision,
        })
    }
}
