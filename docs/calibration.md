# Calibration and evidence

## Depth sidecar contract

Use the actual values from the camera profile, never the illustrative names below
as calibration values. The JSON object has these required keys:

| Key | Meaning |
| --- | --- |
| `depth_scale_m` | Meters represented by one stored depth unit |
| `aligned_to_color` | Must be `true`; the producer confirms registration |
| `intrinsics.width`, `intrinsics.height` | Aligned color/depth resolution |
| `intrinsics.fx`, `intrinsics.fy` | Focal lengths in pixels |
| `intrinsics.ppx`, `intrinsics.ppy` | Principal point in pixels |
| `intrinsics.distortion` | `none`, `brown_conrady`, or `inverse_brown_conrady` |
| `intrinsics.coeffs` | Five distortion coefficients from the camera profile |
| `camera_serial` | Optional device identity; strongly recommended |

PNG depth must be uint16; NPY may be numeric unsigned/integer/float, with no pickle,
objects, negative or non-finite samples. Holes are zero. RGB and depth dimensions
must match. EXIF orientation is deliberately ignored to preserve sensor pixel
registration; export both arrays in sensor orientation.

The Capture & Save function writes valid metadata automatically. Reuse its files
directly. Aligned data cannot be reconstructed from two unrelated images.

## Floor plane

1. Load aligned RGB-D, or inspect a live frame and switch to its pinned view.
2. Use **Floor sample** to draw a rectangle on bare floor, not on the pallet/goods.
3. In Settings, fit the floor plane. Review residual error and physical orientation.
4. Set pallet support height above that floor. Save/reprocess.

The fitted plane uses camera-space millimeters, with its unit normal pointing
toward the camera. Geometry is rejected when the profile/device conflicts with
the calibration. Recalibrate after moving the camera or changing optics/profile.

A scalar floor distance is a separate explicit mode for a camera perpendicular
to the floor. It is not a general substitute for plane fitting on a tilted camera.

## Interpreting measurements

Roll depth uses the median valid samples inside each mask, with a configured
minimum valid fraction. Floor-relative height is evaluated from the calibrated
plane. Pixel extents are projected at this representative depth: visible-extent
estimates, not certified diameter/length measurements of hidden surfaces.

Metric local X/Y use the pallet support plane and its long-axis basis. RGB-only
X/Y use a canonical pallet-local pixel frame, with canonical width set in Settings.
That scale is not millimeters. Different perspective views can invalidate a 2D
comparison. Pallet aspect checks reject large discrepancies but cannot prove
identical perspective.

The pallet axis has 180-degree symmetry; square/near-square or ROI-clipped pallets
are reported incomplete. Keep a consistent camera/pallet approach direction.
Arbitrary 180-degree transfers or square pallets need an identifiable physical
anchor/pose estimator, which is not implemented in this release.

Occluded rolls cannot be counted reliably from a single view. Shiny wrap, dark
surfaces, merged masks and severe perspective require representative real-image
validation and, often, custom YOLO training or a different camera placement.
