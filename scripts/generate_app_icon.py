from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

from PIL import Image


DEFAULT_SOURCE = Path("assets/Logo_mono_512.png")
DEFAULT_OUTPUT_DIR = Path("assets/icons")
DEFAULT_ICO_PATH = Path("assets/app.ico")
DEFAULT_SIZES = (1024, 512, 256, 128, 64, 48, 32, 16)
DEFAULT_PADDING_RATIO = 0.08
ALPHA_THRESHOLD = 1
NEIGHBOR_ALPHA_THRESHOLD = 40
LIGHT_PIXEL_THRESHOLD = 225


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Regenera os icones do app a partir de um PNG com alpha."
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help="PNG base com transparencia real.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Diretorio de saida dos PNGs finais.",
    )
    parser.add_argument(
        "--ico-path",
        type=Path,
        default=DEFAULT_ICO_PATH,
        help="Caminho do arquivo .ico final.",
    )
    parser.add_argument(
        "--padding",
        type=float,
        default=DEFAULT_PADDING_RATIO,
        help="Padding proporcional aplicado apos o recorte (ex.: 0.08 = 8%%).",
    )
    parser.add_argument(
        "--sizes",
        type=int,
        nargs="+",
        default=list(DEFAULT_SIZES),
        help="Lista de tamanhos quadrados a exportar.",
    )
    return parser.parse_args()


def _load_rgba(path: Path) -> Image.Image:
    with Image.open(path) as image:
        return image.convert("RGBA")


def _content_bbox(image: Image.Image) -> tuple[int, int, int, int]:
    alpha = image.getchannel("A")
    bbox = alpha.point(lambda value: 255 if value >= ALPHA_THRESHOLD else 0).getbbox()
    if bbox is None:
        raise ValueError("O PNG base nao possui conteudo visivel no canal alpha.")
    return bbox


def _iter_neighbors(x: int, y: int, width: int, height: int, radius: int = 2) -> Iterable[tuple[int, int, int]]:
    for radius_step in range(1, radius + 1):
        for dy in range(-radius_step, radius_step + 1):
            for dx in range(-radius_step, radius_step + 1):
                if dx == 0 and dy == 0:
                    continue
                nx = x + dx
                ny = y + dy
                if 0 <= nx < width and 0 <= ny < height:
                    distance = abs(dx) + abs(dy)
                    yield nx, ny, max(distance, 1)


def _weighted_neighbor_color(pixels, x: int, y: int, width: int, height: int) -> tuple[int, int, int] | None:
    total_weight = 0.0
    accum_r = 0.0
    accum_g = 0.0
    accum_b = 0.0
    for nx, ny, distance in _iter_neighbors(x, y, width, height):
        red, green, blue, alpha = pixels[nx, ny]
        if alpha < NEIGHBOR_ALPHA_THRESHOLD:
            continue
        weight = (alpha / 255.0) / float(distance)
        accum_r += red * weight
        accum_g += green * weight
        accum_b += blue * weight
        total_weight += weight
    if total_weight <= 0:
        return None
    return (
        int(round(accum_r / total_weight)),
        int(round(accum_g / total_weight)),
        int(round(accum_b / total_weight)),
    )


def _unpremultiply_if_needed(red: int, green: int, blue: int, alpha: int) -> tuple[int, int, int]:
    if alpha <= 0 or alpha >= 255:
        return red, green, blue
    if max(red, green, blue) > alpha + 2:
        return red, green, blue
    scale = 255.0 / float(alpha)
    return (
        min(255, int(round(red * scale))),
        min(255, int(round(green * scale))),
        min(255, int(round(blue * scale))),
    )


def reduce_white_halo(image: Image.Image) -> Image.Image:
    pixels = image.load()
    width, height = image.size
    cleaned = image.copy()
    target_pixels = cleaned.load()

    for y in range(height):
        for x in range(width):
            red, green, blue, alpha = pixels[x, y]
            if alpha <= 0:
                target_pixels[x, y] = (0, 0, 0, 0)
                continue

            red, green, blue = _unpremultiply_if_needed(red, green, blue, alpha)
            luminance = (red + green + blue) / 3.0

            if alpha < 255 and luminance >= LIGHT_PIXEL_THRESHOLD:
                neighbor_color = _weighted_neighbor_color(pixels, x, y, width, height)
                if neighbor_color is not None:
                    mix_ratio = min(1.0, max(0.55, alpha / 255.0))
                    red = int(round(neighbor_color[0] * (1.0 - mix_ratio) + red * mix_ratio))
                    green = int(round(neighbor_color[1] * (1.0 - mix_ratio) + green * mix_ratio))
                    blue = int(round(neighbor_color[2] * (1.0 - mix_ratio) + blue * mix_ratio))

            target_pixels[x, y] = (red, green, blue, alpha)

    return cleaned


def build_padded_master(image: Image.Image, *, master_size: int, padding_ratio: float) -> Image.Image:
    bbox = _content_bbox(image)
    cropped = image.crop(bbox)
    crop_width, crop_height = cropped.size
    if crop_width <= 0 or crop_height <= 0:
        raise ValueError("O recorte do icone ficou vazio.")

    padding_ratio = min(max(float(padding_ratio), 0.06), 0.10)
    usable_size = max(1, int(round(master_size * (1.0 - (padding_ratio * 2.0)))))
    scale = min(usable_size / float(crop_width), usable_size / float(crop_height))
    resized_width = max(1, int(round(crop_width * scale)))
    resized_height = max(1, int(round(crop_height * scale)))
    resized = cropped.resize((resized_width, resized_height), Image.Resampling.LANCZOS)

    canvas = Image.new("RGBA", (master_size, master_size), (0, 0, 0, 0))
    offset_x = (master_size - resized_width) // 2
    offset_y = (master_size - resized_height) // 2
    canvas.alpha_composite(resized, (offset_x, offset_y))
    return canvas


def export_pngs(master_image: Image.Image, *, output_dir: Path, sizes: Iterable[int]) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    exported_paths: list[Path] = []
    for size in sorted({int(size) for size in sizes if int(size) > 0}, reverse=True):
        resized = master_image.resize((size, size), Image.Resampling.LANCZOS)
        output_path = output_dir / f"pga_icon_clean_{size}.png"
        resized.save(output_path, format="PNG")
        exported_paths.append(output_path)
    return exported_paths


def export_ico(master_image: Image.Image, *, ico_path: Path, sizes: Iterable[int]) -> Path:
    ico_path.parent.mkdir(parents=True, exist_ok=True)
    sorted_sizes = sorted({int(size) for size in sizes if int(size) > 0})
    master_image.save(
        ico_path,
        format="ICO",
        sizes=[(size, size) for size in sorted_sizes],
    )
    return ico_path


def main() -> int:
    args = _parse_args()
    source_path = args.source
    if not source_path.exists():
        raise FileNotFoundError(f"PNG base nao encontrado: {source_path}")

    rgba_image = _load_rgba(source_path)
    cleaned_image = reduce_white_halo(rgba_image)
    master_size = max(int(size) for size in args.sizes)
    master_image = build_padded_master(
        cleaned_image,
        master_size=master_size,
        padding_ratio=args.padding,
    )

    exported_pngs = export_pngs(
        master_image,
        output_dir=args.output_dir,
        sizes=args.sizes,
    )
    ico_path = export_ico(
        master_image,
        ico_path=args.ico_path,
        sizes=args.sizes,
    )

    print(f"Fonte: {source_path}")
    print(f"PNGs gerados: {len(exported_pngs)} em {args.output_dir}")
    for png_path in exported_pngs:
        print(f" - {png_path}")
    print(f"ICO gerado: {ico_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
