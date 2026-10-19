"""Fetch the pinned Google Face Landmarker model for local-only webcam tracking."""
import hashlib
from pathlib import Path
import urllib.request

URL = 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task'
SHA256 = '64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff'
DESTINATION = Path(__file__).resolve().parents[1] / '.venv/models/face_landmarker.task'


def main():
    if DESTINATION.is_file() and hashlib.sha256(DESTINATION.read_bytes()).hexdigest() == SHA256:
        print(f'Face model ready: {DESTINATION}')
        return
    with urllib.request.urlopen(URL, timeout=60) as response:
        data = response.read(10_000_000)
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise SystemExit('Face model checksum did not match; nothing installed')
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    temporary = DESTINATION.with_suffix('.download')
    temporary.write_bytes(data)
    temporary.replace(DESTINATION)
    print(f'Face model ready: {DESTINATION}')


if __name__ == '__main__': main()
