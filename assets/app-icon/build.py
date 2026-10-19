"""Rebuild EyeCursor's transparent PNG and macOS ICNS from its editable SVG."""
from pathlib import Path
import subprocess
import tempfile


def main():
    assets = Path(__file__).resolve().parent
    cache = assets.parents[1] / '.venv' / 'swift-cache'
    cache.mkdir(parents=True, exist_ok=True)
    png = assets / 'eye-cursor.png'
    subprocess.run(['swift', '-module-cache-path', str(cache),
                    str(assets / 'render.swift'), str(assets / 'eye-cursor.svg'),
                    str(png)], check=True, timeout=60)
    # WebKit snapshots may be at Retina resolution; normalize the master.
    subprocess.run(['sips', '-z', '1024', '1024', str(png)], check=True, stdout=subprocess.DEVNULL)
    with tempfile.TemporaryDirectory(prefix='eyecursor-icon-') as folder:
        iconset = Path(folder) / 'EyeCursor.iconset'
        iconset.mkdir()
        for points in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                pixels = points * scale
                suffix = '@2x' if scale == 2 else ''
                target = iconset / f'icon_{points}x{points}{suffix}.png'
                subprocess.run(['sips', '-z', str(pixels), str(pixels), str(png),
                                '--out', str(target)], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(['iconutil', '-c', 'icns', str(iconset),
                        '-o', str(assets / 'EyeCursor.icns')], check=True)
    print('Built eye-cursor.png and EyeCursor.icns')


if __name__ == '__main__':
    main()
