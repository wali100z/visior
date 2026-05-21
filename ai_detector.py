# -*- coding: utf-8 -*-
import sys
import os
import json
import time
import subprocess
import requests

sys.stdout.reconfigure(encoding="utf-8")

TWELVELABS_API_KEY = sys.argv[4] if len(sys.argv) > 4 else os.environ.get("TWELVELABS_API_KEY", "")
TWELVELABS_API     = "https://api.twelvelabs.io/v1.3"
CLIPS_OUTPUT_DIR   = "clips"
MAX_CLIP_SEC       = 60
PRE_ROLL_SEC       = 5


def get_or_create_index():
    headers = {"x-api-key": TWELVELABS_API_KEY}
    print(f"[TL] API key length: {len(TWELVELABS_API_KEY)}", flush=True)
    res = requests.get(f"{TWELVELABS_API}/indexes", headers=headers)
    print(f"[TL] Index response: {res.status_code} {res.text[:200]}", flush=True)
    indexes = res.json().get("data", [])

    for idx in indexes:
        if idx.get("name") == "visior-matches":
            print(f"[TL] Using existing index: {idx['_id']}", flush=True)
            return idx["_id"]

    res = requests.post(f"{TWELVELABS_API}/indexes", headers=headers, json={
        "name": "visior-matches",
        "models": [{"name": "marengo2.7", "options": ["visual", "conversation"]}]
    })
    idx_id = res.json()["_id"]
    print(f"[TL] Created index: {idx_id}", flush=True)
    return idx_id


def upload_video(index_id, video_path):
    """Upload video to Twelve Labs and wait for indexing."""
    headers = {"x-api-key": TWELVELABS_API_KEY}

    print(f"[TL] Uploading video to Twelve Labs...", flush=True)

    with open(video_path, "rb") as f:
        res = requests.post(
            f"{TWELVELABS_API}/tasks",
            headers=headers,
            data={"index_id": index_id},
            files={"video_file": f}
        )

    task_id = res.json().get("_id")
    if not task_id:
        raise RuntimeError(f"Upload failed: {res.text}")

    print(f"[TL] Upload started, task: {task_id}", flush=True)

    # Wait for indexing to complete
    while True:
        res    = requests.get(f"{TWELVELABS_API}/tasks/{task_id}", headers=headers)
        data   = res.json()
        status = data.get("status")
        print(f"[TL] Indexing status: {status}", flush=True)

        if status == "ready":
            video_id = data.get("video_id")
            print(f"[TL] Indexed! Video ID: {video_id}", flush=True)
            return video_id
        elif status == "failed":
            raise RuntimeError("Twelve Labs indexing failed")

        time.sleep(10)


def search_player(index_id, video_id, shirt_number, jersey_color):
    """Search for player moments using Twelve Labs."""
    headers = {"x-api-key": TWELVELABS_API_KEY, "Content-Type": "application/json"}

    query = f"player wearing {jersey_color} jersey with number {shirt_number} on their shirt"

    print(f"[TL] Searching: {query}", flush=True)

    res = requests.post(f"{TWELVELABS_API}/search", headers=headers, json={
        "index_id": index_id,
        "query": query,
        "search_options": ["visual"],
        "filter": {"id": [video_id]},
        "threshold": "medium",
        "page_limit": 50
    })

    data = res.json()
    clips = data.get("data", [])

    print(f"[TL] Found {len(clips)} moments", flush=True)
    return clips


def merge_clips(clips):
    """Merge overlapping clip segments."""
    if not clips:
        return []

    segments = sorted([(c["start"], c["end"]) for c in clips])
    merged   = [list(segments[0])]

    for start, end in segments[1:]:
        if start - merged[-1][1] <= 8:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    final = []
    for s, e in merged:
        clip_start = max(0, s - PRE_ROLL_SEC)
        clip_end   = min(e + 3, clip_start + MAX_CLIP_SEC)
        final.append([round(clip_start, 2), round(clip_end, 2)])

    return final


def cut_clips(video_path, segments):
    """Cut clips in TikTok 9:16 format."""
    os.makedirs(CLIPS_OUTPUT_DIR, exist_ok=True)
    clip_paths = []

    print(f"[CUT] Cutting {len(segments)} clips...", flush=True)

    for i, (start, end) in enumerate(segments):
        duration = end - start
        out_path = os.path.join(CLIPS_OUTPUT_DIR, f"clip_{i+1:02d}.mp4")

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

    if not TWELVELABS_API_KEY:
        raise RuntimeError("TWELVELABS_API_KEY not set")

    # 1. Get or create index
    index_id = get_or_create_index()

    # 2. Upload and index video
    video_id = upload_video(index_id, input_path)

    # 3. Search for player
    clips = search_player(index_id, video_id, shirt_number, jersey_color)

    if not clips:
        print("[ERROR] No moments found.", flush=True)
        result = {
            "success": False, "clips": [], "segments": [],
            "player": {"shirtNumber": shirt_number, "jerseyColor": jersey_color}
        }
        print("JSON_RESULT:" + json.dumps(result))
        return

    # 4. Merge segments
    segments = merge_clips(clips)

    # 5. Cut clips
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
    if len(sys.argv) < 4:
        print("Usage: python3 ai_detector.py <veo_link_or_path> <shirt_number> <jersey_color>")
        sys.exit(1)

    input_path = sys.argv[1]
    if input_path.startswith("http"):
        input_path = download_veo(input_path)

    run(input_path, sys.argv[2], sys.argv[3])