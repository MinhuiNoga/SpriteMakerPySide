# SpriteMakerPySide 4.0.1 — Motion Analysis and ARPG Animation Metadata

4.0.1 turns the video/GIF importer into a non-destructive AI-video-to-game-animation workflow. The source video and extracted source frames are never rewritten by motion analysis or combat timing tools.

## End-to-end workflow

1. Import a video or GIF and extract frames with the existing exact / balanced / sharp strategies.
2. Optionally run **Auto**, **Loop**, or **One-shot** motion analysis.
3. Review loop candidates, one-shot range, movement-spike warnings, and long-term centroid drift.
4. Apply the suggested range only when it is useful. The analyzer never deletes frames automatically.
5. Manually check or uncheck frames. This remains the authoritative final selection.
6. Build the **ARPG combat timeline** for the selected frames:
   - Startup
   - Active
   - Recovery
   - one or more Hit frames
   - optional Cancel frame
7. Preview the timing bar and S / A / R / HIT / C thumbnail badges.
8. Save a `project.json` file to preserve the non-destructive curation state.
9. Export `animation.json` for the game runtime.

If frame selection changes after a combat timeline has been created, the old combat metadata is invalidated intentionally. This prevents phase and hit-frame indices from silently drifting onto the wrong images. Programmatic thumbnail or badge refreshes are explicitly excluded from this invalidation path.

## Motion detectors

### Global period profile

The analyzer builds a compact visual feature for each frame and a pairwise distance matrix. Candidate periods are ranked from the mean distance between frames separated by lag `L`, then a local seam score chooses a candidate cycle. A harmonic check reduces common half-cycle errors in walk/run sequences.

### One-shot range

For attacks, jumps, hit reactions, and similar actions, the detector searches for an early/late pair that returns to a similar pose while the interior frames make a meaningful excursion away from that pose.

### Movement-spike QA

Adjacent-frame distances are evaluated with a median/MAD robust threshold. Outliers are marked as possible jolts. They are never deleted automatically because a fast attack frame can be a legitimate large movement.

### Drift estimate

Foreground centroids are estimated from transparency when present, otherwise from a border-derived background color. A linear trend estimates long-term X/Y drift. This is diagnostic only; final correction continues to use the existing foot-alignment tool.

## ARPG phase suggestion

`combat_timeline.py` measures robust per-transition image motion on the currently selected frames. The strongest action transition becomes the center of the suggested Active window. The suggestion is only a starting point: the user can edit the Startup and Active boundaries, Hit frames, and Cancel frame before applying the timeline.

The internal phase convention is zero-based with exclusive boundaries:

```text
startup  = [0, startup_end)
active   = [startup_end, active_end)
recovery = [active_end, frame_count)
```

The UI displays frame numbers as one-based values so artists can work with familiar frame numbering.

## `project.json` schema v2

The video importer can save and reload a non-destructive curation file containing:

- source path and source video metadata
- extraction time range
- target FPS and extraction strategy
- selected extraction indices
- original source frame indices and timestamps
- animation preview FPS and loop state
- motion-analysis results
- ARPG combat timeline metadata

4.0.1 can still read the 4.0 schema-v1 project format; schema-v1 projects simply have no combat timeline to restore.

## Runtime `animation.json`

The runtime manifest uses `index_base = 0` and contains:

```json
{
  "schema": "SpriteMakerPySide.animation",
  "schema_version": 1,
  "app_version": "4.0.1",
  "index_base": 0,
  "animation": {
    "name": "sword_slash_01",
    "fps": 12.0,
    "loop": false,
    "frame_count": 12,
    "duration_seconds": 1.0
  },
  "phases": {
    "startup": {"start": 0, "end_exclusive": 4},
    "active": {"start": 4, "end_exclusive": 7},
    "recovery": {"start": 7, "end_exclusive": 12}
  },
  "hit_frames": [5],
  "cancel_frame": 9,
  "frames": []
}
```

Every entry in `frames` maps the runtime output frame back to its extraction index, original source frame index, and source timestamp. It also includes the resolved phase plus hit/cancel flags.

## Compatibility

The original `VideoImportDialog` remains unchanged. 4.0.1 installs `VideoImportDialogV401` during application bootstrap. `VideoImportDialogV401` layers integration guards over the 4.x feature dialog so programmatic QListWidget badge/thumbnail updates cannot be mistaken for user frame-selection edits. The 3.x importer remains isolated, and existing foot alignment, editor import, sprite-sheet generation, color tools, and image editing code are not replaced by the 4.0.1 timing system.
