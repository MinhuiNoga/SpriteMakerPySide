# SpriteMakerPySide 4.0 — Motion Analysis

4.0 adds a non-destructive motion-analysis layer to the existing video/GIF importer. The final frame decision remains under user control.

## New workflow

1. Import a video or GIF and extract frames as before.
2. On the frame-selection page, choose **Auto**, **Loop**, or **One-shot** analysis.
3. Click **Analyze motion**.
4. Review the suggested range, loop candidates, movement-spike markers, and centroid drift estimate.
5. Click **Apply suggested range** only when useful. No frame is deleted automatically.
6. Save the current curation as `project.json` and restore it later without rewriting the source video or source frames.

## Detectors

### Global period profile

The analyzer builds a compact visual feature for each frame and a pairwise distance matrix. Candidate periods are ranked from the mean distance between frames separated by lag `L`, then a local seam score chooses a candidate cycle. A harmonic check reduces common half-cycle errors in walk/run sequences.

### One-shot range

For attacks, jumps, hit reactions, and similar actions, the detector searches for an early/late pair that returns to a similar pose while the interior frames make a meaningful excursion away from that pose.

### Movement-spike QA

Adjacent-frame distances are evaluated with a median/MAD robust threshold. Outliers are marked as possible jolts. They are never deleted automatically because a fast attack frame can be a legitimate large movement.

### Drift estimate

Foreground centroids are estimated from transparency when present, otherwise from a border-derived background color. A linear trend estimates long-term X/Y drift. This is diagnostic only; final correction should continue to use the existing foot-alignment tool.

## `project.json`

The video importer can save and reload a non-destructive curation file containing source metadata, extraction range, target FPS, extraction strategy, selected frame indices, original source indices/timestamps, preview settings, and motion-analysis results.

## Compatibility

The original `VideoImportDialog` remains unchanged. 4.0 installs `VideoImportDialogV4` during application bootstrap so existing 3.x importer behavior remains isolated from the extension layer.
