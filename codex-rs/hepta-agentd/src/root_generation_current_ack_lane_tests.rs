//! Real original Root client/lane and actual Source files. This establishes
//! the transport ordering mechanism, not a complete PublishedTask ACK flow.

use super::*;
use anyhow::Context;
use pretty_assertions::assert_eq;
use std::sync::mpsc;
use std::time::Duration;

use crate::circuit_task::AckSourceFixture;
use crate::circuit_task::AckSourceStage;

#[derive(Clone, Copy, Debug)]
pub(crate) enum AckLaneOrder {
    SourceFirst,
    CurrentFirst,
}

impl RootGenerationCurrentClient {
    pub(crate) fn component_original_ack_lane_order(
        &self,
        order: AckLaneOrder,
    ) -> anyhow::Result<()> {
        // This method receives only an already connected real production
        // client. Its original stream/protocol must succeed before contention.
        let before = self.observe()?;
        let missing = AckSourceFixture::new(AckSourceStage::Missing)?;
        let pending = AckSourceFixture::new(AckSourceStage::Pending)?;
        const BOUND: Duration = Duration::from_millis(500);
        let sequence = std::thread::scope(|scope| -> anyhow::Result<u64> {
            let (entered, observed) = mpsc::sync_channel(/*bound*/ 1);
            let (release, finish) = mpsc::sync_channel(/*bound*/ 1);
            let holder = scope.spawn(move || -> anyhow::Result<u64> {
                let held = self
                    .lane
                    .lock()
                    .map_err(|_| anyhow::anyhow!("actual original lane poisoned"))?;
                let sequence = held
                    .as_ref()
                    .ok_or_else(|| anyhow::anyhow!("actual original lane consumed"))?
                    .sequence;
                entered.send(sequence)?;
                finish
                    .recv_timeout(BOUND)
                    .context("bounded original lane release")?;
                drop(held);
                Ok(sequence)
            });
            let sequence = observed
                .recv_timeout(BOUND)
                .context("actual other thread holds original lane")?;
            let checked = (|| -> anyhow::Result<()> {
                match order {
                    AckLaneOrder::SourceFirst => {
                        for source in [&missing, &pending] {
                            assert_eq!(
                                source.read_publication().err(),
                                Some(crate::CircuitTaskErrorV1::ReconciliationRequired)
                            );
                            assert!(!self.fenced.load(Ordering::Acquire));
                            source.require_unchanged()?;
                        }
                    }
                    AckLaneOrder::CurrentFirst => {
                        self.connection.require_original_publication_session()?;
                        assert!(!self.fenced.load(Ordering::Acquire));
                        require_uncertain(self.observe().unwrap_err());
                        self.connection.require_original_publication_session()?;
                        assert!(self.fenced.load(Ordering::Acquire));
                    }
                }
                Ok(())
            })();
            let released = release.send(());
            let joined = holder
                .join()
                .map_err(|_| anyhow::anyhow!("original lane holder panicked"))?;
            checked?;
            released?;
            assert_eq!(joined?, sequence);
            Ok(sequence)
        })?;
        assert_eq!(
            self.lane
                .lock()
                .map_err(|_| anyhow::anyhow!("actual original lane poisoned"))?
                .as_ref()
                .map(|lane| lane.sequence),
            Some(sequence),
            "the bounded probe did not send an additional Root frame"
        );
        match order {
            AckLaneOrder::SourceFirst => {
                assert_eq!(self.observe()?, before);
                assert!(!self.fenced.load(Ordering::Acquire));
            }
            AckLaneOrder::CurrentFirst => {
                self.connection.require_original_publication_session()?;
                assert!(self.fenced.load(Ordering::Acquire));
                require_uncertain(self.observe().unwrap_err());
                self.connection.require_original_publication_session()?;
                assert!(self.fenced.load(Ordering::Acquire));
            }
        }
        missing.require_unchanged()?;
        pending.require_unchanged()?;
        println!(
            "\nROOT_ACK_LANE_MECHANISM order={order:?} actual_root_stream=true actual_source_files=true whole_product_ack=0 ordinary_c=0"
        );
        Ok(())
    }
}

fn require_uncertain(error: AgentdError) {
    assert!(
        matches!(error, AgentdError::Io(ref error)
            if error.get_ref().is_some_and(<dyn std::error::Error + Send + Sync + 'static>::is::<RootGenerationPublicationUncertain>)),
        "actual original Root lane refusal: {error}"
    );
}
