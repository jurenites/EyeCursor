"""Monotonic local release numbers, shared by every checkout-building chat."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
from pathlib import Path
import re


def source_digest(root):
    root = Path(root)
    files = [root / name for name in ('README.md', 'AGENTS.md')]
    for directory in ('3DTracker', 'assets'):
        files.extend(p for p in (root / directory).rglob('*')
                     if p.is_file() and not any(part.startswith('.') or part == '__pycache__'
                                               for part in p.relative_to(root).parts)
                     and p.suffix in {'.py', '.swift', '.html', '.md', '.txt', '.svg', '.png', '.icns'})
    digest = hashlib.sha256()
    for path in sorted(set(files)):
        if path.is_file():
            digest.update(str(path.relative_to(root)).encode() + b'\0')
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


@contextmanager
def versioned_build(root):
    """Reserve a version under a shared lock; publish only after a successful build."""
    root = Path(root)
    cache = root / '.venv'
    cache.mkdir(exist_ok=True)
    with (cache / 'app-version.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        manifest = root / 'version.json'
        previous = json.loads(manifest.read_text()) if manifest.exists() else None
        signature = source_digest(root)
        if previous:
            if not re.fullmatch(r'0\.[1-9][0-9]*', previous['version']):
                raise ValueError('version.json must contain a version such as 0.1 or 0.10')
            minor = int(previous['version'].split('.')[1])
            version = previous['version'] if previous['source_sha256'] == signature else f'0.{minor + 1}'
        else:
            version = '0.1'
        yield version
        if source_digest(root) != signature:
            raise RuntimeError('Project files changed during the build. Build again before installing.')
        data = {'version': version, 'source_sha256': signature}
        temporary = cache / 'version-next.json'
        temporary.write_text(json.dumps(data, indent=2) + '\n')
        temporary.replace(manifest)

