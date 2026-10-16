//! Actual custodian release callback reached only through the fenced runner.
use super::support::Fitted;
use super::support::Roles;
use super::support::micros;
use super::support::save;
use super::*;
use codex_hepta_intelligence_eval as eval;

pub(super) struct Provider<'a> {
    pub root: &'a std::path::Path,
    pub name: &'a str,
    pub candidate: &'a Fitted,
    pub roles: &'a mut Roles,
    pub manifest_bytes: Vec<u8>,
    pub plan_digest: Digest32,
    pub observations: Vec<Value>,
    pub independent_observations: Vec<Value>,
}

impl eval::FinalHoldoutProviderV1 for Provider<'_> {
    fn manifest_digest(&mut self) -> Result<Digest32, eval::ProductProviderErrorV1> {
        Ok(Digest32::of_bytes(&self.manifest_bytes))
    }

    fn release_after_consumption(
        &mut self,
        receipt: &eval::FinalHoldoutJournalReceiptV1,
    ) -> Result<eval::TemporalComparisonInputsV1, eval::ProductProviderErrorV1> {
        let material_digest = Digest32::of_bytes(&self.manifest_bytes);
        if !self.observations.is_empty()
            || receipt.disposition != eval::HoldoutUseDispositionV1::Recorded
            || receipt.use_receipt.plan_digest != self.plan_digest
            || receipt.use_receipt.holdout_digest != material_digest
            || receipt.authority.grants_any()
        {
            return Err(eval::ProductProviderErrorV1::Rejected);
        }
        let anchor = json!({"binding":hash("three-generation-holdouts").to_string(),
            "sequence":receipt.sequence, "head":receipt.head_digest.to_string(),
            "plan_digest":self.plan_digest.to_string(), "use_digest":receipt.use_receipt.use_digest.to_string(),
            "holdout_digest":material_digest.to_string(), "recorded_unix_micros":micros()});
        let signature = self.roles.processes[2].sign(&serde_json::to_vec(&anchor).unwrap());
        let reservation = json!({"anchor":anchor,"signature":support::hex(&signature)});
        save(
            &self.root.join(format!("{}-holdout-anchor.json", self.name)),
            &reservation,
        );
        for i in 1..=2 {
            let role_index = if i == 1 { 1 } else { 6 };
            let observed = self.roles.processes[role_index].call(json!({"command":"future",
                "name":format!("{}-window-{i}", self.name),
                "material_manifest_hex":support::hex(&self.manifest_bytes),"reservation":reservation}));
            let independent = self.roles.processes[2]
                .call(json!({"command":"observe_future","observation":observed}));
            save(
                &self
                    .root
                    .join(format!("{}-window-{i}-observer.json", self.name)),
                &independent,
            );
            save(
                &self.root.join(format!("{}-window-{i}.json", self.name)),
                &observed,
            );
            self.observations.push(observed);
            self.independent_observations.push(independent);
        }
        let inputs = temporal::inputs(self.candidate, self.name, &self.observations);
        save(
            &self.root.join("product-released-inputs.json"),
            &serde_json::to_value(
                crate::cognitive_process_product_wire::TemporalComparisonInputsV1Raw::from(
                    inputs.clone(),
                ),
            )
            .unwrap(),
        );
        Ok(inputs)
    }
}
