# -*- coding: utf-8 -*-
import modal
import os

app = modal.App("visior")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg", "libgl1", "libglib2.0-0")
    .pip_install("opencv-python-headless", "numpy", "yt-dlp")
)

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


@app.function(image=image, timeout=600, cpu=4)
def process_match(veo_url: str, shirt_number: str, jersey_color: str):
    import cv2
    import numpy as np
    import subprocess
    import glob
    import shutil
    import json

    FRAMES_DIR       = "/tmp/frames"
    CLIPS_DIR        = "/tmp/clips"
    VIDEO_PATH       = "/tmp/match.mp4"
    FRAME_INTERVAL   = 2
    MAX_CLIP_SEC     = 60
    PRE_ROLL_SEC     = 5
    MIN_CLIP_GAP_SEC = 8

    # Clean up
    shutil.rmtree(FRAMES_DIR, ignore_errors=True)
    shutil.rmtree(CLIPS_DIR, ignore_errors=True)
    os.makedirs(FRAMES_DIR, exist_ok=True)
    os.makedirs(CLIPS_DIR, exist_ok=True)

    # 1. Download
    print(f"[DOWNLOAD] Downloading match...", flush=True)
    subprocess.run([
        "yt-dlp", "-f", "standard-1080p",
        "-o", VIDEO_PATH,
        "--quiet", "--no-warnings", veo_url
    ], check=True)
    print("[DOWNLOAD] Done!", flush=True)

    # 2. Extract frames
    print(f"[FRAMES] Extracting 1 frame every {FRAME_INTERVAL}s...", flush=True)
    subprocess.run([
        "ffmpeg", "-y", "-i", VIDEO_PATH,
        "-vf", f"fps=1/{FRAME_INTERVAL},scale=320:180",
        "-q:v", "5",
        f"{FRAMES_DIR}/frame_%06d.jpg",
        "-loglevel", "error"
    ], check=True)
    frames = sorted(glob.glob(f"{FRAMES_DIR}/frame_*.jpg"))
    print(f"[FRAMES] {len(frames)} frames extracted", flush=True)

    # 3. Detect player
    color = jersey_color.lower().strip()
    if color not in COLOR_RANGES:
        for key in COLOR_RANGES:
            if color in key or key in color:
                color = key
                break
        else:
            color = "blue"

    low  = np.array(COLOR_RANGES[color][0], dtype=np.uint8)
    high = np.array(COLOR_RANGES[color][1], dtype=np.uint8)

    print(f"[SCAN] Scanning for {color} jersey...", flush=True)
    timestamps = []

    for i, frame_path in enumerate(frames):
        img = cv2.imread(frame_path)
        if img is None:
            continue
        h, w = img.shape[:2]
        roi  = img[int(h*0.15):int(h*0.85), int(w*0.05):int(w*0.95)]
        hsv  = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, low, high)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            if cv2.contourArea(cnt) > 150:
                x, y, cw, ch = cv2.boundingRect(cnt)
                if 0.6 < ch / max(cw, 1) < 4.0:
                    timestamps.append(float(i * FRAME_INTERVAL))
                    break

        if i % 100 == 0:
            print(f"[SCAN] {int(i/max(len(frames),1)*100)}% done...", flush=True)

    print(f"[SCAN] {len(timestamps)} moments found", flush=True)

    if not timestamps:
        return {"success": False, "clips": [], "segments": [], "player": {"shirtNumber": shirt_number, "jerseyColor": jersey_color}}

    # 4. Merge timestamps
    segments = []
    start = timestamps[0]
    end   = timestamps[0]
    for ts in timestamps[1:]:
        if ts - end <= MIN_CLIP_GAP_SEC:
            end = ts
            if end - start >= MAX_CLIP_SEC:
                segments.append([start, end])
                start = ts; end = ts
        else:
            segments.append([start, end])
            start = ts; end = ts
    segments.append([start, end])

    final = []
    for s, e in segments:
        cs = max(0, s - PRE_ROLL_SEC)
        ce = min(e + 3, cs + MAX_CLIP_SEC)
        final.append([round(cs, 2), round(ce, 2)])

    # 5. Cut clips
    print(f"[CUT] Cutting {len(final)} clips...", flush=True)
    clip_paths = []
    for i, (s, e) in enumerate(final):
        out = f"{CLIPS_DIR}/clip_{i+1:02d}.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-ss", str(s), "-i", VIDEO_PATH,
            "-t", str(e - s),
            "-vf", "scale=-1:1920,crop=1080:1920",
            "-c:v", "libx264", "-preset", "fast", "-crf", "26",
            "-c:a", "aac", "-movflags", "+faststart",
            "-loglevel", "error", out
        ], check=True)
        clip_paths.append(out)
        print(f"[CUT] Clip {i+1} done", flush=True)

    # 6. Read clips as bytes to return
    clips_data = {}
    for path in clip_paths:
        with open(path, "rb") as f:
            clips_data[os.path.basename(path)] = f.read()

    print(f"[DONE] {len(clip_paths)} clips ready!", flush=True)
    return {
        "success": True,
        "clips_data": clips_data,
        "segments": final,
        "player": {"shirtNumber": shirt_number, "jerseyColor": jersey_color}
    }