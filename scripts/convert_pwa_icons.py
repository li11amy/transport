#!/usr/bin/env python3
"""Convert legacy paletted transport PWA icons to truecolor PNG for Android WebAPK.

Does not redesign the existing AVÍO transport artwork. Requires Pillow.
"""
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
WHITE = (255, 255, 255)

def flatten(source):
    image = Image.open(ROOT / source).convert("RGBA")
    background = Image.new("RGBA", image.size, WHITE + (255,))
    background.alpha_composite(image)
    return background.convert("RGB")

def main():
    for size in (192, 512):
        src = flatten("icon-{}.png".format(size))
        if src.size != (size, size):
            raise ValueError("Unexpected source icon dimensions: {}".format(src.size))
        target = ROOT / "icon-{}-rgb.png".format(size)
        src.save(target, "PNG", optimize=True)
        with Image.open(target) as result:
            assert result.mode == "RGB" and result.size == (size, size)
        print(target.name, target.stat().st_size, "bytes, truecolor", flush=True)

    # Maskable safe-zone: all content is inside central 80% of the canvas,
    # so Android can crop the outside without cutting off the illustration.
    base = flatten("icon-512.png")
    mask = Image.new("RGB", (512, 512), WHITE)
    logo = base.resize((384, 384), Image.Resampling.LANCZOS)
    mask.paste(logo, (64, 64))
    target = ROOT / "icon-512-maskable.png"
    mask.save(target, "PNG", optimize=True)
    with Image.open(target) as result:
        assert result.mode == "RGB" and result.size == (512, 512)
    print(target.name, target.stat().st_size, "bytes, truecolor", flush=True)

if __name__ == "__main__":
    main()
