# Acceptance gates

## Automated software gate

Run pytest, Ruff and the frontend production build. These include numerical
contract tests, not fake camera/image inputs:

- Empty reference is INCOMPLETE, missing current rolls fail count checks.
- Wrong size/orientation, far-away unmatched rolls and incompatible units.
- Intrinsics deprojection and translation/rotation normalization.
- Invalid HSV/ROI/calibration configuration; ETag conflict and persisted settings.
- No-frame capture rejection; missing models and unknown references.
- Upload rejection/cleanup, chunked limits, origin/host boundaries, model traversal.
- Idempotent POSTs, bounded history, worker error persistence and WebSocket state.

## Real-input gate — NOT YET RUN

Requires operator-supplied images, aligned RGB-D pairs, bag recordings, trusted
model weights and a physical camera. No replacement images are generated.

1. For wood/plastic/unknown pallets, compare outputs with labeled real captures.
2. Validate RGB-D scale and floor height with known physical measurements at
   multiple positions/depths. Establish acceptable residual and measurement errors.
3. Capture paired old/new pallets with missing, extra, shifted, rotated, differently
   sized and standing/lying rolls; include touching rolls and shrink-wrap holes.
4. Validate reference local-frame invariance under permitted pallet movement.
5. Verify every missing overlay aligns with its expected location on the target.
6. Confirm PNG/NPY and captured live frames yield equivalent inspection results.
7. Exercise bag EOF, pause, seek, camera disconnect/reconnect and invalid profiles.
8. Measure CPU/GPU inference latency, dropped preview frames and memory during a
   sustained production-like soak. Configure the continuous interval accordingly.
9. Test storage exhaustion, backups/restores, power loss and operator recovery.
10. Confirm model/license suitability and sign off the measured false-pass rate.

This release must not be used as an unattended safety interlock. A software build
or unit-test result is not evidence of vision accuracy.
