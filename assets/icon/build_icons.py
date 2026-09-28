"""Make every size of the app icon from the 1024 px master.

    python assets/icon/build_icons.py

concept-trail.png is the master (a notebook cover with a trail of stars
climbing to a bright one, and the pen writing it). This writes png/ at every
size the OS and the page ask for, and concept-trail.ico for the Windows
shortcut and window. Small sizes get a light unsharp mask so the rings, the
trail and the star stay crisp. Needs Pillow (only here, not at run time).
"""
from pathlib import Path

from PIL import Image, ImageFilter

HERE = Path(__file__).resolve().parent
MASTER = HERE / "concept-trail.png"
SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256, 512)
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
WEB = HERE.parent.parent / "web" / "assets"


def scaled(master: Image.Image, size: int) -> Image.Image:
    # halve step by step first: one big jump to 16 px drops the thin trail
    image = master
    while image.width > size * 2:
        image = image.resize((image.width // 2, image.height // 2), Image.LANCZOS)
    image = image.resize((size, size), Image.LANCZOS)
    if size <= 48:
        image = image.filter(ImageFilter.UnsharpMask(radius=0.6, percent=60 if size <= 24 else 40, threshold=1))
    return image


def main() -> None:
    master = Image.open(MASTER).convert("RGBA")
    out = HERE / "png"
    out.mkdir(exist_ok=True)
    frames = {}
    for size in SIZES:
        frames[size] = scaled(master, size)
        frames[size].save(out / f"concept-trail-{size}.png", optimize=True)
    largest = frames[max(ICO_SIZES)]
    largest.save(HERE / "concept-trail.ico", format="ICO", sizes=[(s, s) for s in ICO_SIZES],
                 append_images=[frames[s] for s in ICO_SIZES if s != max(ICO_SIZES)])
    # the page's tab icon and in-app mark
    frames[64].save(WEB / "concept-trail-64.png", optimize=True)
    frames[256].save(WEB / "concept-trail-256.png", optimize=True)
    print("yazıldı:", len(SIZES), "PNG, concept-trail.ico, web/assets/concept-trail-64.png ve -256.png")


if __name__ == "__main__":
    main()
