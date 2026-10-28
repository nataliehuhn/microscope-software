# Projection calibration optimization report

Date: 2026-08-31  
Working copy: `D:\Chris\codex-microscope-software`  
Original source: `C:\Software\leica_microscope` (unchanged)

## Hardware and acquisition settings

- Basler camera, 4112 × 3008 pixels, uint8
- Exposure: 2.0 ms
- Reported frame rate: 29.1036 FPS
- Requested spacing: 10 µm; actual stage-quantized spacing: 9.9978 µm
- Starting/final processed XYZ: `[13290276, 7889607, 723911]` steps
- Starting/final raw XYZ: `[13290276, 9110393, 723911]` steps
- Starting/final Z speed: `8820000`

## Changes made in the copied code

- Replaced unconstrained proportional iteration with a bounded calibration solver.
- Uses real camera-burst timing rather than relying only on reported FPS.
- Repositions at maximum Z speed between calibration trials.
- Uses bracketed log interpolation once the target is enclosed.
- Escapes the acceleration-limited speed plateau with a bounded large step.
- Warm-starts compatible subsequent calibrations from a previous successful result.
- Confirms near-limit maximum-speed measurements three times and decides from their median.
- Reports `calibrated`, `max_speed_limited`, or `max_iterations` explicitly.
- Refuses fast recording after an unsuccessful or stale-geometry calibration.
- Restores Z position and speed in `finally` blocks and closes the fluorescence shutter after failures.
- Validates nonzero geometry, frame count, stage resolution, camera FPS, and Z range.

Nine offline tests cover convergence, plateau escape, warm starts, maximum-speed confirmation, physical limits, invalid geometry, recording refusal, and restoration after an injected failure.

## Performance comparison at 1 mm

| Calibration | Trials | Duration | Selected speed | Timing error |
|---|---:|---:|---:|---:|
| Previous algorithm | 8 | 56.48 s | 771844 | about 0.9% on final trial |
| Optimized algorithm | 5 | 28.41 s | 698959 | -0.79% |

The optimized control run saved valid min/max projections and index maps. Calibration time was reduced by about 50% while preserving exact hardware restoration.

## Distance sweep at 10 µm spacing

The existing stack geometry commands two additional slice intervals as run-out. For example, a requested 320 µm projection commands 339.93 µm of stage travel.

| Requested distance | Frames | Observed result |
|---:|---:|---|
| 1000 µm | 100 | Calibrated and recorded |
| 500 µm | 50 | Calibrated and recorded |
| 370 µm | 37 | Calibrated and recorded |
| 320 µm | 32 | Calibrated and recorded; final guarded smoke test passed |
| 310 µm | 31 | Calibrated and recorded at maximum Z speed |
| 300 µm | 30 | Marginal: passed one three-sample run and failed the repeat |
| 290 µm | 29 | Consistently maximum-speed limited |
| 280 µm | 28 | Maximum-speed limited |
| 250 µm | 25 | Maximum-speed limited |
| 100 µm | 10 | Maximum-speed limited |
| 50 µm | 5 | Maximum-speed limited |
| 20 µm | 2 | Maximum-speed limited |
| 10 µm | 1 | Maximum-speed limited |

For these camera settings, the short-move stopped-to-stopped floor is roughly 1.05–1.10 seconds. The camera crosses that duration around 30–31 frames. Therefore:

- **Recommended minimum with the current stopped-start technique: 320 µm.**
- 310 µm works but has little timing margin and needs maximum Z speed.
- 300 µm is not repeatably reliable.
- 290 µm and below cannot cover the full requested range at maximum camera FPS with the current technique.

Shorter reliable projections require a recording-method change, not another calibration formula: pre-accelerate the stage using lead-in distance, acquire only during the constant-velocity section, and discard lead-in/run-out frames (ideally with camera timestamps or hardware triggering).

## Key artifacts

- Optimized 1 mm manifest: `baseline_projection_20260831-172841+0200\run_manifest.json`
- Confirmed 310/320 µm boundary manifest: `projection_distance_sweep_20260831-174047+0200\sweep_manifest.json`
- Final guarded 320 µm smoke test: `projection_distance_sweep_20260831-174400+0200\sweep_manifest.json`
- Distance-sweep runner: `projection_distance_sweep.py`
- Unit tests: `tests\test_projection_calibration.py`

## Pre-accelerated projection implementation

The projection mode now uses a persistent stage velocity model instead of
calibrating every recording. The model is stored in
`leica_microscope\projection_velocity_model.json` and is validated against the
microscope name and Z resolution before use.

The one-time velocity characterization now covers the nonlinear low-speed
region as well as normal projection speeds. Calibration travel scales with
speed so the 10k point does not require a 500 µm crawl.

| Z speed command | Measured steady velocity | Calibration travel |
|---:|---:|---:|
| 10000 | 4.086 µm/s | 50 µm |
| 20000 | 10.216 µm/s | 50 µm |
| 40000 | 22.479 µm/s | 50 µm |
| 75000 | 40.660 µm/s | 50 µm |
| 150000 | 83.533 µm/s | 100 µm |
| 300000 | 168.845 µm/s | 200 µm |
| 500000 | 281.353 µm/s | 333 µm |
| 750000 | 422.508 µm/s | 500 µm |

For each projection:

1. The endpoint-inclusive frame count is calculated as
   `ceil(distance / requested spacing) + 1`.
2. At least six frames are enforced. If the nominal stack is shorter, the Z
   velocity is reduced so those six frames still span the requested distance.
3. The stage moves to a lead-in position and reaches steady velocity before
   the requested slab.
4. The Basler starts first and its first real frame releases the already-open
   stage command, avoiding serial-open and camera-startup latency.
5. Hardware camera timestamps and rapidly sampled Z positions identify the
   contiguous frame window that best matches both requested endpoints.
6. Pre-roll and post-roll frames are discarded; only the known frame count is
   used for min/max and index projections.

`generate_record.py` no longer writes a per-experiment calibration command.
The normal `mic.rec_projection(...)` entry point dispatches to this method, so
existing generated projection experiments use it automatically.

## Minimum-frame experiment

The decision criterion was repeatable placement of a 10 µm slab with both
timestamp-derived endpoints within 1 µm. The final camera-locked experiment
used five repeats at each count.

| Retained frames | Effective spacing | Maximum absolute endpoint error | Result |
|---:|---:|---:|---|
| 2 | 9.998 µm | 4.95 µm | Sampling phase flips; reject |
| 3 | 4.999 µm | 2.69 µm | Sampling phase flips; reject |
| 4 | 3.333 µm | 1.62 µm | Too coarse; reject |
| 5 | 2.499 µm | 1.38 µm | Marginal; reject |
| 6 | 2.000 µm | 0.86 µm | Pass |

Earlier independent batches reached the same boundary: five frames produced a
1.225 µm endpoint error, while 18 six-frame trials before the final camera lock
had a worst endpoint error of 0.776 µm. Six is therefore the enforced default,
not merely the smallest count that happened to pass once.

## Distance behavior and final recordings

After adding direct low-speed model points, five-repeat thin-slab tests gave:

| Distance | Retained frames | Selected speed | Coverage error range |
|---:|---:|---:|---:|
| 1 µm | 6 | 13062 | +0.022 to +0.083 µm |
| 2 µm | 6 | 22421 | +0.017 to +0.086 µm |
| 10 µm | 6 | about 106000 | about +0.3 µm in final saved validations |

At larger distances the requested 10 µm spacing naturally determines the
frame count. Absolute first-frame placement can lie within about half one
sampling interval, while total covered distance remains accurate.

The final full validation retained 101 frames across 999.78 µm. Measured mean
spacing was 10.057 µm and total coverage error was +5.88 µm (0.59%). Four valid
4112 × 3008 TIFFs were saved with embedded pre-acceleration diagnostics. The
public projection path also saved a 10 µm projection with a nominal two frames
expanded to the enforced six. The final camera-locked public-path run measured
2.005 µm mean spacing and +0.028 µm total coverage error.

All live runs restored the exact processed XYZ
`[13290276, 7889607, 723911]` and Z speed `8820000`. The final offline suite has
19 passing tests.

### New key artifacts

- Persistent velocity model: `leica_microscope\projection_velocity_model.json`
- Full 1 mm validation: `preaccelerated_projection_full_1mm_validation_20260831-183121+0200\run_manifest.json`
- Public projection-mode validation: `preaccelerated_projection_public_projection_mode_validation_20260831-183415+0200\run_manifest.json`
- Final camera-locked public validation: `preaccelerated_projection_final_camera_locked_public_validation_20260831-183936+0200\run_manifest.json`
- Final 2–6 frame sweep: `preaccelerated_reproducibility_camera_locked_frame_sweep_10.0_20260831-183534+0200\study_manifest.json`
- 1 µm confirmation: `preaccelerated_reproducibility_low_speed_model_confirmation_1.0_20260831-182822+0200\study_manifest.json`
- 2 µm confirmation: `preaccelerated_reproducibility_low_speed_model_confirmation_2.0_20260831-182907+0200\study_manifest.json`
- Reproducibility runner: `preaccelerated_reproducibility_study.py`
- Guarded projection runner: `preaccelerated_projection_runner.py`
- Motion/timing tests: `tests\test_projection_motion.py`
- Projection dispatch tests: `tests\test_projection_dispatch.py`
