use std::path::Path;
use std::time::Duration;

use crate::FrozenOracle;
use crate::ImportCheckpoint;
use crate::ProductReceiptSet;
use crate::QualificationError;
use crate::QualificationManifest;
use crate::QualificationReport;
use crate::QualificationTrial;
use crate::QualificationTrialOutcome;
use crate::TerminalSeal;
use crate::transport::TransportEvidence;

pub struct QualificationClosure;

impl QualificationClosure {
    pub async fn run(
        product_path: impl AsRef<Path>,
        runtime_root: impl AsRef<Path>,
        timeout: Duration,
    ) -> Result<QualificationClosureOutcome, QualificationError> {
        let oracle = FrozenOracle::load_embedded()?;
        let trial = QualificationTrial::run(product_path, runtime_root, timeout).await?;
        let transport = TransportEvidence::capture(&trial)?;
        let product_receipts = ProductReceiptSet::import(&trial, &oracle).await?;
        let manifest = QualificationManifest::write(trial.completed(), &oracle)?;
        let checkpoint = ImportCheckpoint::create(trial.completed(), &product_receipts)?;
        let seal = TerminalSeal::create(checkpoint)?;
        let samples = product_receipts.semantic_reports(&oracle)?;
        transport.verify()?;
        let report = QualificationReport::write(&manifest, &seal, &oracle, samples)?;
        Ok(QualificationClosureOutcome {
            product_receipts,
            report,
            seal,
            trial,
        })
    }
}

pub struct QualificationClosureOutcome {
    product_receipts: ProductReceiptSet,
    report: QualificationReport,
    seal: TerminalSeal,
    trial: QualificationTrialOutcome,
}

impl QualificationClosureOutcome {
    pub fn product_receipts(&self) -> &ProductReceiptSet {
        &self.product_receipts
    }

    pub fn report(&self) -> &QualificationReport {
        &self.report
    }

    pub fn seal(&self) -> &TerminalSeal {
        &self.seal
    }

    pub fn trial(&self) -> &QualificationTrialOutcome {
        &self.trial
    }
}
