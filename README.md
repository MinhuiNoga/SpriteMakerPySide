# SpriteMaker PySide

[繁體中文 README](README.zh-TW.md)

SpriteMaker PySide is a local Windows desktop sprite and frame-matting editor built with Python, PySide6, OpenCV, NumPy, and Pillow. It replaces a large single-file HTML workflow with a native app for drawing, layer editing, frame sequencing, video frame extraction, alpha/color cleanup, selected-color edge spill cleanup, animation preview, and spritesheet export.

## Download

Download the packaged Windows build from GitHub Releases:

- [SpriteMakerPySide-2.4.1-win64.zip](https://github.com/MinhuiNoga/SpriteMakerPySide/releases/latest)

Unzip it, then run:

```text
SpriteMakerPySide-2.4.1.exe
```

The release package includes Python, PySide6, OpenCV, and required runtime files. Users do not need to install Python to run the packaged app.

## What's New In 2.4.1

- Replaces the fixed `1/2`, `1/4`, and `1/8` Pixel Compression preset buttons with a continuous **Output Ratio** slider.
- The slider ranges from `1%` to `100%` in `0.5%` steps and defaults to `25%`.
- The current percentage and familiar fractions such as `1/2`, `1/4`, and `1/8` are displayed beside the slider.
- Dragging updates the logical width and height immediately, but the image preview is recalculated only after release to reduce unnecessary work.
- Manual logical width and height inputs remain available. Unlocking the aspect ratio disables the single-ratio slider and displays the independent width/height percentages.

## What's New In 2.4.0

- Adds **Color Consolidation** for collapsing diffusion-generated near-duplicate colors into one sampled color.
- Click a visible pixel on the active layer to sample the canonical color. The existing toolbar tolerance controls which nearby RGB colors are matched.
- The preview scans every matching pixel in the rectangular/lasso selection, even when matching pixels are disconnected. With no active selection, it scans the entire active layer.
- A red overlay previews all matched pixels and the status bar reports the sampled color, tolerance, matched count, and actual changed count.
- Press `Enter` to apply the preview or `Esc` to cancel it. Clicking another pixel resamples the canonical color.
- Only RGB is consolidated. Per-pixel alpha remains unchanged, and fully transparent pixels are ignored.
- Only the active layer of the current frame is modified, with one undo/redo history entry.

## What's New In 2.3.4

- Adds **Pixel Compression** to the editor toolbar.
- Pixel Compression affects only the active layer of the current frame. Other layers and frames remain unchanged.
- A rectangular or lasso selection limits processing to the selected pixels; with no active selection, the entire active layer is processed.
- The selected area is reduced to a user-defined logical resolution, then restored to its original dimensions with nearest-neighbor scaling for a controlled pixelated result.
- Includes alpha-weighted area sampling, dominant area color, and nearest-neighbor sampling modes. Alpha-aware sampling prevents invisible RGB values in transparent pixels from contaminating visible colors.
- Includes locked aspect ratio, `1/2`, `1/4`, and `1/8` presets, plus side-by-side before/after preview.
- Applying the result creates one undo step and does not change the frame, layer, canvas, or selection dimensions.

## What's New In 2.3.3

- Renames **All-Frame Selection Box** to **Range Selection Box**.
- Range Selection Box now applies synchronized movement, scaling, rotation, flipping, and deletion strictly to the frames currently selected in the frame timeline.
- Selecting one thumbnail affects only that frame. `Shift`-selecting a continuous range or `Ctrl`-selecting separate thumbnails affects exactly those selected frames.

## What's New In 2.3.2

- Updates the default Spritesheet trimming setup to remove `1 px`, enable edge-trim antialiasing, and use `2.00 px` contour smoothing.
- Keeps the outline disabled by default while setting its ready-to-use width to `1 px`.

## What's New In 2.3.1

- Replaces memory-heavy supersampled trimming with native-resolution OpenCV contour rerasterization using antialiased filled contours.
- Edge-trim antialiasing can be disabled to retain exact four-connected hard pixel-layer removal for pixel art.
- Adds adjustable `0–2 px` contour smoothing based on maximum-deviation polygon fitting; `1 px` is the default for straightening shallow digital stair steps while retaining pronounced corners.
- Outline generation follows the trimmed image's 50% alpha contour, preventing faint antialiasing pixels from becoming enlarged black stair steps.
- Outlines are alpha-composited behind low-opacity edge pixels, eliminating the transparent-looking gap between an antialiased trimmed contour and its outline.
- Removes the separate outline-smoothing control and its Gaussian processing.
- Opens the editor with only the frame-sequence dock visible; Layers and Edge Spill Cleanup remain closed until requested.
- Spritesheet preview and saved PNG use the same contour-antialiased result.
- Non-1:1 Spritesheet preview zoom now uses high-quality smooth resampling instead of nearest-style fast scaling; saved PNG pixels remain unchanged.

## What's New In 2.3.0

- Replaces per-timestamp random seeking with one seek followed by sequential decoding, preserving monotonic source-frame order and more reliable actual timestamps.
- Adds **Exact Time**, **Balanced**, and **Sharpness First** extraction strategies. **Balanced** is the default.
- Balanced and Sharpness First evaluate nearby decoded frames using Laplacian sharpness, target-time distance, source-frame spacing, and scene-histogram similarity.
- Candidate frames are kept in a small rolling buffer and released as targets are finalized, avoiding full-range uncompressed video storage.
- Extracted frames record target time, actual source time, time offset, source index, sharpness score, and clarity percentile.
- Low-clarity frames remain selectable but receive a visible red badge, detailed tooltip, and summary count on the frame selection page.
- No automatic sharpening or generated detail is applied to the extracted images.

## What's New In 2.2.9

- Fixes Spritesheet edge trimming so `1 px` removes exactly one alpha-mask contour layer.
- Replaces the square 3x3 erosion kernel with four-connected erosion. This prevents 45-degree edges, hair strands, and sloped clothing contours from losing two staircase levels in one trim step.
- Each additional trim value removes one further layer predictably, and preview/export use the same corrected pipeline.

## What's New In 2.2.8

- Fixes selection rotation jitter by freezing the rotation center, start vector, and starting angle for the entire pointer drag.
- Rotation angle changes are calculated directly from the frozen start vector, preventing intermediate previews from feeding rounding error into later pointer movements.
- Compensates for workspace coordinate shifts while rotating beyond the current image boundary.
- Smooth preview and final commit continue to resample from the original floating selection with the same transform quality, preventing repeated rasterization damage.

## What's New In 2.2.7

- Fixes selection resize jitter and tearing by calculating the entire drag from the transform captured when the resize handle is first pressed, instead of feeding each updated scale back into the next mouse move.
- `Shift` proportional resize now uses one stable radial ratio for both axes.
- Adds **Transform Quality** with **Smooth** as the default for interpolated scaling/rotation and **Pixel Sharp** for nearest-neighbor pixel-art transforms. Preview and final commit always use the same quality.
- Pressing `Delete` while the editor frame timeline has focus removes every selected frame, including an inclusive `Shift` range, as one undoable operation.
- Delete remains context-sensitive: canvas focus deletes selected pixels, while timeline focus deletes selected frames.

## What's New In 2.2.6

- Adds an optional **Pixel Blend Pen** mode that keeps the stroke core at the current pen color while blending edge pixels with nearby colors from the pre-stroke image.
- Blend strength, edge width, sample radius, sampling source, and transparent-edge behavior are independently configurable.
- Sampling can use the active layer or the composite of all visible layers. Transparent pixels are ignored by default, with an optional **Fade To Transparent** mode for semi-transparent stroke edges.
- The stronger defaults are 75% strength, a 2 px edge, a 5 px sample radius, and all-visible-layer sampling. If active-layer sampling finds no usable color, it automatically falls back to the visible composite.
- A cyan inner ring in the cursor preview shows the solid-color core when edge blending is enabled.
- Pixel blending uses local NumPy/OpenCV processing and a stable pre-stroke snapshot to prevent repeated self-sampling and keep large-brush drawing responsive.
- After every stroke, the status bar reports how many pixels actually changed through blending, or explains that no neighboring color was found.

## What's New In 2.2.5

- Separates the editable workspace from the black output guide. The black rectangle now only previews the PNG/ZIP/spritesheet crop and never blocks editing.
- Pen, eraser, fill, rectangular/lasso selection, pasted content, and floating-selection transforms can work beyond the imported image boundary.
- Crossing a workspace edge automatically adds transparent workspace in chunked increments while keeping every frame aligned.
- Workspace expansion keeps the output guide and artwork visually anchored. Pixels outside the guide remain editable and in undo/redo history, but are excluded from export until the output size is enlarged.
- Rectangular and lasso selections can now be finished with `Esc` or by clicking a pixel outside the selection. Any floating transform is committed before the selection is dismissed.

## What's New In 2.2.4

- Introduced synchronized multi-frame selection transforms under the former **All-Frame Selection Box** name. Version 2.3.3 renames it **Range Selection Box** and limits it strictly to selected timeline frames.
- Adds inclusive `Shift` range selection to the editor frame timeline. Click one frame, then `Shift`-click another to select both endpoints and every frame between them.
- Selected frame ranges can be dragged as one ordered block, and opening Animation Preview uses the selected range as its initial playback start/end interval.
- Synchronized frame edits are stored as one project-wide undo/redo operation.

## What's New In 2.2.3

- Closing or switching away from editor mode now also closes its frame timeline, layer panel, edge spill cleanup panel, and other editor child dialogs.
- Editor ZIP export now follows the current arranged frame order and always renames every image sequentially as `video_frame_0001.png`, `video_frame_0002.png`, and so on.

## What's New In 2.2.2

- Switching from editor mode to video import now shows a destructive-action warning first.
- After confirmation, the editor page closes and its frames, layers, selections, clipboard, debug overlay, and undo/redo history are initialized before video import opens.
- Cancelling the warning keeps the editor and all current content unchanged. Dragging a video into the editor follows the same confirmation flow.
- **Switch to Editor Mode** in the video frame selection page also requires confirmation and warns that extracted frames and checked states will not be imported; use **Import to Editor** to keep checked frames.

## What's New In 2.2.1

- Unchecked thumbnails on the extracted-video frame selection page now display a semi-transparent gray overlay, making kept and discarded frames easy to distinguish at a glance.

## What's New In 2.2.0

- Adds selected-color edge spill cleanup with nearby inner-color repair, transparent RGB padding, batch scopes, diagnostics, debug overlays, and undo/redo support.
- Makes edge spill cleanup selection-aware: rectangular and lasso selections limit all modified pixels while nearby clean-color sampling can still use adjacent pixels.
- Makes fill selection-aware: rectangular selections constrain flood fill, while clicking inside a lasso selection directly fills the entire lasso area.
- Opens frame PNG, frame ZIP, spritesheet, and extracted-video ZIP save dialogs in the most recently imported file's directory.

## Startup

When the app opens, choose one of two workflows:

- **Import Video**: open the video frame extraction workflow first.
- **Enter Editor Mode**: open the sprite editor directly.

From the video workflow, use **Switch to Editor Mode** to close the video importer and enter an initialized editor. A confirmation warns that extracted frames are discarded; use **Import to Editor** when checked frames should be kept.

## Supported Files

- Images: `.png`, `.jpg`, `.jpeg`, `.bmp`, `.webp`
- Videos: `.mp4`, `.mov`, `.avi`, `.webm`, `.mkv`

When importing multiple images, frames are ordered by filename with natural numeric sorting. For example:

```text
frame_1.png
frame_2.png
frame_10.png
```

## Editor Workflow

### File Actions

The **File** toolbar menu contains:

- **Import** (`Ctrl+O`): import image files as a new frame sequence. Existing frames are replaced.
- **Insert** (`Ctrl+I`): insert images after the current frame.
- **Clear**: clear the current project.
- **Import Video**: switch from editor mode to the video importer. A warning explains that the current editor project and history will be initialized; the switch only proceeds after confirmation.
- **Save Current Frame** (`Ctrl+S`): export the current composited frame as PNG.
- **Save ZIP**: export all frames in their current arranged order to a ZIP file, renamed sequentially as `video_frame_0001.png`, `video_frame_0002.png`, and so on.

Save dialogs for the current frame, frame ZIP, spritesheet, and extracted-video ZIP open in the directory of the most recently imported image or video. Before any file is imported, they use the user's home directory.

You can also drag files into the editor:

- Drag one or more images into the editor to append them to the end of the current frame sequence.
- Drag a video into the editor to open it in the video importer.
- Dragging videos into the video import window itself also loads that video.

### Frame Timeline

The bottom frame dock contains:

- Previous frame
- Next frame
- Duplicate frame
- Delete frame
- Thumbnail timeline

Frames can be reordered by dragging thumbnails in the frame timeline. Reordering enters undo history.

Use the timeline's multi-frame controls as follows:

- Click one frame, then `Shift`-click another to select the inclusive continuous range.
- With the frame timeline focused, press `Delete` to remove every selected frame in one operation; one undo restores the complete range.
- Drag any selected thumbnail to move the whole selected range while preserving its internal order.
- Enable **Range Selection Box** before drawing a rectangular or lasso selection. The synchronized operation targets only the thumbnails currently selected in the frame timeline.
- Move, resize, rotate, flip, or delete the selected content to apply the same transform to every target frame. One undo restores the complete synchronized operation.
- Opening Animation Preview with a selected range sets that range as the initial playback interval.

### Layers

The layer dock supports:

- Add layer
- Duplicate layer
- Delete layer
- Move layer up/down
- Toggle layer visibility
- Select active layer
- Change active layer opacity
- Reopen the layer window from **Layer Window** if it was closed

Drawing, fill, erase, selection deletion, and color erase operations affect the active layer unless the tool is explicitly global.

### Canvas And View

- `Ctrl+wheel`: zoom the main canvas.
- `Ctrl+0`: reset canvas zoom to 100%.
- Use scrollbars to reach areas outside the current viewport.
- The black rectangle is only a guide for the current global export crop; it does not limit editing.
- Drawing or moving content beyond the imported image boundary automatically expands the transparent workspace.
- Pixels outside the black guide remain in frame/layer data and undo/redo history. They are exported only after **Output W/H** is enlarged enough to include them.
- Edit **Output W** and **Output H** to change the global output size.
- Use **Current Size** to match the output size to the current frame.
- Toggle **Center Lines** to show horizontal/vertical center guides.
- Toggle **Checker** to use transparent checker background.
- Use **Background** to choose a solid preview background color.

## Drawing Tools

### Color And Brush Settings

- **Color**: choose the current pen/fill/erase-target color. Alpha is supported.
- **Transparent**: set the current color to fully transparent.
- **Brush**: controls pen and eraser size.
- **Tolerance**: controls fill, magic wand, single-frame color erase, and global color erase tolerance.
- `Alt+click` on the canvas: sample the visible pixel color into the toolbar color.

### Pixel Blend Pen

Enable **Pixel Blend** to blend only the outer pixels of pen strokes with nearby colors:

- **Strength** (`0-100%`): how strongly edge pixels move toward sampled neighboring colors.
- **Edge** (`1-8 px`): width of the blended outer stroke band.
- **Sample** (`1-16 px`): nearby color sampling radius.
- **Active Layer / All Visible Layers**: choose whether sampling reads only the active layer or the visible composite. All visible layers is the default; active-layer mode automatically falls back to the visible composite only where the active layer has no usable neighboring color.
- **Fade To Transparent**: allow transparent neighboring pixels to reduce edge alpha. It is disabled by default, so transparent pixels do not change stroke alpha.

The defaults are 75% strength, a 2 px edge, and a 5 px sample radius. The stroke core always uses the current pen color. Each mouse-down starts from a stable image snapshot, so a stroke never repeatedly samples its own newly painted pixels. After mouse release, the status bar reports the number of pixels that actually differed from a normal solid pen stroke. This mode affects only the pen; eraser, fill, and edge-spill cleanup behavior are unchanged.

### Pixel Compression

Use **Pixel Compression** on the editor toolbar to create a lower-resolution pixel style while keeping the original image dimensions:

- It processes only the active layer of the current frame.
- With an active rectangular or lasso selection, only selected pixels are changed. Without a selection, the whole active layer is processed.
- Choose the logical output width and height, or use the `1%` to `100%` output-ratio slider. The slider supports `0.5%` steps and displays familiar fractions at `50%`, `25%`, and `12.5%`.
- Slider dragging updates the target dimensions immediately and recalculates the preview after release. Unlock the aspect ratio to enter independent custom width and height values.
- **Alpha-Weighted Area** produces stable reduced colors while ignoring invisible RGB contamination from transparent pixels.
- **Dominant Area Color** keeps the most prominent local color in each logical pixel block.
- **Nearest Neighbor** samples hard pixels directly.
- The reduced result is enlarged back to the original processing-area size with nearest-neighbor scaling. Pixels outside the selection, other layers, and other frames remain untouched.
- The dialog shows original/result previews before applying. Apply creates one undo/redo history entry.

### Color Consolidation

Use **Color Consolidation** to remove small near-duplicate color variations produced by diffusion-based image generation:

1. Optionally create a rectangular or lasso selection around the part to clean.
2. Select **Color Consolidation**, then click the correct color that should be retained.
3. Adjust the existing toolbar tolerance if needed. The red overlay updates immediately.
4. Press `Enter` to replace every matched RGB value with the sampled RGB, or `Esc` to cancel.

Unlike Paint Bucket, Color Consolidation does not require matching pixels to be connected. It scans the full selection, or the entire active layer when there is no selection. Every pixel is compared directly with the original sampled color, so tolerance cannot spread progressively through a gradient. Fully transparent pixels are ignored; visible and semitransparent pixels retain their original alpha values.

### Tools

- **Selection** (`V`): rectangular selection.
- **Lasso** (`L`): freeform selection.
- **Pen** (`B`): draw with the current color and brush size.
- **Eraser** (`E`): erase with the current brush size.
- **Fill** (`G`): flood fill the active layer using the current color and tolerance. A rectangular selection limits the flood fill to that selection. With a lasso selection active, clicking inside it directly replaces the whole lasso area with the current color.
- **Color Consolidation**: sample one canonical color and replace all similar RGB values in the current selection or active layer, regardless of connectivity. `Enter` applies and `Esc` cancels the preview.
- **Magic Wand** (`W`): erase a connected color region on the active layer.
- **Single-Frame Color Erase** (`Shift+W`): erase matching pixels from every layer in the current frame.
- **Global Color Erase** (`U`): erase matching pixels from every layer in every frame.

Color erase behavior:

- The clicked position is used only as the starting connected area for the magic wand.
- The target color is the current toolbar color plus tolerance.
- Single-frame erase and global erase process all matching pixels, not only connected pixels.

### Selected-Color Edge Spill Cleanup

The **Edge Spill Cleanup** dock repairs colored fringing around alpha edges without replacing color across the whole image. Use the **Spill Panel** toolbar button to reopen the dock when it is hidden.

It reuses existing editor state:

- Spill color: the current toolbar color.
- Color tolerance: the existing tolerance value.

Controls:

- **Despill Strength**: repair strength from `0` to `1`, default `0.8`.
- **Edge Width**: alpha-edge band width from `1` to `10 px`, default `3 px`.
- **Alpha Erode**: optional alpha shrink from `0` to `3 px`, default `0`.
- **Feather**: optional repair-weight smoothing from `0` to `3 px`, default `0`.
- **Edge Color Bleeding**: fills RGB values in transparent edge padding while preserving alpha.
- **Scope**: active layer, all layers in current frame, or all layers in all frames. With a rectangle or lasso selection active, cleanup only changes pixels inside that selection (the nearby clean-color lookup can still reference adjacent pixels for natural repair).

Use it for green/red/blue screen residue, AI-generated color fringing, chroma-key leftovers, and transparent PNG edge padding. The tool only processes pixels near the alpha edge that are close to the current toolbar color; interior pixels with similar colors are left alone. Contaminated edge pixels are recolored from nearby clean inner character pixels, and alpha is preserved unless **Alpha Erode** is greater than `0`.

Debug controls:

- **Show Debug Overlay**: overlays the selected diagnostic mask on the canvas.
- **Overlay Type**: `innerEdgeBand`, `outerPaddingBand`, `semiTransparentBand`, `contaminatedMask`, `lookupFallback`, `actualChangedPixels`, or `allDebugMasks`.
- **Contaminated Pixel Test Paint**: paints detected contaminated pixels bright red while preserving alpha.
- **Detect Only**: runs detection, statistics, and overlay generation without writing changes to the image.
- **Print Last Stats**: prints the latest cleanup statistics to the console.

Every run prints debug statistics including mask counts, contaminated pixel counts, clean-color lookup success/fallback counts, changed RGB/alpha counts, average RGB delta, average/max repair weight, and before/after RGB/alpha sums.

## Selection Editing

Selections support:

- Copy (`Ctrl+C`)
- Cut (`Ctrl+X`)
- Paste (`Ctrl+V`)
- Delete selected pixels (`Delete`)
- Drag selected content
- Move the selection or floating pasted content with arrow keys
- Hold `Shift` with arrow keys to move by 10 pixels
- Rotate floating content with the on-canvas yellow handle
- Resize floating content with corner handles
- Hold `Shift` while resizing to preserve proportions
- Choose **Smooth** transform quality to reduce tearing during scaling/rotation, or **Pixel Sharp** to preserve nearest-neighbor pixel edges
- Rotate floating content 90 degrees with `R`
- Flip floating content horizontally with `H`
- Flip floating content vertically with `Shift+H`
- Press `Esc` or click a pixel outside the selection to finish the transform and deselect

Pasted content appears at the same coordinate where it was copied, even when pasted into another frame.

## Video Import Workflow

The video importer supports choosing or dragging a video file.

### Video Preview Page

- The selected video loops inside the chosen start/end range.
- Use the green and red handles to set start and end time.
- Use the yellow playhead to scrub preview position.
- Dragging time handles pauses playback and resumes after release to reduce preview lockups.
- Use **Play/Pause** to control preview playback.
- Use `Ctrl+wheel` over the preview to zoom.
- Target FPS defaults to `12 FPS`.
- Choose an extraction strategy: **Exact Time**, **Balanced** (default), or **Sharpness First**.
- Click **Extract frame** to sequentially decode and select frames from the chosen time range.

### Frame Selection Page

After extraction, the app opens a clean frame selection page:

- Left top: animation preview of checked frames.
- Right top: single-frame preview.
- Bottom: extracted frame thumbnail list. Unchecked frames display a semi-transparent gray thumbnail overlay.
- Low-clarity results show a red badge but remain checked and selectable.
- Hover a thumbnail to inspect target time, actual source time, offset, source index, sharpness, and clarity percentile.
- Splitters let you resize the preview and frame list areas.
- `Ctrl+wheel` on the preview or frame list changes zoom/thumbnail size.
- Check or uncheck frames to decide what to keep.
- Long-press a frame, then drag over a range to quickly toggle many frames.
- Animation preview supports play/pause, custom FPS, progress slider, and loop toggle.
- **All**, **None**, and **Invert** help manage selection.
- **Save PNG** creates `matted_frames.zip`.
- **Import to Editor** imports checked frames into the editor.

Saved extracted frames are stored inside `matted_frames.zip` as:

```text
matte_00001.png
matte_00002.png
matte_00003.png
...
```

## Editor Animation Preview

Open **Animation Preview** from the output toolbar.

Features:

- Custom playback FPS.
- Start/end frame controls for looping a section.
- Right-side thumbnail list of all imported frames.
- Click a thumbnail to preview that frame.
- **Set as Start** and **Set as End** quickly choose the loop range from the thumbnail list.
- Current playback frame is highlighted in the thumbnail list.
- `Ctrl+wheel` changes preview zoom.

## Spritesheet Preview And Export

Open **Spritesheet** from the output toolbar.

Options:

- Column count.
- Global output cell size if an output canvas size is set.
- Trim edge pixels touching transparency.
- Add an outline around the sprite edge.
- Choose outline color.
- Preview zoom slider and `Ctrl+wheel` zoom.
- Save the spritesheet as PNG.

## Shortcuts

| Shortcut | Action |
| --- | --- |
| `Ctrl+O` | Import images as a new sequence |
| `Ctrl+I` | Insert images after current frame |
| `Ctrl+S` | Save current frame |
| `Ctrl+Z` | Undo |
| `Ctrl+Shift+Z` | Redo |
| `Ctrl++` | Zoom in |
| `Ctrl+-` | Zoom out |
| `Ctrl+0` | Reset canvas zoom |
| `Ctrl+wheel` | Zoom the canvas/preview under the cursor |
| `Shift+click` two timeline frames | Select the inclusive continuous frame range |
| `B` | Pen |
| `E` | Eraser |
| `V` | Rectangular selection |
| `L` | Lasso selection |
| `G` | Fill |
| `W` | Magic wand |
| `Shift+W` | Single-frame color erase |
| `U` | Global color erase |
| `Ctrl+C` | Copy selection |
| `Ctrl+X` | Cut selection |
| `Ctrl+V` | Paste selection |
| `Delete` | Delete selected pixels when the canvas has focus; delete all selected frames when the frame timeline has focus |
| `R` | Rotate floating selection 90 degrees |
| `H` | Flip floating selection horizontally |
| `Shift+H` | Flip floating selection vertically |
| Arrow keys | Move selection/floating selection |
| `Shift+Arrow keys` | Move selection/floating selection by 10 pixels |
| `Esc` | Finish the current rectangular/lasso selection and deselect |
| `Alt+click` | Sample visible pixel color |

## Run From Source

Requirements:

- Python 3.9 or newer
- PySide6
- NumPy
- Pillow
- OpenCV
- PyInstaller, only for building Windows packages

Install dependencies:

```powershell
py -m pip install -r requirements.txt
```

Run:

```powershell
py -m sprite_maker
```

or:

```powershell
.\start.ps1
```

## Build Windows App

Install dependencies first, then run:

```powershell
.\build_exe.ps1
```

Generated build outputs are ignored by Git.

## License

This project is open source under the MIT License.
