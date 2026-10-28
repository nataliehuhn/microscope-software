"""Create comparable display-contrast TIFFs for the timed projection series.

The source images remain untouched. All ten images share one linear 8-bit
window, computed from their pooled pixel histogram. These enhanced images are
for display; quantitative analysis should use the original TIFFs.
"""

import json
from pathlib import Path

import numpy as np
import tifffile


ROOT = Path(__file__).resolve().parent / "INT_4_AP_7"
RUN_MANIFEST = ROOT / "run_20260923-173722+0200.json"
REPORT = ROOT / "contrast_enhancement_20260923-173722+0200.json"
LOW_QUANTILE = 0.001
HIGH_QUANTILE = 0.9999


def histogram_quantile(histogram, quantile):
    cumulative = np.cumsum(histogram)
    return int(np.searchsorted(cumulative, quantile * cumulative[-1]))


def main():
    manifest = json.loads(RUN_MANIFEST.read_text(encoding="utf-8"))
    if manifest["status"] != "complete" or len(manifest["scans"]) != 5:
        raise RuntimeError("The source projection run is incomplete")
    sources = []
    for scan in manifest["scans"]:
        sources.extend([Path(scan["min_file"]), Path(scan["max_file"])])
    if len(sources) != 10 or len(set(sources)) != 10:
        raise RuntimeError("Expected ten distinct projection TIFFs")
    destinations = [
        source.with_name(source.stem + "_contrast.tif") for source in sources
    ]
    existing = [str(path) for path in destinations if path.exists()]
    if REPORT.exists():
        existing.append(str(REPORT))
    if existing:
        raise FileExistsError("Contrast outputs already exist: {}".format(existing))

    histogram = np.zeros(256, dtype=np.int64)
    dimensions = None
    for source in sources:
        image = tifffile.imread(source)
        if image.dtype != np.uint8 or image.ndim != 2:
            raise ValueError("Expected an 8-bit grayscale image: {}".format(source))
        if dimensions is None:
            dimensions = image.shape
        elif image.shape != dimensions:
            raise ValueError("Projection image sizes differ")
        histogram += np.bincount(image.ravel(), minlength=256)

    low = histogram_quantile(histogram, LOW_QUANTILE)
    high = histogram_quantile(histogram, HIGH_QUANTILE)
    if high <= low:
        raise RuntimeError("The pooled image intensities have no usable range")
    values = np.arange(256, dtype=np.float64)
    lookup = np.clip(
        np.rint((values - low) * 255.0 / (high - low)), 0, 255
    ).astype(np.uint8)
    report = {
        "source_manifest": str(RUN_MANIFEST),
        "method": "shared_linear_percentile_window",
        "low_quantile": LOW_QUANTILE,
        "high_quantile": HIGH_QUANTILE,
        "input_low_value": low,
        "input_high_value": high,
        "formula": "round(clip((input - low) * 255 / (high - low), 0, 255))",
        "below_window_pixel_count": int(histogram[:low].sum()),
        "above_window_pixel_count": int(histogram[high + 1:].sum()),
        "total_pixel_count": int(histogram.sum()),
        "outputs": [],
        "note": "Enhanced TIFFs are for display; use original TIFFs for measurement.",
    }
    for source, destination in zip(sources, destinations):
        with tifffile.TiffFile(source) as file:
            image = file.asarray()
            metadata = json.loads(file.pages[0].description)
        enhanced = lookup[image]
        metadata.pop("shape", None)
        metadata.update({
            "DisplayContrastMethod": "shared_linear_percentile_window",
            "DisplayContrastInputLow": low,
            "DisplayContrastInputHigh": high,
            "DisplayContrastOutputLow": 0,
            "DisplayContrastOutputHigh": 255,
            "DisplayContrastSourceFile": source.name,
            "DisplayOnlyUseOriginalForQuantification": True,
        })
        tifffile.imwrite(
            destination, enhanced, photometric="minisblack", metadata=metadata
        )
        with tifffile.TiffFile(destination) as saved:
            saved_image = saved.asarray()
            saved_metadata = json.loads(saved.pages[0].description)
        if not np.array_equal(saved_image, enhanced):
            raise RuntimeError("Saved enhanced pixels did not verify")
        if saved_metadata["DisplayContrastInputLow"] != low:
            raise RuntimeError("Saved enhancement metadata did not verify")
        report["outputs"].append({
            "source": str(source),
            "enhanced": str(destination),
            "source_min_max": [int(image.min()), int(image.max())],
            "enhanced_min_max": [int(enhanced.min()), int(enhanced.max())],
            "shape": list(enhanced.shape),
        })
        print(destination, flush=True)
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("CONTRAST_WINDOW={}..{}".format(low, high), flush=True)
    print("REPORT={}".format(REPORT), flush=True)


if __name__ == "__main__":
    main()
