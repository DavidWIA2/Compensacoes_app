from pathlib import Path

from PIL import Image

from scripts.generate_app_icon import (
    DEFAULT_SOURCE,
    build_padded_master,
    export_ico,
    export_pngs,
    reduce_white_halo,
    strip_light_background,
)


def _make_base_icon() -> Image.Image:
    image = Image.new("RGBA", (120, 100), (0, 0, 0, 0))
    for x in range(20, 100):
        for y in range(10, 90):
            image.putpixel((x, y), (24, 32, 48, 255))
    image.putpixel((19, 50), (255, 255, 255, 96))
    return image


def test_build_padded_master_keeps_transparent_corners() -> None:
    base = _make_base_icon()
    cleaned = reduce_white_halo(base)

    master = build_padded_master(cleaned, master_size=256, padding_ratio=0.08)

    assert master.size == (256, 256)
    assert master.getpixel((0, 0))[3] == 0
    assert master.getchannel("A").getbbox() is not None


def test_strip_light_background_removes_opaque_checkerboard_border() -> None:
    image = Image.new("RGBA", (96, 96), (244, 244, 244, 255))
    for x in range(18, 78):
        for y in range(16, 80):
            image.putpixel((x, y), (28, 76, 148, 255))

    cleaned = strip_light_background(image)

    assert cleaned.getpixel((0, 0))[3] == 0
    assert cleaned.getchannel("A").getbbox() == (18, 16, 78, 80)


def test_default_source_uses_colored_logo_asset() -> None:
    assert DEFAULT_SOURCE.name == "Logo_512.png"


def test_export_pngs_and_ico_create_expected_files(tmp_path: Path) -> None:
    master = build_padded_master(reduce_white_halo(_make_base_icon()), master_size=256, padding_ratio=0.08)

    png_paths = export_pngs(master, output_dir=tmp_path / "icons", sizes=[256, 64, 16])
    ico_path = export_ico(master, ico_path=tmp_path / "app.ico", sizes=[256, 64, 16])

    assert [path.name for path in png_paths] == [
        "pga_icon_clean_256.png",
        "pga_icon_clean_64.png",
        "pga_icon_clean_16.png",
    ]
    assert all(path.exists() for path in png_paths)
    assert ico_path.exists()
