# Architecture and invariants

Sources implement `FrameSource.read/close` and return a `FrameBundle` with real BGR,
optional aligned depth, intrinsics/scale, immutable frame identity and timestamp.
`RealSenseSource` owns live acquisition. `FileSource` accepts static RGB/RGB-D and
delegates bag playback to the real SDK adapter. Neither generates fallback frames.

One acquisition thread owns the source; one inference worker owns the segmentation
model. The async API remains responsive. Preview queues do not retain old frames;
inspection jobs pin raw evidence to disk. Model weights are loaded lazily, only
from the trusted model directory, and fingerprinted for result provenance.

The pipeline composes calibration, pallet contour extraction, HSV/histogram
classification, segmentation, depth fusion and local-frame geometry. The transfer
module performs gated Hungarian matching with explicit unmatched assignments,
then independent position/size/orientation acceptance tests.

Missing geometry/calibration/model/depth validity cannot produce transfer PASS.
Placement `OK/NG` and transfer `PASS/FAIL` are separate checks. `INCOMPLETE` is a
first-class state, not an empty successful result. Material may be UNKNOWN even
when other checks complete.

Configuration updates validate strictly, require an ETag revision, write
atomically and schedule offline reprocessing. Reference snapshots store the full
configuration and model fingerprint. A verification requires compatible evidence.
An old reference is not silently interpreted under new thresholds.

SQLite stores typed resource records (assets, frames, inspections, references,
verifications, jobs, calibrations, media, failures), timestamps and immutable JSON
results. Large image/depth arrays remain on disk. Job rows are mutable only for
job lifecycle; interrupted jobs become failed on restart. History uses stable
cursor pagination. Persistent failures and the health endpoint support diagnostics.

REST mutations are serialized for one workstation. Resource-creating JSON POSTs
support idempotency keys. Uploads are streamed to UUID directories and validated;
upload retries may create a second asset. OpenAPI describes accepted inputs;
frontend types and websocket-protocol document result/event payloads.

The HMI uses one active session and explicit pinned results. Images and overlays
must refer to the same frame; live previews never receive a prior frame's roll
overlay. Controls do not show placeholder QC counts or synthetic camera imagery.
