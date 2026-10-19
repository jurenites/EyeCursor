"""Exercise the real native controller with synthetic states; no camera access."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'native_calibration.swift').read_text().split('let arguments = Array(CommandLine.arguments')[0]
with tempfile.TemporaryDirectory(prefix='eyecursor-lifecycle-') as folder:
    folder = Path(folder)
    main = folder / 'main.swift'
    main.write_text(source + (Path(__file__).with_name('lifecycle.swift')).read_text())
    binary = folder / 'test'
    subprocess.run(['/usr/bin/swiftc', '-module-cache-path', str(root.parent / '.venv/swift-cache'),
                    str(root / 'gaze_motion.swift'), str(root / 'angle_debugger.swift'), str(main), '-o', str(binary)], check=True)
    result = subprocess.run([str(binary)], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('Native lifecycle failed:\n' + result.stdout + result.stderr)
    if 'Native lifecycle passed:' not in result.stdout:
        raise RuntimeError('Native test exited before its assertions completed: ' + result.stderr)
    print(result.stdout, end='')
