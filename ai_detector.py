# -*- coding: utf-8 -*-
import sys
import os
import json
import subprocess
import glob
import shutil

sys.stdout.reconfigure(encoding="utf-8")

CLIPS_OUTPUT_DIR = "clips"
FRAMES_DIR       = "frames"
MAX_CLIP_SEC     = 60
PRE_ROLL_SEC     = 5
MIN_CLIP_GAP_SEC = 8
FRAME_INTERVAL   = 2  # extract 1 frame every 2 seconds

COLOR_RANGES = {
    "white":      ([0,   0,   200], [180, 40,  255]),
    "black":      ([0,   0,     0], [180, 60,   50]),
    "red":        ([0,   120,  80], [10,  255, 255]),
    "blue":       ([100, 80,   80], [130, 255, 255]),
    "navy":       ([100, 80,   20], [125, 255, 130]),
    "navy blue":  ([100, 80,   20], [125, 255, 130]),
    "dark blue":  ([100, 80,   20], [125, 255, 130]),
    "sky blue":   ([95,  60,  140], [115, 255, 255]),
    "light blue": ([95,  60,  140], [115, 255, 255]),
    "green":      ([40,  80,   80], [80,  255, 255]),
    "dark green": ([40,  80,   30], [75,  255, 150]),
    "yellow":     ([20,  120, 100], [35,  255, 255]),
    "orange":     ([10,  120, 100], [20,  255, 255]),
    "purple":     ([130, 60,   60], [160, 255, 255]),
    "pink":       ([160, 60,  100], [175, 255, 255]),
    "gray":       ([0,   0,    80], [180,  25, 180]),
    "grey":       ([0,   0,    80], [180,  25, 180]),
    "maroon":     ([0,   100,  40], [10,  255, 150]),
    "turquoise":  ([80,  80,  100], [100, 255, 255]),
}


def download_veo(url, output_path="match.mp4"):
    print("[DOWNLOAD] Downloading match...", flush=True)
    subprocess.run([
        "yt-dlp", "-f", "standard-1080p",
        "-o", output_path,
        "--quiet", "--no-warnings", url
    ], check=True)
    print("[DOWNLOAD] Done!", flush=True)
    return output_path


def extract_frames(video_path):
    """Use ffmpeg to extract 1 frame every N seconds — very fast."""
    os.makedirs(FRAMES_DIR, exist_ok=True)
    print(f"[FRAMES] Extracting 1 frame every {FRAME_INTERVAL}s...", flush=True)

    subprocess.run([
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", f"fps=1/{FRAME_INTERVAL},scale=320:180",
        "-q:v", "5",
        f"{FRAMES_DIR}/frame_%06d.jpg",
        "-loglevel", "error"
    ], check=True)

    frames = sorted(glob.glob(f"{FRAMES_DIR}/frame_*.jpg"))
    print(f"[FRAMES] Extracted {len(frames)} frames", flush=True)
    return frames


def detect_color_in_image(image_path, jersey_color):
    """Check if jersey color exists in image using OpenCV."""
    import cv2
    import numpy as np

    color = jersey_color.lower().strip()
    if color not in COLOR_RANGES:
        # Try partial match
        for key in COLOR_RANGES:
            if color in key or key in color:
                color = key
                break
        else:
            color = "blue"  # fallback

    low  = COLOR_RANGES[color][0]
    high = COLOR_RANGES[color][1]

    img  = cv2.imread(image_path)
    if img is None:
        return False

    # Focus on middle of frame (ignore crowd/sidelines)
    h, w = img.shape[:2]
    roi  = img[int(h*0.15):int(h*0.85), int(w*0.05):int(w*0.95)]

    hsv  = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(
        hsv,
        __import__('numpy').array(low,  dtype=__import__('numpy').uint8),
        __import__('numpy').array(high, dtype=__import__('numpy').uint8)
    )

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area > 150:
            x, y, cw, ch = cv2.boundingRect(cnt)
            aspect = ch / max(cw, 1)
            if 0.6 < aspect < 4.0:
                return True
    return False


def scan_frames(frames, jersey_color):
    """Scan extracted frames and return timestamps where player is visible."""
    print(f"[SCAN] Scanning {len(frames)} frames for {jersey_color} jersey...", flush=True)
    timestamps = []

    for i, frame_path in enumerate(frames):
        ts = i * FRAME_INTERVAL
        if detect_color_in_image(frame_path, jersey_color):
            timestamps.append(float(ts))

        if i % 50 == 0:
            pct = int((i / max(len(frames), 1)) * 100)
            print(f"[SCAN] {pct}% done...", flush=True)

    print(f"[SCAN] Done! {len(timestamps)} moments found.", flush=True)
    return timestamps


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
        cs = max(0, s - PRE_ROLL_SEC)
        ce = min(e + 3, cs + MAX_CLIP_SEC)
        final.append([round(cs, 2), round(ce, 2)])

    return final


def cut_clips(video_path, segments):
    os.makedirs(CLIPS_OUTPUT_DIR, exist_ok=True)
    clip_paths = []
    print(f"[CUT] Cutting {len(segments)} clips in TikTok 9:16...", flush=True)

    for i, (start, end) in enumerate(segments):
        out_path = os.path.join(CLIPS_OUTPUT_DIR, f"clip_{i+1:02d}.mp4")
        subprocess.run([
            "ffmpeg", "-y",
            "-ss", str(start),
            "-i", video_path,
            "-t", str(end - start),
            "-vf", "scale=-1:1920,crop=1080:1920",
            "-c:v", "libx264", "-preset", "fast", "-crf", "26",
            "-c:a", "aac", "-movflags", "+faststart",
            "-loglevel", "error", out_path
        ], check=True)

        clip_paths.append(out_path)
        print(f"[CUT] Clip {i+1}: {int(start//60)}:{int(start%60):02d} - {int(end//60)}:{int(end%60):02d}", flush=True)

    return clip_paths


def cleanup():
    if os.path.exists(FRAMES_DIR):
        shutil.rmtree(FRAMES_DIR)
    if os.path.exists("match.mp4"):
        os.remove("match.mp4")


def run(input_path, shirt_number, jersey_color):
    print(f"[VISIOR] Player #{shirt_number} | {jersey_color} jersey", flush=True)

    frames     = extract_frames(input_path)
    timestamps = scan_frames(frames, jersey_color)

    if not timestamps:
        print("[ERROR] No moments found.", flush=True)
        cleanup()
        result = {
            "success": False, "clips": [], "segments": [],
            "player": {"shirtNumber": shirt_number, "jerseyColor": jersey_color}
        }
        print("JSON_RESULT:" + json.dumps(result))
        return

    segments   = merge_timestamps(timestamps)
    clip_paths = cut_clips(input_path, segments)
    cleanup()

    print(f"[DONE] {len(clip_paths)} clips ready!", flush=True)
    result = {
        "success": True,
        "clips": clip_paths,
        "segments": segments,
        "player": {"shirtNumber": shirt_number, "jerseyColor": jersey_color}
    }
    print("JSON_RESULT:" + json.dumps(result))


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python3 ai_detector.py <veo_link_or_path> <shirt_number> <jersey_color>")
        sys.exit(1)

    input_path = sys.argv[1]
    if input_path.startswith("http"):
        input_path = download_veo(input_path)

    run(input_path, sys.argv[2], sys.argv[3])