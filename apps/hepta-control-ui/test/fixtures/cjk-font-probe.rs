extern crate makepad_widgets;
extern crate rustybuzz;
use makepad_widgets::makepad_draw::text::{
    font_face::FontFace,
    geom::{Point, Rect, Size},
    glyph_outline::Builder,
    image::{Image, R},
    loader::FontData,
};
#[unsafe(no_mangle)]
pub extern "C" fn check_fonts() -> u32 {
    let mut count = 0;
    for bytes in [
        include_bytes!(concat!(
            env!("HEPTA_CJK_FONT_DIR"),
            "/NotoSansSC-Regular.otf"
        ))
        .as_slice(),
        include_bytes!(concat!(env!("HEPTA_CJK_FONT_DIR"), "/NotoSansSC-Bold.otf")).as_slice(),
    ] {
        let face = FontFace::from_data_and_index(FontData::from_vec(bytes.to_vec()), 0)
            .expect("static CFF face");
        let mut buffer = rustybuzz::UnicodeBuffer::new();
        buffer.push_str("中文输入鍵盤日本語");
        buffer.guess_segment_properties();
        let shaped = face.shape(&[], buffer);
        assert!(shaped.glyph_infos().iter().all(|g| g.glyph_id > 0));
        assert!(
            shaped
                .glyph_positions()
                .iter()
                .map(|p| p.x_advance)
                .sum::<i32>()
                > 0
        );
        count += 1;
        face.with_ttf_parser_face(|f| {
            for c in "中文输入键盘焦点滚动位置繁體漢字日本語かなカナ".chars()
            {
                let id = f.glyph_index(c).expect("glyph coverage");
                assert!(f.glyph_hor_advance(id).unwrap() > 0);
                let mut builder = Builder::new();
                let b = f.outline_glyph(id, &mut builder).expect("CFF outline");
                let outline = builder.finish(
                    Rect::new(
                        Point::new(b.x_min as f32, b.y_min as f32),
                        Size::new((b.x_max - b.x_min) as f32, (b.y_max - b.y_min) as f32),
                    ),
                    f.units_per_em() as f32,
                );
                assert!(!outline.commands().is_empty());
                let mut pixels = Image::<R>::new(Size::new(128, 128));
                outline.rasterize(
                    32.0,
                    &mut pixels.subimage_mut(Rect::new(Point::new(0, 0), Size::new(128, 128))),
                );
                assert!(pixels.as_pixels().iter().any(|p| p.r() > 0));
                count += 1;
            }
        });
    }
    count
}
