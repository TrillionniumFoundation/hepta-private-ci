use super::*;

#[test]
fn colors_round_trip_without_role_collisions() {
    for (role, row) in PALETTES.iter().enumerate() {
        for color in row {
            assert!(PALETTES.iter().enumerate().all(|(other, values)| role == other || !values.contains(color)));
        }
        let c = rgba(row[1]);
        let mut value = [c.x, c.y, c.z, c.w];
        for choice in [HeptaTheme::DeepSpaceTitanium, HeptaTheme::ObsidianCeramic, HeptaTheme::PolarPrism] {
            retarget(&mut value, choice);
            let expected = rgba(row[choice.index()]);
            assert_eq!(value, [expected.x, expected.y, expected.z, expected.w]);
        }
    }
}

#[test]
fn unowned_colors_and_geometry_are_unchanged() {
    for mut value in [[0.0, 0.0, 0.0, 0.0], [0.3, 0.5, 0.9, 1.0], [-1.0; 4]] {
        let before = value;
        assert!(!retarget(&mut value, HeptaTheme::DeepSpaceTitanium));
        assert_eq!(value, before);
    }
    let mut dimension = [12.0];
    assert!(!material(&mut dimension, id!(border_radius), HeptaTheme::DeepSpaceTitanium));
    assert_eq!(dimension, [12.0]);
}

#[test]
fn selection_preserves_real_input_identity_text_cursor_and_selection() {
    let mut cx = Cx::new(Box::new(|_, _| {}));
    let mut input = cx.with_vm(|vm| {
        makepad_widgets::script_mod(vm);
        let value = script_eval!(vm, { mod.widgets.TextInput {} });
        TextInput::script_from_value(vm, value)
    });
    input.set_text(&mut cx, "Draft with a reply and an unfinished edit");
    input.move_cursor_left(&mut cx, true);
    let before = (input.widget_uid(), input.text(), input.cursor(), input.selection().anchor);
    for theme in [HeptaTheme::DeepSpaceTitanium, HeptaTheme::ObsidianCeramic, HeptaTheme::PolarPrism] {
        select(&mut cx, theme);
        paint(&mut cx);
        assert_eq!((input.widget_uid(), input.text(), input.cursor(), input.selection().anchor), before);
    }
}

#[test]
fn only_explicit_materials_own_color_slots() {
    let mut cx = Cx::new(Box::new(|_, _| {}));
    let (panel, foreign) = cx.with_vm(|vm| {
        makepad_widgets::script_mod(vm);
        super::script_mod(vm);
        let panel = script_eval!(vm, { mod.widgets.HeptaPanel {} });
        let panel = View::script_from_value(vm, panel);
        let foreign = script_eval!(vm, {
            mod.widgets.SolidView { draw_bg.color: #x171329 }
        });
        (panel, View::script_from_value(vm, foreign))
    });
    let panel_shader = panel.draw_bg.draw_vars.draw_shader_id.expect("real panel shader").index;
    let foreign_shader = foreign.draw_bg.draw_vars.draw_shader_id.expect("real unowned shader").index;
    assert!(owned_material(&cx, panel_shader).is_some(), "tag must survive shader compilation");
    assert!(owned_material(&cx, foreign_shader).is_none(), "matching bytes do not grant ownership");
}

#[test]
fn avatar_ownership_excludes_caller_color_even_when_palette_bytes_match() {
    let mut cx = Cx::new(Box::new(|_, _| {}));
    let avatar = cx.with_vm(|vm| {
        makepad_widgets::script_mod(vm);
        let value = script_eval!(vm, {
            use mod.prelude.widgets.*
            mod.widgets.SolidView {
                draw_bg +: {
                    hepta_owned_avatar: uniform(1.0)
                    hepta_color_avatar: uniform(#x382e55)
                    color: #x171329
                    pixel: fn() { return if self.color.x < -0.5 self.hepta_color_avatar else self.color }
                }
            }
        });
        View::script_from_value(vm, value)
    });
    let shader = avatar.draw_bg.draw_vars.draw_shader_id.unwrap().index;
    let slots = owned_material(&cx, shader).unwrap();
    assert!(slots.colors.is_empty(), "caller colors never grant theme ownership");
    assert_eq!(slots.uniforms.iter().map(|s| s.0).collect::<Vec<_>>(), vec![id!(hepta_color_avatar)]);
}

#[test]
fn paint_changes_owned_material_without_touching_same_color_foreign_content() {
    let mut cx = Cx::new(Box::new(|_, _| {}));
    let (mut panel, mut foreign) = cx.with_vm(|vm| {
        makepad_widgets::script_mod(vm);
        super::script_mod(vm);
        let value = script_eval!(vm, { mod.widgets.HeptaPanel {width: 80, height: 60} });
        let panel = View::script_from_value(vm, value);
        let value = script_eval!(vm, { mod.widgets.SolidView {width: 80, height: 60, draw_bg.color: #x171329} });
        (panel, View::script_from_value(vm, value))
    });
    let pass = DrawPass::new(&mut cx);
    pass.set_size(&mut cx, dvec2(320.0, 240.0));
    let mut list = DrawList::new(&mut cx);
    let event = DrawEvent::default();
    let mut draw = CxDraw::new(&mut cx, &event);
    draw.begin_pass(&pass, None);
    list.begin_always(&mut draw);
    {
        let mut cx = Cx2d::new(&mut draw);
        cx.begin_root_turtle(dvec2(320.0, 240.0), Layout::flow_down());
        panel.draw_all(&mut cx, &mut Scope::empty());
        foreign.draw_all(&mut cx, &mut Scope::empty());
        cx.end_turtle();
    }
    list.end(&mut draw);
    draw.end_pass(&pass);
    drop(draw);
    let Area::Instance(foreign_area) = foreign.area() else { panic!("real foreign draw instance") };
    let foreign_before = cx.draw_lists[foreign_area.draw_list_id].draw_items[foreign_area.draw_item_id].instances.clone();
    let Area::Instance(panel_area) = panel.area() else { panic!("real panel draw instance") };
    for choice in [HeptaTheme::DeepSpaceTitanium, HeptaTheme::PolarPrism, HeptaTheme::ObsidianCeramic] {
        select(&mut cx, choice);
        paint(&mut cx);
        assert_eq!(cx.draw_lists[foreign_area.draw_list_id].draw_items[foreign_area.draw_item_id].instances, foreign_before);
        let item = &cx.draw_lists[panel_area.draw_list_id].draw_items[panel_area.draw_item_id];
        let call = item.draw_call().unwrap();
        let mapping = &cx.draw_shaders.shaders[call.draw_shader_id.index].mapping;
        let color = mapping.instances.inputs.iter().find(|input| input.id == id!(color)).unwrap();
        let at = panel_area.instance_offset + color.offset;
        let expected = rgba(PALETTES[1][choice.index()]);
        assert_eq!(&item.instances.as_ref().unwrap()[at..at + 4], &[expected.x, expected.y, expected.z, expected.w]);
        let radius = mapping.dyn_uniforms.inputs.iter().find(|input| input.id == id!(hepta_radius)).unwrap();
        assert_eq!(call.dyn_uniforms[radius.offset], [6.0, 12.0, 9.0][choice.index()]);
    }
}

#[test]
fn runtime_button_style_helpers_do_not_redeclare_shader_uniforms() {
    let mut cx = Cx::new(Box::new(|_, _| {}));
    let mut button = cx.with_vm(|vm| {
        vm.bx.captured_errors = Some(Vec::new());
        let _ = <crate::app::App as AppMain>::script_mod(vm);
        let value = script_eval!(vm, {mod.widgets.RobrixIconButton {text: "Fixture"}});
        WidgetRef::script_from_value(vm, value).as_button()
    });
    let uid = button.widget_uid();
    for style in [super::super::styles::apply_positive_button_style,
        super::super::styles::apply_negative_button_style,
        super::super::styles::apply_neutral_button_style,
        super::super::styles::apply_primary_button_style] {
        style(&mut cx, &mut button);
        assert_eq!(button.widget_uid(), uid);
        cx.with_vm(|vm| assert!(vm.take_errors().is_empty(), "runtime style script errors"));
    }
}
