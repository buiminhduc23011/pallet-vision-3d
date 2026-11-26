# Pallet Vision implementation

Approved architecture: local Windows workstation; FastAPI + shared real-input
vision pipeline, React/TypeScript HMI, SQLite audit trail. No synthetic inputs.

Sequence:
1. Schemas, configuration, process bootstrap and QC contract tests.
2. Real RGB/RGB-D/bag ingestion and source abstraction.
3. Classifier, alignment, detector adapters, depth fusion, calibration.
4. Hungarian transfer comparison and immutable reference snapshots.
5. REST, background inference, live acquisition, WebSocket/MJPEG, persistence.
6. Industrial light HMI, uploads, calibration/settings, history.
7. Automated checks and local browser smoke check.
8. Hardware/model/real-capture acceptance (requires operator inputs).

Validation boundary: automated software checks do not establish segmentation
accuracy, millimeter accuracy, throughput, or factory deployment readiness.

## Delivery checkpoint

Implementation steps 1–6 are present. Software validation currently covers 46
passing automated checks, production HMI build, and local browser startup/settings.
Step 8 remains an explicit operator acceptance gate: no camera/model/pallet capture
was supplied. Remote deployment is pending a target and network access model.

Teach Setup extension: four-corner datum, image-space search region, following
material/roll regions, floor/material sampling controls, immutable recipes,
frame-bound manual origin confirmation and taught-alignment verdict gating.
See `teaching.md` for operation and explicit validation limits.
