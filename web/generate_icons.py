"""
Generate clean, original PWA icons for Universal Clipboard AI.
Outputs:
- web/static/icons/icon-192.png
- web/static/icons/icon-512.png
- web/static/icons/icon-maskable-192.png
- web/static/icons/icon-maskable-512.png
- web/static/icons/icon.svg
"""
from pathlib import Path
from PIL import Image, ImageDraw

ICONS_DIR = Path(__file__).resolve().parent.parent / "web" / "static" / "icons"
ICONS_DIR.mkdir(parents=True, exist_ok=True)


def draw_clipboard(size: int, is_maskable: bool = False) -> Image.Image:
    # High resolution canvas for smooth anti-aliased downsampling
    canvas_size = 1024
    img = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # If maskable, fill entire background with brand dark slate color
    if is_maskable:
        draw.rectangle([0, 0, canvas_size, canvas_size], fill=(11, 15, 23, 255))
        # Scale inner graphic to fit within 70% safe zone
        scale = 0.70
        offset_x = canvas_size * 0.15
        offset_y = canvas_size * 0.15
    else:
        # Rounded squircle background
        pad = 64
        draw.rounded_rectangle(
            [pad, pad, canvas_size - pad, canvas_size - pad],
            radius=180,
            fill=(17, 24, 39, 255),
            outline=(99, 102, 241, 180),
            width=16,
        )
        scale = 0.82
        offset_x = canvas_size * 0.09
        offset_y = canvas_size * 0.09

    # Clipboard board
    board_x0 = offset_x + 160 * scale
    board_y0 = offset_y + 140 * scale
    board_x1 = offset_x + (1024 - 160) * scale
    board_y1 = offset_y + (1024 - 100) * scale
    board_radius = int(60 * scale)

    # Board drop shadow
    draw.rounded_rectangle(
        [board_x0 + 10, board_y0 + 15, board_x1 + 10, board_y1 + 15],
        radius=board_radius,
        fill=(5, 8, 14, 180),
    )

    # Board background (gradient-like indigo/dark)
    draw.rounded_rectangle(
        [board_x0, board_y0, board_x1, board_y1],
        radius=board_radius,
        fill=(22, 31, 48, 255),
        outline=(99, 102, 241, 240),
        width=int(14 * scale),
    )

    # Clipboard paper sheet
    paper_pad_x = 55 * scale
    paper_pad_y = 90 * scale
    paper_x0 = board_x0 + paper_pad_x
    paper_y0 = board_y0 + paper_pad_y
    paper_x1 = board_x1 - paper_pad_x
    paper_y1 = board_y1 - 50 * scale
    paper_radius = int(32 * scale)

    draw.rounded_rectangle(
        [paper_x0, paper_y0, paper_x1, paper_y1],
        radius=paper_radius,
        fill=(241, 245, 249, 255),
    )

    # Paper content lines (representing clipboard items)
    line_x0 = paper_x0 + 60 * scale
    line_x1 = paper_x1 - 60 * scale
    line_color = (148, 163, 184, 255)
    accent_color = (99, 102, 241, 255)
    line_width = int(18 * scale)

    # Line 1: Header / Accent item
    draw.rounded_rectangle(
        [line_x0, paper_y0 + 100 * scale, line_x0 + 180 * scale, paper_y0 + 100 * scale + line_width],
        radius=int(9 * scale),
        fill=accent_color,
    )

    # Line 2: Text preview
    draw.rounded_rectangle(
        [line_x0, paper_y0 + 180 * scale, line_x1, paper_y0 + 180 * scale + line_width],
        radius=int(9 * scale),
        fill=line_color,
    )

    # Line 3: Text preview shorter
    draw.rounded_rectangle(
        [line_x0, paper_y0 + 250 * scale, line_x0 + 320 * scale, paper_y0 + 250 * scale + line_width],
        radius=int(9 * scale),
        fill=line_color,
    )

    # Line 4: Checkmark / sync indicator at bottom
    sync_cyan = (6, 182, 212, 255)
    draw.rounded_rectangle(
        [line_x0, paper_y0 + 350 * scale, line_x0 + 140 * scale, paper_y0 + 350 * scale + int(24 * scale)],
        radius=int(12 * scale),
        fill=sync_cyan,
    )

    # Metallic Clip at top
    clip_w = 260 * scale
    clip_h = 90 * scale
    clip_cx = (board_x0 + board_x1) / 2
    clip_x0 = clip_cx - clip_w / 2
    clip_y0 = board_y0 - 30 * scale
    clip_x1 = clip_cx + clip_w / 2
    clip_y1 = clip_y0 + clip_h

    # Clip shadow
    draw.rounded_rectangle(
        [clip_x0, clip_y0 + 6, clip_x1, clip_y1 + 6],
        radius=int(24 * scale),
        fill=(0, 0, 0, 140),
    )

    # Clip body (silver/slate)
    draw.rounded_rectangle(
        [clip_x0, clip_y0, clip_x1, clip_y1],
        radius=int(24 * scale),
        fill=(203, 213, 225, 255),
        outline=(100, 116, 139, 255),
        width=int(8 * scale),
    )

    # Clip hole
    hole_w = 90 * scale
    hole_h = 30 * scale
    draw.rounded_rectangle(
        [clip_cx - hole_w / 2, clip_y0 + 28 * scale, clip_cx + hole_w / 2, clip_y0 + 28 * scale + hole_h],
        radius=int(14 * scale),
        fill=(17, 24, 39, 255),
    )

    # Resize with high quality Lanczos filter
    return img.resize((size, size), Image.Resampling.LANCZOS)


# Generate the required icon files
for size in (192, 512):
    standard = draw_clipboard(size, is_maskable=False)
    standard.save(ICONS_DIR / f"icon-{size}.png", "PNG", optimize=True)

    maskable = draw_clipboard(size, is_maskable=True)
    maskable.save(ICONS_DIR / f"icon-maskable-{size}.png", "PNG", optimize=True)

print(f"Generated icons in {ICONS_DIR}")
