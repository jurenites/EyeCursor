"""Local screen/gaze/cursor recorder for a running monitor_demo.py calibration."""

import argparse
from bisect import bisect_left, bisect_right
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import selectors
import subprocess
import threading
import time
from urllib.request import urlopen
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
RECORDINGS = ROOT / "recordings"
HELPER = ROOT / ".venv" / "bin" / "eyetracker-screen-recorder"
PAGE = Path(__file__).with_name("session_recorder.html")
TRACKER = "http://127.0.0.1:8765/state"
SAMPLE_INTERVAL = 1 / 24
SESSION_ID = re.compile(r"^[0-9]{8}T[0-9]{6}-[0-9a-f]{8}$")
SAMPLE_HZ = 24
GROUP_SIZE = 24


def read_state():
    with urlopen(TRACKER, timeout=0.7) as response:
        return json.load(response)


def displays():
    completed = subprocess.run([str(HELPER), "--list"], capture_output=True, text=True, timeout=15)
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or "Could not list displays")
    return [json.loads(line) for line in completed.stdout.splitlines()]


def load_lines(path):
    if not path.exists():
        return []
    with path.open() as stream:
        return [json.loads(line) for line in stream if line.strip()]


def nearest_sample(samples, times, target_ms, max_distance_ms):
    if not samples:
        return None
    index = bisect_left(times, target_ms)
    candidates = [samples[position] for position in (index - 1, index)
                  if 0 <= position < len(samples)]
    nearest = min(candidates, key=lambda item: abs(item["t_ms"] - target_ms))
    return nearest if abs(nearest["t_ms"] - target_ms) <= max_distance_ms else None


def compact_tracking(manifest, gaze, frames):
    """Resample onto the video timeline and anchor every 24 coordinates in UTC."""
    gaze = sorted(gaze, key=lambda item: item["t_ms"])
    frames = sorted(frames, key=lambda item: item["t_ms"])
    gaze_times = [item["t_ms"] for item in gaze]
    frame_times = [item["t_ms"] for item in frames]
    end_ms = max(gaze_times[-1] if gaze_times else 0,
                 frame_times[-1] if frame_times else 0)
    sample_count = int(end_ms * SAMPLE_HZ / 1000) + 1 if gaze or frames else 0
    groups = []
    for first in range(0, sample_count, GROUP_SIZE):
        start_ms = first * 1000 / SAMPLE_HZ
        absolute_ns = manifest["started_at_unix_ns"] + round(start_ms * 1_000_000)
        utc = datetime.fromtimestamp(absolute_ns / 1_000_000_000, timezone.utc)
        group = {"utc": utc.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                 "video_ms": round(start_ms, 3), "gaze_xy": [], "cursor_xy": []}
        for index in range(first, min(first + GROUP_SIZE, sample_count)):
            target_ms = index * 1000 / SAMPLE_HZ
            eye = nearest_sample(gaze, gaze_times, target_ms, 75)
            group["gaze_xy"].append([round(eye["x"], 4), round(eye["y"], 4)]
                                    if eye and eye.get("valid") and eye.get("x") is not None
                                    and eye.get("y") is not None else None)
            frame_index = bisect_right(frame_times, target_ms) - 1
            cursor = frames[frame_index] if frame_index >= 0 else None
            group["cursor_xy"].append([round(cursor["cursor_nx"], 4),
                                       round(cursor["cursor_ny"], 4)]
                                      if cursor and cursor.get("cursor_on_display") else None)
        groups.append(group)
    return {"schema": "eyetracker.tracking.v2", "sample_hz": SAMPLE_HZ,
            "group_size": GROUP_SIZE, "coordinate_space": "normalized display",
            "groups": groups}


def expand_tracking(compact, manifest):
    """Decode grouped coordinates for the existing replay UI."""
    rate = compact["sample_hz"]
    gaze, frames = [], []
    for group in compact["groups"]:
        for index, (eye, cursor) in enumerate(zip(group["gaze_xy"], group["cursor_xy"])):
            time_ms = group["video_ms"] + index * 1000 / rate
            gaze.append({"t_ms": time_ms, "valid": eye is not None,
                         "x": eye[0] if eye else None, "y": eye[1] if eye else None})
            frames.append({"t_ms": time_ms, "cursor_on_display": cursor is not None,
                           "cursor_nx": cursor[0] if cursor else None,
                           "cursor_ny": cursor[1] if cursor else None})
    return {"manifest": manifest, "gaze": gaze, "frames": frames}


class SessionManager:
    def __init__(self):
        self.lock = threading.RLock()
        self.active = None

    def status(self):
        with self.lock:
            active = self.active
            return {"active": active["id"] if active else None,
                    "started_at": active["started_at"] if active else None}

    def start(self, display_id):
        with self.lock:
            if self.active:
                raise ValueError("A session is already recording")
            state = read_state()
            if not state.get("calibrated"):
                raise ValueError("Complete the four-corner eye calibration first")
            selected = next((item for item in displays() if item["id"] == display_id), None)
            if not selected:
                raise ValueError("Choose a connected display")
            session_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8]
            folder = RECORDINGS / session_id
            folder.mkdir(parents=True)
            process = subprocess.Popen([str(HELPER), "--record", str(display_id),
                                        str(folder / "screen.mp4"), str(folder / "frames.jsonl")],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True, bufsize=1)
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                ready = selector.select(timeout=15)
            if not ready:
                process.kill()
                process.wait(timeout=3)
                raise RuntimeError("Screen capture did not produce a frame within 15 seconds")
            start_line = process.stdout.readline()
            if not start_line:
                error = process.stderr.read().strip()
                process.wait(timeout=10)
                raise RuntimeError(error or "Screen capture did not start")
            started = json.loads(start_line)
            if started.get("type") != "start":
                raise RuntimeError("Screen recorder returned an invalid start event")
            manifest = {"id": session_id, "created_at": datetime.now(timezone.utc).isoformat(),
                        "display": selected, "target_fps": 24,
                        "started_at_unix_ns": started["epoch_ns"],
                        "tracker_source": state["source"], "status": "recording",
                        "coordinates": "normalized 0..1 from the selected display's top-left",
                        "time_unit": "milliseconds from first captured screen frame"}
            (folder / "session.json").write_text(json.dumps(manifest, indent=2) + "\n")
            active = {"id": session_id, "folder": folder, "process": process,
                      "started_at": manifest["created_at"], "epoch_ns": started["epoch_ns"],
                      "stop": threading.Event(), "sampler": None}
            self.active = active
            active["sampler"] = threading.Thread(target=self._sample_gaze, args=(active,), daemon=True)
            active["sampler"].start()
            return manifest

    def _sample_gaze(self, active):
        next_sample = time.monotonic()
        with (active["folder"] / "gaze.jsonl").open("w", buffering=1) as output:
            while not active["stop"].is_set():
                sampled_ns = time.time_ns()
                try:
                    state = read_state()
                    error = None
                except Exception as exc:
                    state, error = {}, str(exc)
                gaze = state.get("raw_gaze", state.get("gaze")) if state.get("valid") else None
                output.write(json.dumps({"t_ms": (sampled_ns - active["epoch_ns"]) / 1e6,
                                         "unix_ns": sampled_ns, "valid": bool(gaze),
                                         "camera_connected": state.get("camera_connected", False),
                                         "calibrated": state.get("calibrated", False),
                                         "x": gaze[0] if gaze else None,
                                         "y": gaze[1] if gaze else None,
                                         "confidence": state.get("confidence", 0),
                                         "error": error}, separators=(",", ":")) + "\n")
                next_sample += SAMPLE_INTERVAL
                active["stop"].wait(max(0, next_sample - time.monotonic()))

    def stop(self):
        with self.lock:
            active = self.active
            if not active:
                raise ValueError("No session is recording")
            active["stop"].set()
            active["sampler"].join(timeout=2)
            process = active["process"]
            process.stdin.write("stop\n")
            process.stdin.flush()
            process.stdin.close()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            errors = process.stderr.read()
            folder = active["folder"]
            manifest = json.loads((folder / "session.json").read_text())
            gaze = load_lines(folder / "gaze.jsonl")
            frames = load_lines(folder / "frames.jsonl")
            compact = compact_tracking(manifest, gaze, frames)
            manifest.update(status="complete" if process.returncode == 0 else "failed",
                            ended_at=datetime.now(timezone.utc).isoformat(),
                            duration_ms=max(0, (time.time_ns() - active["epoch_ns"]) / 1e6),
                            gaze_samples=sum(len(group["gaze_xy"]) for group in compact["groups"]),
                            raw_gaze_samples=len(gaze),
                            screen_frames=len(frames),
                            error=errors.strip() if process.returncode else None)
            (folder / "session.json").write_text(json.dumps(manifest, indent=2) + "\n")
            (folder / "tracking.json").write_text(json.dumps(compact, separators=(",", ":")) + "\n")
            self.active = None
            return manifest


def make_handler(manager, default_display_id=None):
    class Handler(BaseHTTPRequestHandler):
        def json(self, status, payload):
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def file(self, path, content_type):
            size = path.stat().st_size
            start, end = 0, size - 1
            requested = self.headers.get("Range")
            if requested:
                match = re.fullmatch(r"bytes=(\d+)-(\d*)", requested)
                if not match:
                    self.send_error(416)
                    return
                start = int(match.group(1))
                end = min(int(match.group(2)), size - 1) if match.group(2) else size - 1
                if start > end or start >= size:
                    self.send_error(416)
                    return
            self.send_response(206 if requested else 200)
            self.send_header("Content-Type", content_type)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            if requested:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            with path.open("rb") as stream:
                stream.seek(start)
                remaining = end - start + 1
                while remaining:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

        def do_GET(self):
            try:
                if self.path == "/":
                    self.file(PAGE, "text/html; charset=utf-8")
                elif self.path == "/api/displays":
                    self.json(200, displays())
                elif self.path == "/api/config":
                    self.json(200, {"default_display_id": default_display_id})
                elif self.path == "/api/status":
                    self.json(200, manager.status())
                elif self.path == "/api/sessions":
                    self.json(200, [json.loads(path.read_text()) for path in
                                    sorted(RECORDINGS.glob("*/session.json"), reverse=True)])
                else:
                    match = re.fullmatch(r"/api/sessions/([^/]+)/(data|video|manifest|tracking)", self.path)
                    if not match or not SESSION_ID.fullmatch(match.group(1)):
                        self.send_error(404)
                        return
                    folder = RECORDINGS / match.group(1)
                    kind = match.group(2)
                    if kind == "video":
                        self.file(folder / "screen.mp4", "video/mp4")
                    elif kind == "manifest":
                        self.json(200, json.loads((folder / "session.json").read_text()))
                    elif kind == "tracking":
                        self.file(folder / "tracking.json", "application/json; charset=utf-8")
                    else:
                        tracking = folder / "tracking.json"
                        if tracking.exists():
                            saved = json.loads(tracking.read_text())
                            if saved.get("schema") == "eyetracker.tracking.v2":
                                self.json(200, expand_tracking(
                                    saved, json.loads((folder / "session.json").read_text())))
                            else:
                                self.json(200, saved)
                        else:
                            self.json(200, {"manifest": json.loads((folder / "session.json").read_text()),
                                            "gaze": load_lines(folder / "gaze.jsonl"),
                                            "frames": load_lines(folder / "frames.jsonl")})
            except (OSError, RuntimeError, ValueError) as error:
                self.json(500, {"error": str(error)})

        def do_POST(self):
            try:
                if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
                    raise ValueError("Expected application/json")
                origin = self.headers.get("Origin")
                if origin and origin != f"http://127.0.0.1:{self.server.server_port}":
                    raise ValueError("Request must originate from this local recorder page")
                size = int(self.headers.get("Content-Length", "0"))
                if size > 1024:
                    raise ValueError("Request too large")
                body = json.loads(self.rfile.read(size) or b"{}")
                if self.path == "/api/start":
                    self.json(200, manager.start(int(body.get("display_id", 0))))
                elif self.path == "/api/stop":
                    self.json(200, manager.stop())
                else:
                    self.send_error(404)
            except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as error:
                self.json(400, {"error": str(error)})

        def log_message(self, format, *args):
            pass

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--default-display", type=int,
                        help="Preselect this display in the recorder page")
    args = parser.parse_args()
    if not HELPER.exists():
        raise SystemExit(f"Compile {HELPER} from 3DTracker/screen_recorder.swift first")
    RECORDINGS.mkdir(exist_ok=True)
    manager = SessionManager()
    server = ThreadingHTTPServer(("127.0.0.1", args.port),
                                 make_handler(manager, args.default_display))
    print(f"Recording and replay: http://127.0.0.1:{args.port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if manager.active:
            manager.stop()
        server.server_close()


if __name__ == "__main__":
    main()
