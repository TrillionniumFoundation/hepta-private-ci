//! Fixed publication data retained from the actual original sealed Root offer.
//! This cannot connect CURRENT before late enrollment and owns no Root writer.

use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use super::*;
use crate::authority_host_runtime::PreparedPublicationData;

pub(crate) struct OriginalPreparedPublicationRoute {
    handoff: RootGenerationPublicationHandoffV1,
    connection: RootGenerationPublicationConnectionV1,
    data: PreparedPublicationData,
    end: Instant,
    fenced: AtomicBool,
}

struct FenceOnDrop<'a> {
    route: &'a OriginalPreparedPublicationRoute,
    armed: bool,
}

impl Drop for FenceOnDrop<'_> {
    fn drop(&mut self) {
        if self.armed {
            self.route.fenced.store(true, Ordering::Release);
        }
    }
}

impl RootGenerationPublicationHandoffV1 {
    pub(crate) fn retain_original_preparation(
        mut self,
        connection: RootGenerationPublicationConnectionV1,
        prepared: &crate::CellQ24PreparedLearningV1,
        end: Instant,
    ) -> Result<OriginalPreparedPublicationRoute, AgentdError> {
        let (bundle, data) =
            RootGenerationPublicationHandoffV1::read_original_route(&mut self, &connection, end)?;
        if PublicationVersion::from_purpose(&bundle.purpose)? != PublicationVersion::DurableV2
            || bundle.initial != prepared.initial().head_digest.to_string()
            || bundle.scope != prepared.scope().binding().to_string()
            || bundle.learning_operation != prepared.initial().request.operation_id.as_str()
        {
            return Err(refused(
                "prepared publication belongs to another original learning cut",
            ));
        }
        let route = OriginalPreparedPublicationRoute {
            handoff: self,
            connection,
            data: data.ok_or_else(|| refused("original Root publication inputs are absent"))?,
            end,
            fenced: AtomicBool::new(false),
        };
        OriginalPreparedPublicationRoute::require_current(&route)?;
        Ok(route)
    }
}

impl OriginalPreparedPublicationRoute {
    pub(crate) fn require_current(&self) -> Result<(), AgentdError> {
        if self.fenced.load(Ordering::Acquire) {
            return Err(refused("original prepared publication route is fenced"));
        }
        let result = (|| {
            publication_remaining(self.end)?;
            RootGenerationPublicationHandoffV1::require_original_root(&self.handoff)?;
            self.connection.require_original_publication_session()?;
            publication_remaining(self.end)?;
            Ok(())
        })();
        if result.is_err() {
            self.fenced.store(true, Ordering::Release);
        }
        result
    }

    pub(crate) fn with_original_data<T>(
        &self,
        action: impl FnOnce(&PreparedPublicationData) -> Result<T, AgentdError>,
    ) -> Result<T, AgentdError> {
        let mut fence = FenceOnDrop {
            route: self,
            armed: true,
        };
        Self::require_current(self)?;
        let result = action(&self.data);
        Self::require_current(self)?;
        if result.is_ok() {
            fence.armed = false;
        }
        result
    }

    pub(crate) fn into_original_connection(
        self,
    ) -> Result<
        (
            RootGenerationPublicationHandoffV1,
            RootGenerationPublicationConnectionV1,
            Instant,
        ),
        AgentdError,
    > {
        Self::require_current(&self)?;
        Ok((self.handoff, self.connection, self.end))
    }
}
