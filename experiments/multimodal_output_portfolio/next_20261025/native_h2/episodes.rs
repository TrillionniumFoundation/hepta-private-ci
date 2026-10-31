//! Bind a second decision to the durable first actual observation and public state.
use crate::stream_io::Result;
use codex_hepta_types::Digest32;
use serde_json::Value;
use serde_json::json;
use std::collections::HashSet;

#[derive(Default)]
pub struct Episodes {
    seen: HashSet<String>,
    pending: Option<(String, u64, String)>,
    continuation: Option<(String, String, String)>,
}

impl Episodes {
    pub fn status(&self) -> Value {
        json!({"seen_episodes": self.seen.len(), "pending": self.pending, "continuation": self.continuation})
    }

    pub fn check_decision(
        &self,
        episode: &str,
        prefix: &str,
        parent: Option<&str>,
        horizon: u64,
    ) -> Result<()> {
        if self.pending.is_some() {
            return Err("An actual observation is still pending".into());
        }
        if horizon == 2 {
            if self.seen.contains(episode) || self.continuation.is_some() || parent.is_some() {
                return Err(
                    "Root cannot replace a committed episode or unfinished continuation".into(),
                );
            }
        } else if horizon != 1
            || self
                .continuation
                .as_ref()
                .is_none_or(|(e, p, d)| e != episode || p != prefix || Some(d.as_str()) != parent)
        {
            return Err("H1 must bind its H2 observed outcome and resulting public state".into());
        }
        Ok(())
    }

    pub fn check_outcome(&self, receipt: &Value) -> Result<()> {
        let (episode, horizon, action) = self.pending.as_ref().ok_or("No pending episode")?;
        let remaining = if action == "stop" {
            *horizon
        } else {
            horizon - 1
        };
        if receipt["episode_id"] != *episode
            || receipt["after_remaining"].as_u64() != Some(remaining)
            || receipt["done"].as_bool() != Some(action == "stop" || remaining == 0)
            || receipt["after_public_digest"]
                .as_str()
                .ok_or("Missing resulting public state")?
                .parse::<Digest32>()?
                .is_zero()
        {
            return Err("Actual result does not match the committed H2 transition".into());
        }
        Ok(())
    }

    pub fn apply(&mut self, event: &Value, digest: Digest32) -> Result<()> {
        match event["kind"].as_str().ok_or("Missing episode event")? {
            "bootstrap" => {}
            "decision" => {
                let episode = event["episode_id"]
                    .as_str()
                    .ok_or("Missing episode identity")?;
                let horizon = event["remaining"].as_u64().ok_or("Missing horizon")?;
                let prefix = event["prefix_digest"].as_str().ok_or("Missing prefix")?;
                self.check_decision(
                    episode,
                    prefix,
                    event["parent_outcome_digest"].as_str(),
                    horizon,
                )?;
                self.seen.insert(episode.to_string());
                self.continuation = None;
                self.pending = event["selected_action"]
                    .as_str()
                    .map(|a| (episode.to_string(), horizon, a.to_string()));
            }
            "outcome" => {
                self.check_outcome(event)?;
                let (episode, horizon, action) =
                    self.pending.take().ok_or("Missing pending episode")?;
                if horizon == 2 && action != "stop" {
                    self.continuation = Some((
                        episode,
                        event["after_public_digest"]
                            .as_str()
                            .ok_or("Missing observed prefix")?
                            .to_string(),
                        digest.to_string(),
                    ));
                }
            }
            "cancel" => {
                self.pending = None;
                self.continuation = None;
            }
            _ => return Err("Unknown episode event".into()),
        }
        Ok(())
    }
}
