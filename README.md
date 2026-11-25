# Pallet Vision

Local RGB-D pallet inspection workstation: React/TypeScript industrial HMI,
FastAPI vision engine, real image/RealSense sources, and a SQLite audit trail.

**Release status:** implementation for local integration and validation, not an
accuracy-certified factory release. No mock cameras, generated inspection images,
fake measurements, bundled model weights, or pre-populated history.

## Run on Windows

Requires Python **3.13** for the supplied dependency lock and Node **22.12+**.
The Python project supports 3.10+ with separately resolved compatible packages.

From a PowerShell terminal at the repository root:

```powershell
./scripts/setup.ps1
./scripts/start.ps1
```

Open **http://127.0.0.1:8000**. API documentation is at **/docs** and health at
**/api/v1/health**. The built HMI is served by the Python process; there is no
separate frontend server in this mode. Close with Ctrl+C.

For a hidden local background process:

```powershell
./scripts/start.ps1 -Background
```

The command prints the process ID, stop command, and local address. This does not
install a Windows service, open a firewall port, or publish the app on the internet.

Optional integrations:

```powershell
./scripts/setup.ps1 -Vision -Camera
```

These install Ultralytics/PyTorch and the RealSense SDK. Install only the extras
you need. Camera/accelerator wheel compatibility depends on your Python version,
OS and GPU; core Offline mode starts without these integrations.

## First inspection

1. Choose **Image check → Single image** and load a real JPEG or PNG.
2. Draw a target ROI that contains the entire visible pallet, with margin.
3. Open **Settings** to tune HSV bands, contour extraction and tolerances.
4. Install a trusted FastSAM checkpoint in the model directory and set its relative
   model path, or choose a custom YOLO segmentation checkpoint/OpenVINO export.
5. Load the **Reference image** of the old pallet. Reference capture requires valid
   pallet geometry and segmented rolls; missing prerequisites are reported.
6. Load the **Target image**. Transfer matching compares count, local position,
   visible size and standing/lying orientation. Every verification is stored.

Without a detector model, RGB material/alignment estimates remain available but
transfer QC is **INCOMPLETE**, never silently PASS. HSV confidence is a heuristic
score, not a calibrated probability of correctness.

Settings auto-save and re-run the active offline image and captured reference.
Previous reference/result revisions remain immutable. Reset clears working
selections, not saved images or inspection history.

## RGB-D, recordings and live camera

An RGB-D upload requires three files: RGB JPEG/PNG, aligned depth (16-bit PNG or
numeric NPY), and metadata JSON. See [calibration guidance](docs/calibration.md)
for the schema and measurement assumptions. Do not substitute arbitrary depth
units or resized/unregistered depth images.

A RealSense `.bag` must contain both color and depth. Playback opens paused;
play/pause, rewind and **Inspect current frame** select the evidence to inspect.
The same vision pipeline processes all real sources.

In Live camera mode, color/depth are aligned by the SDK. **Capture & save frame**
saves lossless RGB, raw depth and metadata for later inspection. A disconnect
clears the live frame and stops continuous verification instead of reusing stale
camera data. Continuous checking requires a valid reference.

## Data and configuration

- `config.json` persists validated settings. Missing sections use schema defaults;
  the first UI save writes the full configuration. All thresholds are exposed through
  the settings controls or Advanced JSON. `config.schema.json` describes them.
- Local runtime data lives in `data/`: SQLite, uploads, captures, masks, reference
  evidence and verification overlays. It is excluded from Git.
- Model files live in `models/` and are excluded from Git. No model is downloaded
  automatically. Only load checkpoints from trusted sources; `.pt` is executable
  model content. Review licensing for the chosen model and deployment.
- Captures are retained until the operator archives them. The engine stops new
  writes near the configured free-disk reserve. There is no automatic deletion.

Back up the configuration, model files and the complete data directory with the
server stopped. Restoring only SQLite without its image files loses evidence.

## Development and verification

```powershell
./.venv/Scripts/python.exe -m pytest backend/tests -q
./.venv/Scripts/python.exe -m ruff check backend
npm run build --prefix frontend
./.venv/Scripts/python.exe scripts/export_contracts.py
```

For frontend development, run the API and `npm run dev --prefix frontend`; Vite
proxies HTTP/WebSocket API calls to the local Python service.

The software tests exercise configuration, geometry/matching, API errors,
idempotency, persistence and local-boundary protections. They do **not** establish
model accuracy, RealSense stability or dimensional accuracy. See the
[acceptance checklist](docs/acceptance-tests.md) before factory use.

## Deployment boundary

The supported current deployment is **one trusted local workstation / one camera**.
Keep one Uvicorn worker because it owns the camera and model. Do not bind directly
to a LAN/public address: user authentication, multi-tenant isolation, TLS and
remote operational controls are not implemented. A static-only host cannot run
the Python vision engine or access the workstation's USB camera.

See [design](docs/DESIGN.md), [WebSocket protocol](docs/websocket-protocol.md),
[security review](docs/SECURITY_REVIEW.md) and [release status](docs/RELEASE_STATUS.md).
