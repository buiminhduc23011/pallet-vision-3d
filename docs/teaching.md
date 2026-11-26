# Teach setup and recipes

Teaching defines an inspection datum; it does not train FastSAM/YOLO or prove
camera accuracy. Only actual pinned inputs can be used. No sample images are
generated or bundled.

## Operator workflow

1. Mount the camera rigidly. Load an actual RGB/RGB-D image or connect live input.
   Place the correct pallet, fully visible, in its intended inspection position.
2. Open **Teach setup / Recipes**. This pins a real frame independently of model
   availability. Without input, only the recipe library is available.
3. Click four pallet corners **clockwise in the image**: physical origin O,
   the end of +X, opposite corner, then the end of +Y. Drag corners or edit pixel
   coordinates. **Cycle origin** changes the corner and axis together. The first
   edge may be the short edge; X is not forcibly assigned to the longest edge.
4. Draw a larger **Search region** around the pallet with margin. Its center is
   not the target. Moving this region does not move the taught datum.
5. Optionally draw an exposed **Material patch** and a **Roll region**, both
   inside the taught pallet. These regions are warped with the detected pallet
   pose. Keep the material patch free of goods; roll masks are excluded where
   segmentation is available. **Learn wood/plastic** samples a hue histogram
   from the pinned image; HSV thresholds still apply. It is not model training.
6. For RGB-D, select exposed floor, **Fit exposed floor**, and set the actual
   pallet support height. Never fit a floor plane to the pallet or goods.
7. Set center-position (px for RGB / mm for calibrated RGB-D), rotation, and
   pallet-size tolerances. **Validate & preview tolerances** checks geometry and
   projects the accepted center region onto the image. It is a center-position
   window, not a box that the whole pallet must fit inside. Metric preview needs
   calibration and none/Brown-Conrady projection; unsupported inverse distortion
   returns no preview rather than drawing a misleading region. Preview is hidden
   whenever its geometry/calibration/tolerances change. Size uses image-edge
   dimensions, so camera scale and perspective must remain fixed.
8. Name the recipe and **Save recipe & activate**. Recipes are immutable snapshots
   of the full configuration, including calibration, thresholds and source-frame
   identity. Saving the same name creates a new snapshot; the library is paginated.
   Activating different teaching clears the transfer reference and stops continuous
   checks. Existing snapshots/history are not deleted.
9. Inspect a pinned frame, select **Confirm origin**, then click the same physical
   O corner (or use the numbered corner buttons). For live input, switch to
   **Pinned inspection** first; pause bag playback first. Confirmation belongs to
   that exact frame, never the next live frame. Capture an aligned reference, then
   inspect/confirm the target and verify transfer.

## Direction and coordinate guarantees

- A symmetric rectangular outline cannot reveal physical 180-degree reversal.
  Default mode requires an operator to identify O on every inspected frame. A
  square pallet also needs this confirmation. An incorrect operator selection is
  not detectable without a physical marker or additional trained detector.
- Missing confirmation produces INCOMPLETE and prevents reference capture. This
  mode rejects continuous verification. Axis-only mode is an explicit opt-out for
  mechanically constrained direction; it cannot certify 180-degree orientation.
- Taught roll coordinates start at observed O, X follows O→+X, Y is its clockwise
  perpendicular. RGB roll coordinates retain canonical pallet-width normalization;
  calibrated RGB-D coordinates use mm. Alignment displacement compares centers in
  the target axes. Pixel size/angle are image-space estimates, not full 6-DoF pose.
- A taught pallet must still be detected from actual contours/depth. The drawn
  target is never substituted for detection. Candidate selection favors taught
  dimensions but is not a semantic pallet detector; similar objects/occlusion
  need real-capture validation.
- Matching rolls cannot override NG taught alignment: transfer becomes FAIL.
  Missing evidence remains INCOMPLETE. A new reference must pass taught alignment.
- Resolution, depth intrinsics and available camera serial must match. A moved
  camera with unchanged metadata cannot be automatically recognized: re-teach and
  recalibrate after any camera movement.

## API contract (local trusted workstation only)

- `POST /api/v1/teachings`: `{frame_id, config}` → 200 validated draft config,
  acceptance polygon and units. Binds dimensions/intrinsics/serial from stored
  real frame. Does not activate or save a recipe.
- `POST /api/v1/material-samples`: `{frame_id, roi, bins}` → 200 normalized hue
  histogram and sample-pixel count. Does not activate configuration.
- `POST /api/v1/recipes`: `{name, config}` → 201 immutable recipe. Teaching and
  stored real source frame required; name max 120 characters.
- `GET /api/v1/recipes?limit=25&cursor=...`: summaries plus `next_cursor`; max 100.
- `GET /api/v1/recipes/{id}`: full saved recipe.
- Activate with existing `PUT /api/v1/config` and `If-Match` revision. Stale writes
  return 412. Wrong/missing resources return 404; bad geometry/fields return 422.
  Profile mismatch returns 409. Errors use the existing `error.code/message` shape.
- `POST /api/v1/inspections` accepts optional normalized `confirmed_origin: [x,y]`.
  It is persisted with the inspection, not with the shared config. Existing stored
  reference confirmation is reused only when reprocessing that same saved frame.
- Additive v1 endpoints; existing loopback Host/Origin checks, bounded request
  bodies and POST idempotency apply. See generated `openapi.json`.

## Acceptance gate

Unit tests exercise numerical geometry/projection, verdict precedence, origin
distance, winding/duplicate rejection and transformed masks. API tests cover
missing real input, validation and recipe pagination. No test fabricates camera
input. Full teach/save/reload/inspect acceptance still requires an actual pallet
capture and installed detector weights. Use `acceptance-tests.md` on the workstation
before operational use.
