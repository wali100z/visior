# -*- coding: utf-8 -*-
import sys
import os
import json

sys.stdout.reconfigure(encoding="utf-8")

def main():
    if len(sys.argv) < 4:
        print("Usage: python3 run_modal.py <veo_url> <shirt> <color>")
        sys.exit(1)

    veo_url      = sys.argv[1]
    shirt_number = sys.argv[2]
    jersey_color = sys.argv[3]

    import modal
    f = modal.Function.lookup("visior", "process_match")
    result = f.remote(veo_url, shirt_number, jersey_color)

    # Save clips to local clips/ folder
    clips_dir = os.path.join(os.path.dirname(__file__), "clips")
    os.makedirs(clips_dir, exist_ok=True)

    clip_urls = []
    if result.get("clips_data"):
        for filename, data in result["clips_data"].items():
            out_path = os.path.join(clips_dir, filename)
            with open(out_path, "wb") as f_out:
                f_out.write(data)
            clip_urls.append("/clips/" + filename)

    output = {
        "success": result.get("success", False),
        "clips": clip_urls,
        "segments": result.get("segments", []),
        "player": result.get("player", {})
    }

    print("JSON_RESULT:" + json.dumps(output))

if __name__ == "__main__":
    main()