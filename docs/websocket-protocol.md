# Streaming protocol v1

## Telemetry

`/api/v1/sessions/{id}/events` sends JSON. Initial `session.state` is a snapshot.
Subsequent events include `schema_version`, `type`, `sequence`, `session_id`,
`frame_id`, `config_revision`, UTC `timestamp`, and `payload`.

Events: `session.state`, `inspection.completed`, `verification.completed`,
`reference.invalidated`, `config.applied`, `job.failed`, `source.disconnected`.
Completion payloads contain resource IDs; fetch their immutable REST records.
Heartbeat messages contain current session state. They use the compact
`{type, sequence, payload}` envelope, as does connection state recovery.

Sequence numbers are process-local, not durable offsets. Reconnection starts
from the current state; REST history/jobs are the durable recovery mechanism.
Do not apply inspection results from a superseded configuration or session.

## Binary JPEG frames

`/api/v1/sessions/{id}/frames?view=rgb|depth|annotated` sends binary messages:

1. Four-byte unsigned big-endian JSON-header length.
2. UTF-8 JSON header: schema version, frame ID, width, height, configuration revision,
   and `pinned` flag.
3. JPEG bytes for exactly that frame.

Annotated previews are pinned inspection snapshots. Raw RGB/depth previews follow
the latest available source frame. Depth preview is unavailable for RGB-only files.

## HTTP MJPEG alternative

`/api/v1/sessions/{id}/stream.mjpg?view=rgb|depth|annotated` uses
`multipart/x-mixed-replace; boundary=frame`, JPEG parts, Content-Length and
X-Frame-Id. This is ordinary HTTP MJPEG, not MJPEG embedded in WebSocket JSON.

Each viewer pulls latest data at the configured stream rate. There is no unbounded
per-viewer queue. Source disconnect clears live data; it does not manufacture a
replacement or silently treat the last image as a fresh capture.
