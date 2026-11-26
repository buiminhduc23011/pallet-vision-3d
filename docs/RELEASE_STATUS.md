# Release status

## Implemented

- Shared real-input sources, modular vision pipeline and both detector adapters.
- Local API/worker, configuration, frame capture, references, transfer matching.
- SQLite history, immutable images/masks and failure records.
- Light industrial HMI, settings/HSV controls, ROI, offline upload, live controls.
- Core software checks and local browser startup/settings checks.
- Teach Setup: four corners, origin/axes, separate search/material/roll regions,
  material histograms, floor calibration controls and tolerance preview.
- Persistent recipe library, camera-profile checks and frame-bound origin confirmation.

## Not validated / not bundled

- No actual pallet captures, .bag or model checkpoints were supplied.
- RealSense/PyTorch integrations and 3D accuracy have not been exercised on hardware.
- No trained roll model, labeled acceptance dataset or production error budget.
- No user authentication, network-hosted deployment, Windows service or installer.
- No automatic capture retention/deletion; disk reserve stops new writes.
- No automatic physical-marker recognition. Taught direction uses explicit manual
  origin confirmation; axis-only mode cannot certify 180-degree reversal.
- Teach-on-real-image and recipe save/reload with real captures remain unvalidated.

## Deployment

Git remote is configured, but no hosting/server target is configured. The local
server is for workstation integration, not a public production deployment. Choose
the target and trust model before exposing any inspection images or controls.

## Dependency note

The tested FastAPI/Starlette combination emits a TestClient deprecation notice
for httpx. Tests pass with the locked test stack; this is not an inspection error.
Optional vision/camera packages have their own platform compatibility matrix.
