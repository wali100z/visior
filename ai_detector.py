# -*- coding: utf-8 -*-
import sys
import os
import json
import time
import subprocess

sys.stdout.reconfigure(encoding="utf-8")

TWELVELABS_API_KEY = os.environ.get("TWELVELABS_API_KEY", "")
CLIPS_OUTPUT_DIR   = "clips"
MAX_CLIP_SEC       = 60
PRE_ROLL_SEC       = 5


def download_veo(url, output_path="match.mp4"):
    print("[DOWNLOAD] Downloading match...", flush=True)
    subprocess.run([
        "yt-dlp", "-f", "standard-1080p",
        "-o", output_path,
        "--quiet", "--no-warnings",
        url
    ], check=True)
    print("[DOWNLOAD] Done!", flush=True)
    return output_path


def get_or_create_index(client):
    indexes = list(client.indexes.list())

    for idx in indexes:
        idx_name = getattr(idx, "index_name", None) or getattr(idx, "name", None)
        if idx_name == "visior-matches":
            idx_id = getattr(idx, "index_id", None) or getattr(idx, "id", None)
            print(f"[TL] Using index: {idx_id}", flush=True)
            return idx_id

    idx = client.indexes.create(
        index_name="visior-matches",
        models=[{"name": "marengo2.7", "options": ["visual"]}]
    )
    idx_id = getattr(idx, "index_id", None) or getattr(idx, "id", None)
    print(f"[TL] Created index: {idx_id}", flush=True)
    return idx_id


def upload_and_index(client, index_id, video_path):
    print("[TL] Uploading video...", flush=True)
    task = client.tasks.create(index_id=index_id, file=video_path)
    print(f"[TL] Task: {task.id} — waiting for indexing...", flush=True)

    while True:
        task = client.tasks.retrieve(task.id)
        print(f"[TL] Status: {task.status}", flush=True)
        if task.status == "ready":
            print(f"[TL] Indexed! Video: {task.video_id}", flush=True)
            return task.video_id
        elif task.status == "failed":
            raise RuntimeError("Twelve Labs indexing failed")
        time.sleep(10)


def search_player(client, index_id, video_id, shirt_number, jersey_color):
    query = f"player wearing {jersey_color} jersey with number {shirt_number}"
    print(f"[TL] Searching: {query}", flush=True)

    results = client.search.query(
        index_id=index_id,
        query_text=query,
        options=["visual"],
        filter={"id": [video_id]},
        threshold="medium",
        page_limit=50
    )

    clips = []
    for item in results.data:
        clips.append({"start": item.start, "end": item.end})

    print(f"[TL] Found {len(clips)} moments", flush=True)
    return clips


def merge_clips(clips):
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
        cs = max(0, s - PRE_ROLL_SEC)
        ce = min(e + 3, cs + MAX_CLIP_SEC)
        final.append([round(cs, 2), round(ce, 2)])
    return final


def cut_clips(video_path, segments):
    os.makedirs(CLIPS_OUTPUT_DIR, exist_ok=True)
    clip_paths = []
    print(f"[CUT] Cutting {len(segments)} clips...", flush=True)
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
        print(f"[CUT] Clip {i+1} done", flush=True)
    return clip_paths


def run_return_dict(input_path, shirt_number, jersey_color):
    from twelvelabs import TwelveLabs

    print(f"[VISIOR] Player #{shirt_number} | {jersey_color} jersey", flush=True)
    print(f"[TL] API key length: {len(TWELVELABS_API_KEY)}", flush=True)

    client   = TwelveLabs(api_key=TWELVELABS_API_KEY)
    index_id = get_or_create_index(client)
    video_id = upload_and_index(client, index_id, input_path)
    clips    = search_player(client, index_id, video_id, shirt_number, jersey_color)

    if not clips:
        print("[ERROR] No moments found.", flush=True)
        return {
            "success": False,
            "clips": [],
            "segments": [],
            "player": {"shirtNumber": shirt_number, "jerseyColor": jersey_color}
        }

    segments   = merge_clips(clips)
    clip_paths = cut_clips(input_path, segments)

    print(f"[DONE] {len(clip_paths)} clips ready!", flush=True)
    return {
        "success": True,
        "clips": clip_paths,
        "segments": segments,
        "player": {"shirtNumber": shirt_number, "jerseyColor": jersey_color}
    }
