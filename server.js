const express = require("express");
const cors = require("cors");
const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");

const app = express();
app.use(cors());
app.use(express.json());

// Serve frontend and clips
app.use(express.static(path.join(__dirname, "public")));
app.use("/clips", express.static(path.join(__dirname, "clips")));

const AI_SCRIPT = path.join(__dirname, "ai_detector.py");
const jobs = {};

function runAIDetector(jobId, veoLink, shirtNumber, jerseyColor) {
  jobs[jobId] = { status: "processing", clips: [], error: null };

  const py = spawn("python3", [AI_SCRIPT, veoLink, shirtNumber, jerseyColor]);
  let output = "";
  let errorOutput = "";

  py.stdout.on("data", function(data) {
    const text = data.toString();
    output += text;
    process.stdout.write(text);
  });

  py.stderr.on("data", function(data) {
    errorOutput += data.toString();
  });

  py.on("close", function(code) {
    if (code !== 0) {
      jobs[jobId].status = "error";
      jobs[jobId].error = errorOutput;
      console.error("AI failed:", errorOutput);
      return;
    }

    const lines = output.split("\n");
    let jsonLine = null;
    for (let i = 0; i < lines.length; i++) {
      if (lines[i].startsWith("JSON_RESULT:")) {
        jsonLine = lines[i];
        break;
      }
    }

    if (!jsonLine) {
      jobs[jobId].status = "error";
      jobs[jobId].error = "No result from AI";
      return;
    }

    try {
      const result = JSON.parse(jsonLine.replace("JSON_RESULT:", ""));
      jobs[jobId].status = "done";
      jobs[jobId].clips = result.clips.map(function(p) {
        return "/clips/" + path.basename(p);
      });
      jobs[jobId].player = result.player;
      jobs[jobId].segments = result.segments;
      console.log("[DONE] Job " + jobId + " — " + jobs[jobId].clips.length + " clips ready");
    } catch(e) {
      jobs[jobId].status = "error";
      jobs[jobId].error = "Parse error: " + e.message;
    }
  });
}

// ROUTE: Submit VEO link
app.post("/api/find-player", function(req, res) {
  const veoLink = req.body.veoLink;
  const shirtNumber = req.body.shirtNumber;
  const jerseyColor = req.body.jerseyColor;

  if (!veoLink || !shirtNumber || !jerseyColor) {
    return res.status(400).json({ error: "Missing fields" });
  }

  const jobId = Date.now().toString();
  console.log("\n[JOB " + jobId + "] Player #" + shirtNumber + " (" + jerseyColor + ")");
  runAIDetector(jobId, veoLink, shirtNumber, jerseyColor);
  res.json({ success: true, jobId: jobId });
});

// ROUTE: Check job status
app.get("/api/status/:jobId", function(req, res) {
  const job = jobs[req.params.jobId];
  if (!job) return res.status(404).json({ error: "Job not found" });
  res.json(job);
});

// ROUTE: List clips
app.get("/api/clips-list", function(req, res) {
  const clipsDir = path.join(__dirname, "clips");
  if (!fs.existsSync(clipsDir)) return res.json({ clips: [] });
  const files = fs.readdirSync(clipsDir).filter(function(f) {
    return f.endsWith(".mp4");
  });
  res.json({ clips: files.map(function(f) { return "/clips/" + f; }) });
});

const PORT = 3001;
app.listen(PORT, function() {
  console.log("\n[VISIOR] Running on http://localhost:" + PORT + "\n");
});