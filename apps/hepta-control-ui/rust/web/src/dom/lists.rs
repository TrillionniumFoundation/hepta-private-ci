use super::*;
use hepta_control_core::confirmation::retained_target;

pub(super) struct ModuleRow {
    node: Element,
    cells: Vec<Element>,
}
pub(super) struct OperationRow {
    node: Element,
    label: Element,
    pub button: Option<HtmlButtonElement>,
}

impl Dom {
    pub(super) fn render_modules(&mut self, view: &ControlView) -> Result<(), ControlError> {
        let modules = view
            .snapshot
            .as_ref()
            .map(RuntimeSnapshot::modules)
            .unwrap_or_default();
        let ids: Vec<_> = modules
            .iter()
            .map(|module| module.id().to_owned())
            .collect();
        if view.snapshot.is_some() {
            let selected = retained_target(&self.target.value(), &ids, self.target_initialized);
            if self.target_order != ids {
                self.target.set_text_content(None);
                let empty = self.document.create_element("option").map_err(dom_error)?;
                empty.set_attribute("value", "").map_err(dom_error)?;
                set_text(&empty, "Choose a target");
                self.target.append_child(&empty).map_err(dom_error)?;
                for id in &ids {
                    let option = self.document.create_element("option").map_err(dom_error)?;
                    option.set_attribute("value", id).map_err(dom_error)?;
                    set_text(&option, id);
                    self.target.append_child(&option).map_err(dom_error)?;
                }
                self.target_order = ids.clone();
            }
            self.target.set_value(&selected);
            if !ids.is_empty() {
                self.target_initialized = true;
            }
        }
        self.module_rows.retain(|id, row| {
            let keep = ids.contains(id);
            if !keep {
                row.node.remove();
            }
            keep
        });
        for module in modules {
            if !self.module_rows.contains_key(module.id()) {
                let node = self.document.create_element("tr").map_err(dom_error)?;
                let mut cells = Vec::with_capacity(4);
                for _ in 0..4 {
                    let cell = self.document.create_element("td").map_err(dom_error)?;
                    node.append_child(&cell).map_err(dom_error)?;
                    cells.push(cell);
                }
                self.module_rows
                    .insert(module.id().into(), ModuleRow { node, cells });
            }
            let row = self
                .module_rows
                .get(module.id())
                .ok_or_else(ControlError::invalid)?;
            for (cell, text) in row.cells.iter().zip([
                module.id().to_owned(),
                runtime_status(module.status()).to_owned(),
                module.revision().to_string(),
                redact_digest(module.semantic_digest()),
            ]) {
                set_text(cell, &text);
            }
        }
        if self.module_order != ids || self.modules.child_element_count() == 0 {
            if ids.is_empty() {
                self.modules.set_text_content(None);
                let row = self.document.create_element("tr").map_err(dom_error)?;
                let cell = self.document.create_element("td").map_err(dom_error)?;
                cell.set_attribute("colspan", "4").map_err(dom_error)?;
                set_text(
                    &cell,
                    if view.stale {
                        "No current runtime snapshot."
                    } else {
                        "No runtime modules reported."
                    },
                );
                row.append_child(&cell).map_err(dom_error)?;
                self.modules.append_child(&row).map_err(dom_error)?;
            } else {
                if self.module_order.is_empty() {
                    self.modules.set_text_content(None);
                }
                for id in &ids {
                    self.modules
                        .append_child(&self.module_rows[id].node)
                        .map_err(dom_error)?;
                }
            }
            self.module_order = ids;
        }
        Ok(())
    }

    pub(super) fn render_operations(
        &mut self,
        operations: &[OperationView],
        state: &RenderState<'_>,
    ) -> Result<(), ControlError> {
        let focused = self.document.active_element();
        let focused_id = self.pending_rows.iter().find_map(|(id, row)| {
            row.button
                .as_ref()
                .filter(|button| {
                    focused
                        .as_ref()
                        .is_some_and(|element| button.is_same_node(Some(element)))
                })
                .map(|_| id.clone())
        });
        let ids: Vec<_> = operations
            .iter()
            .map(|operation| operation.operation_id.clone())
            .collect();
        self.pending_rows.retain(|id, row| {
            let keep = ids.contains(id);
            if !keep {
                row.node.remove();
            }
            keep
        });
        for operation in operations {
            if !self.pending_rows.contains_key(&operation.operation_id) {
                let node = self.document.create_element("li").map_err(dom_error)?;
                let label = self.document.create_element("span").map_err(dom_error)?;
                node.append_child(&label).map_err(dom_error)?;
                self.pending_rows.insert(
                    operation.operation_id.clone(),
                    OperationRow {
                        node,
                        label,
                        button: None,
                    },
                );
            }
            let row = self
                .pending_rows
                .get_mut(&operation.operation_id)
                .ok_or_else(ControlError::invalid)?;
            set_text(
                &row.label,
                &format!(
                    "{} · {} · {} · generation {} · revision {} · digest {}",
                    redact_identifier(&operation.operation_id),
                    operation_state(operation.state),
                    redact_identifier(operation.audit_trace_id.as_deref().unwrap_or("")),
                    operation.generation,
                    operation.displayed_revision,
                    redact_digest(&operation.semantic_digest)
                ),
            );
            if operation.state == OperationState::Indeterminate {
                if row.button.is_none() {
                    let button: HtmlButtonElement =
                        cast(self.document.create_element("button").map_err(dom_error)?)?;
                    button.set_type("button");
                    set_text(&button, "Recover operation");
                    button
                        .set_attribute(
                            "aria-label",
                            &format!(
                                "Recover operation {}",
                                redact_identifier(&operation.operation_id)
                            ),
                        )
                        .map_err(dom_error)?;
                    row.node.append_child(&button).map_err(dom_error)?;
                    row.button = Some(button);
                }
                if let Some(button) = &row.button {
                    button.set_disabled(
                        state.destroyed
                            || !state.connected
                            || state.recovering.contains(&operation.operation_id),
                    );
                }
            } else if let Some(button) = row.button.take() {
                button.remove();
            }
        }
        if self.pending_order != ids || self.pending.child_element_count() == 0 {
            if ids.is_empty() {
                self.pending.set_text_content(None);
                let empty = self.document.create_element("li").map_err(dom_error)?;
                set_text(&empty, "No pending operations.");
                self.pending.append_child(&empty).map_err(dom_error)?;
            } else {
                if self.pending_order.is_empty() {
                    self.pending.set_text_content(None);
                }
                for id in &ids {
                    self.pending
                        .append_child(&self.pending_rows[id].node)
                        .map_err(dom_error)?;
                }
            }
            self.pending_order = ids;
        }
        if let Some(id) = focused_id {
            if let Some(button) = self
                .pending_rows
                .get(&id)
                .and_then(|row| row.button.as_ref())
                .filter(|button| !button.disabled())
            {
                let _ = button.focus();
            } else {
                let _ = self.live.set_attribute("tabindex", "-1");
                let _ = self.live.focus();
            }
        }
        Ok(())
    }

    pub(super) fn render_completed(
        &mut self,
        operations: &[OperationView],
    ) -> Result<(), ControlError> {
        let ids: Vec<_> = operations
            .iter()
            .map(|operation| operation.operation_id.clone())
            .collect();
        self.completed_rows.retain(|id, row| {
            let keep = ids.contains(id);
            if !keep {
                row.node.remove();
            }
            keep
        });
        for operation in operations {
            if !self.completed_rows.contains_key(&operation.operation_id) {
                let node = self.document.create_element("li").map_err(dom_error)?;
                self.completed_rows.insert(
                    operation.operation_id.clone(),
                    OperationRow {
                        label: node.clone(),
                        node,
                        button: None,
                    },
                );
            }
            let row = self
                .completed_rows
                .get(&operation.operation_id)
                .ok_or_else(ControlError::invalid)?;
            set_text(
                &row.label,
                &format!(
                    "{} · {} · {} · generation {} · revision {} · digest {} · outcome {}",
                    redact_identifier(&operation.operation_id),
                    operation.terminal_status.as_deref().unwrap_or("terminal"),
                    redact_identifier(operation.audit_trace_id.as_deref().unwrap_or("")),
                    operation.generation,
                    operation.displayed_revision,
                    redact_digest(&operation.semantic_digest),
                    redact_digest(operation.outcome_digest.as_deref().unwrap_or(""))
                ),
            );
        }
        if self.completed_order != ids || self.completed.child_element_count() == 0 {
            if ids.is_empty() {
                self.completed.set_text_content(None);
                let empty = self.document.create_element("li").map_err(dom_error)?;
                set_text(&empty, "No terminal operations observed in this session.");
                self.completed.append_child(&empty).map_err(dom_error)?;
            } else {
                if self.completed_order.is_empty() {
                    self.completed.set_text_content(None);
                }
                for id in &ids {
                    self.completed
                        .append_child(&self.completed_rows[id].node)
                        .map_err(dom_error)?;
                }
            }
            self.completed_order = ids;
        }
        Ok(())
    }
}
