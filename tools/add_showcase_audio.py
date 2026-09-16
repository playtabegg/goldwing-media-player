"""Restore a silent showcase recording's original feature audio, with verified frame alignment.

This is post-production, not live audio capture. It never reads a microphone,
desktop mixer or chat app. The film images at three times must independently
match the given disc feature and agree on its start time before anything is muxed.
Requires OpenCV and ffmpeg on the recording workstation, not in the Player.

    python tools/add_showcase_audio.py capture.mp4 feature.m2ts output.mp4 \
        --video-rect 10,107,813,611

The rectangle is the film picture in the recording, excluding UI/letterboxing.
Use a new output filename; the original recording is never replaced.
Listen and check lip sync before approving the resulting recording for posting.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
from pathlib import Path


def align(capture: Path, feature: Path, rect: tuple[int, int, int, int]) -> dict:
    import cv2

    screen = cv2.VideoCapture(str(capture))
    source = cv2.VideoCapture(str(feature))
    try:
        rate = screen.get(cv2.CAP_PROP_FPS)
        duration = screen.get(cv2.CAP_PROP_FRAME_COUNT) / rate if rate > 0 else 0
        source_rate = source.get(cv2.CAP_PROP_FPS)
        if not screen.isOpened() or not source.isOpened() or duration <= 2 or source_rate <= 0:
            raise ValueError("both inputs must be readable videos, with a capture longer than two seconds")
        x, y, width, height = rect
        if min(x, y) < 0 or min(width, height) <= 0:
            raise ValueError("invalid video rectangle")
        # Avoid opening/closing UI transitions. Three widely separated frames
        # still have to independently establish one consistent offset.
        at_times = [duration * fraction for fraction in (0.1, 0.3, 0.5, 0.7, 0.9)]
        targets = []
        wanted = [round(at * rate) for at in at_times]
        for frame_index in range(wanted[-1] + 1):
            ok, frame = screen.read()
            if not ok:
                raise ValueError("capture ended before the alignment frames")
            if frame_index not in wanted:
                continue
            if x + width > frame.shape[1] or y + height > frame.shape[0]:
                raise ValueError("video rectangle does not fit a readable capture frame")
            crop = cv2.cvtColor(frame[y:y + height, x:x + width], cv2.COLOR_BGR2GRAY)
            targets.append(cv2.resize(crop, (160, 120)))
        best = [(-1.0, 0.0)] * len(targets)
        index = 0
        while True:
            ok, frame = source.read()
            if not ok:
                break
            small = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (160, 120))
            at = index / source_rate
            for i, target in enumerate(targets):
                score = float(cv2.matchTemplate(small, target, cv2.TM_CCOEFF_NORMED)[0, 0])
                if score > best[i][0]:
                    best[i] = score, at
            index += 1
        offsets = [source_at - capture_at for (_, source_at), capture_at in zip(best, at_times, strict=True)]
        # A static title card can match many source frames equally well. It
        # cannot establish timing by itself. Require three confident matches
        # spread across the clip to independently agree on one offset.
        confident = [i for i, (score, _) in enumerate(best) if score >= 0.92]
        groups = [
            [i for i in confident if abs(offsets[i] - offsets[anchor]) <= 0.15]
            for anchor in confident
        ]
        agreed = max(groups, key=len, default=[])
        if len(agreed) < 3 or at_times[agreed[-1]] - at_times[agreed[0]] < duration * 0.35:
            raise ValueError(f"at least three well-spaced feature frames must agree: {best}, offsets {offsets}")
        offset = statistics.median(offsets[i] for i in agreed)
        matches = [
            {"capture_seconds": at, "source_seconds": source_at, "correlation": score,
             "used_for_timing": i in agreed}
            for i, (at, (score, source_at)) in enumerate(zip(at_times, best, strict=True))
        ]
        if max(abs(offsets[i] - offset) for i in agreed) > 0.15 or offset < 0:
            raise ValueError(f"three frames do not agree on timing: {offsets}")
        return {"source_start_seconds": offset, "duration_seconds": duration, "matches": matches}
    finally:
        screen.release()
        source.release()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("feature", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--video-rect", required=True, help="x,y,width,height of the actual film picture")
    args = parser.parse_args()
    if args.output.exists() or args.output.resolve() in (args.capture.resolve(), args.feature.resolve()):
        parser.error("use a new output filename; inputs and existing outputs are never replaced")
    rect = tuple(int(value) for value in args.video_rect.split(","))
    if len(rect) != 4:
        parser.error("--video-rect needs four integers")
    proof = align(args.capture, args.feature, rect)
    offset = proof["source_start_seconds"]
    if not math.isfinite(offset):
        raise ValueError("non-finite source timing")
    audio = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=index", "-of", "json", str(args.feature)],
        check=True, capture_output=True, text=True,
    )
    if not json.loads(audio.stdout).get("streams"):
        raise ValueError("the disc feature contains no audio; no replacement soundtrack will be invented")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-n",
            "-i", str(args.capture), "-ss", f"{offset:.6f}", "-i", str(args.feature),
            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-t", f"{proof['duration_seconds']:.6f}", "-movflags", "+faststart", str(args.output),
        ],
        check=True,
    )
    proof.update({"capture": str(args.capture), "feature": str(args.feature), "output": str(args.output),
                  "audio": "original disc feature only; no desktop or microphone capture"})
    args.output.with_suffix(".audio-proof.json").write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(proof, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
