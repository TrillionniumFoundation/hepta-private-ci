//! Negotiated bounded reads reuse the existing client, owner and generation fence.
use super::*;
use codex_hepta_automation::AutomationTaskCursorV1;
use codex_hepta_automation::AutomationTaskPageV1;

impl AgentdClient {
    /// Read at most `limit` live tasks in creation/identity order. This is not a
    /// frozen snapshot across concurrent insertions. A single overall deadline
    /// and strict cursor progress prevent pagination from creating unbounded work.
    pub async fn automation_list(&self, limit: u16) -> Result<Vec<AutomationTask>, AgentdError> {
        if !(1..=256).contains(&limit) {
            return Err(AgentdError::Invalid(
                "automation list limit must be between 1 and 256".into(),
            ));
        }
        timeout(self.timeout, async {
            let supported = self
                .capabilities()
                .await?
                .capabilities
                .iter()
                .any(|capability| {
                    capability.id == crate::AGENTD_CAPABILITY_AUTOMATION_LIST_PAGE_V1
                        && capability.major == 1
                });
            if !supported {
                // Same-schema older servers retain their original small-list path.
                return match self
                    .send(AgentdRequest::automation_list(
                        self.request_id(),
                        self.spawn_generation,
                        limit,
                    ))
                    .await?
                    .payload
                {
                    AgentdPayload::AutomationTasks { tasks } => Ok(tasks),
                    payload => unexpected(payload),
                };
            }
            let mut tasks = Vec::new();
            let mut cursor = None;
            while tasks.len() < usize::from(limit) {
                let remaining = usize::from(limit) - tasks.len();
                let page = self
                    .automation_list_page_v1(
                        u16::try_from(remaining)
                            .map_err(|_| AgentdError::Invalid("list limit overflow".into()))?,
                        cursor,
                    )
                    .await?;
                cursor = page.next_cursor;
                tasks.extend(page.tasks);
                if cursor.is_none() {
                    break;
                }
            }
            Ok(tasks)
        })
        .await
        .map_err(|_| {
            AgentdError::Protocol("automation list exceeded its overall deadline".into())
        })?
    }

    /// Fetch one page after negotiating `automation.list_page_v1`. The existing
    /// request envelope fences every page to the expected Agent and process.
    pub async fn automation_list_page_v1(
        &self,
        limit: u16,
        after: Option<AutomationTaskCursorV1>,
    ) -> Result<AutomationTaskPageV1, AgentdError> {
        if !(1..=256).contains(&limit) {
            return Err(AgentdError::Invalid(
                "automation list limit must be between 1 and 256".into(),
            ));
        }
        match self
            .send(AgentdRequest::automation_list_page_v1(
                self.request_id(),
                self.spawn_generation,
                limit,
                after,
            ))
            .await?
            .payload
        {
            AgentdPayload::AutomationTasksPageV1(page) => {
                validate_page(&self.expected_agent_id, after, usize::from(limit), &page)?;
                Ok(page)
            }
            payload => unexpected(payload),
        }
    }
}

fn validate_page(
    owner: &AgentId,
    after: Option<AutomationTaskCursorV1>,
    remaining: usize,
    page: &AutomationTaskPageV1,
) -> Result<(), AgentdError> {
    let invalid =
        || AgentdError::Protocol("automation page violates owner, limit or cursor progress".into());
    if page.tasks.len() > remaining || (page.tasks.is_empty() && page.next_cursor.is_some()) {
        return Err(invalid());
    }
    let mut previous = after;
    for task in &page.tasks {
        let current = AutomationTaskCursorV1::from_task(task);
        if &task.owner_agent_id != owner || previous.is_some_and(|value| current <= value) {
            return Err(invalid());
        }
        previous = Some(current);
    }
    if let Some(next) = page.next_cursor
        && Some(next) != previous
    {
        return Err(invalid());
    }
    Ok(())
}

#[cfg(test)]
#[path = "client_automation_listing_tests.rs"]
mod tests;
