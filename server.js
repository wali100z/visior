process.on("uncaughtException", function(err) {
  console.error("[UNCAUGHT]", err.message);
});
process.on("unhandledRejection", function(err) {
  console.error("[UNHANDLED]", err);
});

const express = require("express");
const cors    = require("cors");
const path    = require("path");
const fs      = require("fs");
const { execFile } = require("child_process");

const app = express();
app.use(cors());
app.use(express.json());

app.use(express.static(path.join(__dirname, "public")));
app.use("/clips", express.static(path.join(__dirname, "clips")));

const jobs = {};

function runModal(jobId, veoLink, shirtNumber, jerseyColor) {
  jobs[jobId] = { status: "processing", clips: [], error: null, step: "Starting..." };

  const script = path.join(__dirname, "run_modal.py");

  const py = require("child_process").spawn(
    process.env.PYTHON_PATH || "python3",
    [script, veoLink, shirtNumber, jerseyColor],
    { env: Object.assign({}, process.env) }
  );

  let output = "";
  let errorOutput = "";

  py.stdout.on("data", function(data) {
    const text = data.toString();
    output += text;
    process.stdout.write(text);
    if (text.includes("[DOWNLOAD]"))  jobs[jobId].step = "Downloading match video...";
    if (text.includes("[FRAMES]"))    jobs[jobId].step = "Extracting frames...";
    if (text.includes("[SCAN]"))      jobs[jobId].step = "Scanning for player...";
    if (text.includes("[CUT]"))       jobs[jobId].step = "Cutting your clips...";
    if (text.includes("[DONE]"))      jobs[jobId].step = "Done!";
  });

  py.stderr.on("data", function(data) {
    errorOutput += data.toString();
  });

  py.on("error", function(err) {
    jobs[jobId].status = "error";
    jobs[jobId].error  = "Could not start python: " + err.message;
  });

  py.on("close", function(code) {
    if (code !== 0) {
      jobs[jobId].status = "error";
      jobs[jobId].error  = errorOutput || "Processing failed";
      return;
    }

    const lines   = output.split("\n");
    const jsonLine = lines.find(l => l.startsWith("JSON_RESULT:"));

    if (!jsonLine) {
      jobs[jobId].status = "error";
      jobs[jobId].error  = "No result from processor";
      return;
    }

    try {
      const result = JSON.parse(jsonLine.replace("JSON_RESULT:", ""));
      jobs[jobId].status   = "done";
      jobs[jobId].clips    = result.clips || [];
      jobs[jobId].segments = result.segments || [];
      jobs[jobId].player   = result.player;
      console.log("[DONE] Job " + jobId + " — " + jobs[jobId].clips.length + " clips");
    } catch(e) {
      jobs[jobId].status = "error";
      jobs[jobId].error  = "Parse error: " + e.message;
    }
  });
}

// ROUTE: Submit job
app.post("/api/find-player", function(req, res) {
  const { veoLink, shirtNumber, jerseyColor } = req.body;
  if (!veoLink || !shirtNumber || !jerseyColor) {
    return res.status(400).json({ error: "Missing fields" });
  }
  const jobId = Date.now().toString();
  console.log("\n[JOB " + jobId + "] Player #" + shirtNumber + " (" + jerseyColor + ")");
  runModal(jobId, veoLink, shirtNumber, jerseyColor);
  res.json({ success: true, jobId });
});

// ROUTE: Job status
app.get("/api/status/:jobId", function(req, res) {
  const job = jobs[req.params.jobId];
  if (!job) return res.status(404).json({ error: "Job not found" });
  res.json(job);
});

// ROUTE: List clips
app.get("/api/clips-list", function(req, res) {
  const clipsDir = path.join(__dirname, "clips");
  if (!fs.existsSync(clipsDir)) return res.json({ clips: [] });
  const files = fs.readdirSync(clipsDir).filter(f => f.endsWith(".mp4"));
  res.json({ clips: files.map(f => "/clips/" + f) });
});

const PORT = process.env.PORT || 3001;
app.listen(PORT, function() {
  console.log("\n[VISIOR] Running on http://localhost:" + PORT + "\n");
});