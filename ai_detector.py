# -*- coding: utf-8 -*-
import sys
import cv2
import numpy as np
import subprocess
import os
import json
import multiprocessing as mp

sys.stdout.reconfigure(encoding="utf-8")

# ── CONFIG ──────────────────────────────────────────────
CLIPS_OUTPUT_DIR  = "clips"
FRAME_SKIP        = 45        # check every 45th frame (~every 1.8s at 25fps)
PRE_ROLL_SEC      = 5
MAX_CLIP_SEC      = 60
MIN_CLIP_GAP_SEC  = 8
NUM_WORKERS       = max(2, mp.cpu_count() - 1)  # use all cores except 1
# ────────────────────────────────────────────────────────

COLOR_RANGES = {
    "white":      [(0,   0,  200), (180, 30, 255)],
    "black":      [(0,   0,    0), (180, 60,  50)],
    "red":        [(0,  120,  80), (10,  255, 255)],
    "blue":       [(100, 80,  80), (130, 255, 255)],
    "navy":       [(100, 80,  30), (125, 255, 120)],
    "navy blue":  [(100, 80,  30), (125, 255, 120)],
    "dark blue":  [(100, 80,  30), (125, 255, 120)],
    "sky blue":   [(95,  60, 140), (115, 255, 255)],
    "light blue": [(95,  60, 140), (115, 255, 255)],
    "green":      [(40,  80,  80), (80,  255, 255)],
    "dark green": [(40,  80,  30), (75,  255, 150)],
    "light green":[(45, 60, 140), (85,  255, 255)],
    "yellow":     [(20, 120, 100), (35,  255, 255)],
    "orange":     [(10, 120, 100), (20,  255, 255)],
    "purple":     [(130, 60,  60), (160, 255, 255)],
    "pink":       [(160, 60, 100), (175, 255, 255)],
    "gray":       [(0,    0,  80), (180,  25, 180)],
    "grey":       [(0,    0,  80), (180,  25, 180)],
    "maroon":     [(0,  100,  40), (10,  255, 150)],
    "burgundy":   [(0,  100,  40), (10,  255, 150)],
    "turquoise":  [(80,  80, 100), (100, 255, 255)],
    "brown":      [(10,  80,  40), (20,  255, 150)],
}


def detect_jersey(frame, jersey_color):
    color = jersey_color.lower()
    if color not in COLOR_RANGES:
        color = "white"
    low  = np.array(COLOR_RANGES[color][0], dtype=np.uint8)
    high = np.array(COLOR_RANGES[color][1], dtype=np.uint8)

    h, w = frame.shape[:2]
    roi  = frame[int(h*0.15):int(h*0.85), int(w*0.05):int(w*0.95)]
    small = cv2.resize(roi, (320, 180))
    hsv   = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    mask  = cv2.inRange(hsv, low, high)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area > 200:
            x, y, cw, ch = cv2.boundingRect(cnt)
            aspect = ch / max(cw, 1)
            if 0.7 < aspect < 3.5:
                return True
    return False


def scan_chunk(args):
    """Scan a chunk of frames — runs in parallel."""
    video_path, start_frame, end_frame, jersey_color, fps = args
    cap = cv2.VideoCapture(video_path)
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

    timestamps = []
    frame_idx  = start_frame

    while frame_idx < end_frame:
        ret, frame = cap.read()
        if not ret:
            break
        if (frame_idx - start_frame) % FRAME_SKIP == 0:
            ts = frame_idx / fps
            if detect_jersey(frame, jersey_color):
                timestamps.append(round(ts, 2))
        frame_idx += 1

    cap.release()
    return timestamps


def find_player_timestamps(video_path, jersey_color):
    print(f"[SCAN] Opening video...", flush=True)
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open: {video_path}")

    fps          = cap.get(cv2.CAP_PROP_FPS) or 25
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()

    print(f"[SCAN] {int(total_frames/fps/60)} min match | {NUM_WORKERS} workers | scanning...", flush=True)

    # Split into chunks for parallel processing
    chunk_size = total_frames // NUM_WORKERS
    chunks = []
    for i in range(NUM_WORKERS):
        s = i * chunk_size
        e = s + chunk_size if i < NUM_WORKERS - 1 else total_frames
        chunks.append((video_path, s, e, jersey_color, fps))

    # Run all chunks in parallel
    with mp.Pool(NUM_WORKERS) as pool:
        results = pool.map(scan_chunk, chunks)

    # Merge and sort all timestamps
    timestamps = sorted([ts for chunk in results for ts in chunk])
    print(f"[SCAN] Done! {len(timestamps)} moments found.", flush=True)
    return timestamps, fps


def merge_timestamps(timestamps):
    if not timestamps:
        return []

    segments = []
    start = timestamps[0]
    end   = timestamps[0]

    for ts in timestamps[1:]:
        if ts - end <= MIN_CLIP_GAP_SEC:
            end = ts
            if end - start >= MAX_CLIP_SEC:
                segments.append([start, end])
                start = ts
                end   = ts
        else:
            segments.append([start, end])
            start = ts
            end   = ts

    segments.append([start, end])

    final = []
    for s, e in segments:
        clip_start = max(0, s - PRE_ROLL_SEC)
        clip_end   = min(e + 3, clip_start + MAX_CLIP_SEC)
        final.append([round(clip_start, 2), round(clip_end, 2)])

    return final


def cut_clips(video_path, segments, output_dir=CLIPS_OUTPUT_DIR):
    os.makedirs(output_dir, exist_ok=True)
    clip_paths = []

    print(f"[CUT] Cutting {len(segments)} clips in TikTok 9:16 format...", flush=True)

    for i, (start, end) in enumerate(segments):
        duration = end - start
        out_path = os.path.join(output_dir, f"clip_{i+1:02d}.mp4")

        subprocess.run([
            "ffmpeg", "-y",
            "-ss", str(start),
            "-i", video_path,
            "-t", str(duration),
            "-vf", "scale=-1:1920,crop=1080:1920",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "26",
            "-c:a", "aac",
            "-movflags", "+faststart",
            "-loglevel", "error",
            out_path
        ], check=True)

        clip_paths.append(out_path)
        print(f"[CUT] Clip {i+1}: {int(start//60)}:{int(start%60):02d} - {int(end//60)}:{int(end%60):02d}", flush=True)

    return clip_paths


def download_veo(url, output_path="match.mp4"):
    print(f"[DOWNLOAD] Downloading match...", flush=True)
    subprocess.run([
        "yt-dlp", "-f", "standard-1080p",
        "-o", output_path,
        "--quiet", "--no-warnings",
        url
    ], check=True)
    print(f"[DOWNLOAD] Done!", flush=True)
    return output_path


def run(input_path, shirt_number, jersey_color):
    print(f"[VISIOR] Player #{shirt_number} | {jersey_color} jersey", flush=True)

    timestamps, fps = find_player_timestamps(input_path, jersey_color)

    if not timestamps:
        print("[ERROR] No moments found.", flush=True)
        result = {
            "success": False, "clips": [], "segments": [],
            "player": {"shirtNumber": shirt_number, "jerseyColor": jersey_color}
        }
        print("JSON_RESULT:" + json.dumps(result))
        return

    segments   = merge_timestamps(timestamps)
    clip_paths = cut_clips(input_path, segments)

    print(f"[DONE] {len(clip_paths)} clips ready!", flush=True)

    result = {
        "success": True,
        "clips": clip_paths,
        "segments": segments,
        "player": {"shirtNumber": shirt_number, "jerseyColor": jersey_color}
    }
    print("JSON_RESULT:" + json.dumps(result))


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python ai_detector.py <veo_link_or_path> <shirt_number> <jersey_color>")
        sys.exit(1)

    input_path = sys.argv[1]
    if input_path.startswith("http"):
        input_path = download_veo(input_path)

    run(input_path, sys.argv[2], sys.argv[3])