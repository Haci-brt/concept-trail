"""Render the app icon: PNGs at every size Windows asks for and one .ico.

    python assets/icon/build_icons.py

The detailed mark is drawn from 48 px up; 16–32 px use the simpler one,
where hairlines and far stars would only turn to mush. Needs PyQt6 (already
a dependency) and Pillow (only here, not at run time).
"""
import sys
from pathlib import Path

from PyQt6.QtCore import QByteArray, Qt
from PyQt6.QtGui import QGuiApplication, QImage, QPainter
from PyQt6.QtSvg import QSvgRenderer

HERE = Path(__file__).resolve().parent
SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256, 512)
SMALL = 32


def render(svg: Path, size: int) -> QImage:
    renderer = QSvgRenderer(QByteArray(svg.read_bytes()))
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    renderer.render(painter)
    painter.end()
    return image


def main() -> None:
    from PIL import Image

    QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    out = HERE / "png"
    out.mkdir(exist_ok=True)
    frames = []
    for size in SIZES:
        svg = HERE / ("concept-trail-small.svg" if size <= SMALL else "concept-trail.svg")
        path = out / f"concept-trail-{size}.png"
        render(svg, size).save(str(path))
        if size <= 256:
            frames.append(Image.open(path).convert("RGBA"))
    frames[-1].save(HERE / "concept-trail.ico", format="ICO",
                    sizes=[(f.width, f.height) for f in frames], append_images=frames[:-1])
    print("yazıldı:", ", ".join(p.name for p in sorted(out.glob("*.png"))), "+ concept-trail.ico")


if __name__ == "__main__":
    main()
