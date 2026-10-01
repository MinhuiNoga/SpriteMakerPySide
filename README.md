# SpriteMaker PySide

[繁體中文 README](README.zh-TW.md)

SpriteMaker PySide is a local Windows desktop sprite and frame-matting editor built with Python, PySide6, OpenCV, NumPy, and Pillow. It replaces a large single-file HTML workflow with a native app for drawing, layer editing, frame sequencing, video/GIF frame extraction, spritesheet splitting and playback, alpha/color cleanup, selected-color edge spill cleanup, animation preview, and spritesheet export.

## Download

Download the packaged Windows build from GitHub Releases:

- [GitHub Releases (published builds)](https://github.com/MinhuiNoga/SpriteMakerPySide/releases/latest)

Unzip it, then run:

```text
SpriteMakerPySide-3.3.0.exe
```

The release package includes Python, PySide6, OpenCV, and required runtime files. Users do not need to install Python to run the packaged app.

## What's New In 3.3.0

- Fixes missing red previews after selecting multiple frames. Color Consolidation uses the selected frame list directly, supports entire active layers without a region, and preserves the region and source-color preview when switching frames during range selection or batch consolidation.
- **Batch Color Consolidation**: enable synchronized range selection, select multiple frames, then draw a rectangle or lasso. Consolidation edits matching pixels only inside that region on each selected frame's active layer. One Undo/Redo covers the entire batch.
- **Independent target color**: the Color Consolidation tool exposes a target color picker and a reset-to-sampled-color button. Resampling the source does not overwrite the custom target or change the drawing palette.
- The current frame shows the red match overlay; status reports batch counts, source/target colors and total changed pixels. Enter applies and Escape cancels; tolerance and target changes refresh the preview.
- Original alpha, transparent pixels, unselected frames, other layers and out-of-region pixels remain unchanged. Both single and multiple frames use the selected region when present, otherwise the entire active layer. Batch Color Consolidation follows selected thumbnails independently of the synchronized-selection toggle.

## What's New In 3.2.2

- Drop local images into sprite import to load and split them automatically, using the same image format list as the editor.
- Drops work over previews, thumbnails, and settings. Multiple files use the first supported image.
- Existing loading and splitting paths are reused. Invalid images preserve the current sheet; directories, remote URLs, and non-images are rejected. Successfully loading a new image stops old playback and returns to the first frame.

## What's New In 3.2.1

- Sprite import now supports minimize, maximize/restore, a window resize grip, and F11 fullscreen. Escape exits fullscreen and restores the prior window state. Grid and background settings use collapsible tabs to free preview space.

- Extend the yellow grid beyond any source edge. Grid X/Y can be negative and grid dimensions can exceed the image.
- Expanded areas display as a transparency checkerboard and export as transparent pixels. Original pixels retain their size and position; cells redistribute across the new grid.
- The view transform stays fixed during dragging and the preview canvas expands on release. Entirely outside cells are EMPTY; empty ratios include transparent extension pixels.
- Keeps the vertical preview height divider. Total output is limited to 64 megapixels to avoid accidental oversized allocations.

## What's New In 3.2.0

- Sprite import now uses **Grid X / Y / Width / Height + Columns / Rows**. Changing grid dimensions redistributes every cell; Separation X / Y lives under Advanced, including existing negative overlap support.
- Drag the grid interior, edges, or corners with two-way numeric control updates. The grid stays inside the source and cells remain at least 1 × 1 px. Thumbnails rebuild on release.
- **Auto Detect Grid** supports transparent, green, blue, and custom color backgrounds, with alpha threshold, RGB distance tolerance, confidence, and warnings.
- Every split classifies **EMPTY** cells with the shared background mask (default foreground threshold: 0.10%). Empty cells retain their indices, start unchecked, and can be checked manually.
- Non-divisible cells receive individual transparent output padding without expanding the grid. Selection, animation, FPS, looping, zoom, and editor import remain available.

Detection fits background projections to regular separator positions. Confidence describes fit quality, not a calibrated probability. Sheets without regular gaps, wholly empty rows/columns, repeated internal holes, or invisible per-frame padding can be ambiguous. Unknown axes preserve manual settings; adjust the grid after detection. Color mode classifies backgrounds but does not remove their color from imported frames.

## What's New In 3.1.0

- Adds **腳底對齊** (Foot Alignment) to the editor: choose a reference frame, click its planted foot, then click the corresponding anchor in each frame, or use automatic silhouette-based anchors.
- Automatic anchoring supports the current frame or all frames and screen-left foot, screen-right foot, or midpoint. With no reference, the current frame becomes the reference. Batch mode preserves existing anchors by default; uncheck that option to replace them.
- Applied cumulative offsets (such as `-168 px`), anchors, the frozen reference, and panel settings survive reopening the alignment dialog. The records are memory-only and clear on leaving the editor, closing the app, or replacing the entire project.
- A frozen reference overlay, ground guides, anchor crosshair, adjustable opacity/zoom, and FPS playback help compare frames. Integer X/Y controls move the whole character; positive values move right/down.
- Align both axes or height only. Preserve intentional movement during running, stepping, or jumping rather than pinning every lifted foot to the ground.
- Changes are staged until **套用所有調整** (Apply all); Cancel discards them, and one Undo/Redo restores/reapplies the whole operation. Original layer pixels remain intact. PNG, ZIP, animation, and sheet export share the output centers.
- Warns when visible pixels extend outside the output frame. Increase output W/H in the editor before exporting to preserve sword tips, hats, and other content.

Select a frame and press **設此格為參考，再點腳底** before clicking the reference foot. Switch frames and click the matching point, then fine-tune X/Y and play the sequence. Yellow guides mark the reference; cyan marks the current anchor. **重設目前格** resets the current frame's cumulative offset to zero, using its first alignment baseline in this editor session. Reopening does not reset values or apply them twice. A new reference affects subsequent clicks only. Cancel discards only the current draft; previously applied records remain. Frame reorder, cloning, workspace expansion, and undo/redo preserve the corresponding metadata.

Automatic points estimate contact positions from the lower transparent silhouette, filtering faint alpha fringes and small disconnected specks. This is not semantic foot recognition: capes, low weapons, and shadows may affect the estimate. Blank frames, opaque backgrounds, and frames without a usable silhouette are skipped with a message. Review playback and correct points manually as needed.

Keep the packaged `_internal` folder beside the EXE when distributing or running the Windows build.

## What's New In 3.0.1

- Horizontal and vertical spacing in Sprite sheet import now accept negative values, with matching preview and split results for overlapping cells.
- Negative spacing that would prevent cells from advancing right or down is rejected instead of producing invalid cuts.

## What's New In 3.0.0

- Adds **Import Sprite Sheet** as a third startup workflow and as a command in the editor's **File** menu.
- Splits a sheet using configurable columns, rows, horizontal spacing, vertical spacing, and one outer margin applied to all four sides.
- If the usable image dimensions are not evenly divisible by the grid, transparent pixels are added on the right and bottom instead of cropping source pixels.
- Shows the calculated cell size, transparent padding, numbered grid preview, and a row-major thumbnail sequence.
- All cells are checked by default. Unchecked cells receive a semi-transparent gray overlay and are excluded from playback and import.
- Plays only checked cells with play/pause, loop, progress seeking, custom FPS, and `Ctrl + mouse wheel` preview zoom.
- **Split Sprite Sheet** imports checked cells into the editor as `sprite_frame_0001.png`, `sprite_frame_0002.png`, and so on.
- Importing from an existing editor project shows a destructive-action warning. The current project and undo/redo history are replaced only after a valid split is confirmed; cancelling or loading an invalid image leaves the project unchanged.

## What's New In 2.5.0

- Adds animated GIF support to the **Video / GIF Import** workflow through the startup choice, file picker, and drag-and-drop.
- Plays GIF previews with their authored per-frame delays and preserves transparency while looping only the selected start/end range.
- Builds a cumulative timeline for variable-duration GIF frames, so playhead seeking and start/end handles resolve to the correct source frame.
- Resamples the selected GIF time range at the requested target FPS before opening the existing frame-picking page.
- GIF extraction uses exact-time frame mapping rather than video sharp-frame substitution, preserving authored poses and intentional held frames.
- Animated GIF files dropped into the editor open the animation importer; single-frame GIF files remain normal image imports.

## What's New In 2.4.3

- Replaces the former Pixel Blend Pen with a conventional **Blur Brush** that softens existing image detail instead of painting the current foreground color into stroke edges.
- Adds configurable blur strength, Gaussian radius, brush hardness, and optional alpha preservation.
- Uses alpha-aware premultiplied sampling so hidden RGB in transparent pixels does not contaminate visible sprite edges.
- Each mouse-down uses one stable source snapshot and the maximum accumulated brush coverage. Repeatedly crossing the same position in one stroke does not recursively blur an already blurred result.
- Rectangular and lasso selections constrain changed pixels. The tool continues to affect only the active layer of the current frame and creates one undo/redo entry per stroke.

## What's New In 2.4.2

- Expands editor import and drag-and-drop beyond PNG/JPEG to common image formats.
- Supports JPEG variants (`JPE`, `JFIF`, `JIF`, `JFI`), `BMP/DIB`, `GIF`, `WebP`, `TIFF`, `TGA`, `ICO/ICNS`, `PBM/PGM/PPM`, `XBM/XPM`, and `SVG/SVGZ`.
- Uses Qt image decoding with automatic orientation and a Pillow fallback for broader compatibility.
- Animated or multi-page image files imported through the normal image command use their first frame/page. Use **Video / GIF Import** to preserve and extract an animated GIF timeline.
- Multiple imported images retain natural filename sorting, such as `frame_2` before `frame_10`.

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

When the app opens, choose one of three workflows:

- **Import Video / GIF**: open the video or animated-GIF frame extraction workflow first.
- **Import Sprite Sheet**: open the grid splitter, select cells, preview their animation, and import the checked cells into a new editor project.
- **Enter Editor Mode**: open the sprite editor directly.

From the video/GIF workflow, use **Switch to Editor Mode** to close the importer and enter an initialized editor. A confirmation warns that extracted frames are discarded; use **Import to Editor** when checked frames should be kept.

## Supported Files

- Images: PNG, JPEG/JPG/JPE/JFIF/JIF/JFI, BMP/DIB, GIF, WebP, TIFF, TGA, ICO/ICNS, PBM/PGM/PPM, XBM/XPM, and SVG/SVGZ
- Animation importer: `.mp4`, `.mov`, `.avi`, `.webm`, `.mkv`, animated `.gif`

When importing multiple images, frames are ordered by filename with natural numeric sorting. For example:

```text
frame_1.png
frame_2.png
frame_10.png
```

## Sprite Sheet Import

Open the importer from the startup screen or choose **File > Import Sprite Sheet** in editor mode.

1. Choose a supported image file.
2. Choose a Background mode and thresholds, then press **Auto Detect Grid**, or set Columns, Rows, Grid X / Y / Width / Height manually.
3. Drag the grid interior to move it, or an edge/corner to resize it. Advanced Separation X / Y describes real source gaps or negative overlap.
4. Review the numbered grid. The information panel reports the source size, calculated per-cell size, and any transparent right/bottom padding.
5. Check the cells to keep. EMPTY cells start unchecked but can be checked manually. Cells are ordered left to right, then top to bottom. Use **Select All**, **Select None**, or **Invert Selection** for batch changes.
6. Preview the checked sequence with custom FPS, looping, and progress seeking. Use `Ctrl + mouse wheel` over either preview to zoom.
7. Choose **Split Sprite Sheet** to replace the editor project with only the checked cells.

Every cell has one consistent output size. When usable grid dimensions cannot be divided evenly, integer remainders are distributed across source cells and smaller output cells receive transparent right/bottom padding. The grid does not automatically expand or sample pixels outside its rectangle. Manually extend the grid beyond the source to add transparent output pixels. From editor mode, the existing frames, layers, and undo/redo history are cleared only after the split is accepted successfully.

## Editor Workflow

### File Actions

The **File** toolbar menu contains:

- **Import** (`Ctrl+O`): import image files as a new frame sequence. Existing frames are replaced.
- **Insert** (`Ctrl+I`): insert images after the current frame.
- **Clear**: clear the current project.
- **Import Video / GIF**: switch from editor mode to the animation importer. A warning explains that the current editor project and history will be initialized; the switch only proceeds after confirmation.
- **Import Sprite Sheet**: open the grid splitter. Confirming a valid split replaces the current project with the checked cells; cancelling keeps the current project unchanged.
- **Save Current Frame** (`Ctrl+S`): export the current composited frame as PNG.
- **Save ZIP**: export all frames in their current arranged order to a ZIP file, renamed sequentially as `video_frame_0001.png`, `video_frame_0002.png`, and so on.

Save dialogs for the current frame, frame ZIP, spritesheet, and extracted-video ZIP open in the directory of the most recently imported image or video. Before any file is imported, they use the user's home directory.

You can also drag files into the editor:

- Drag one or more images into the editor to append them to the end of the current frame sequence.
- Drag a video or animated GIF into the editor to open it in the animation importer. A single-frame GIF remains a normal image import.
- Drag a video or GIF into the **Video / GIF Import** window itself to load it directly.

Supported image imports include PNG, JPEG/JPG/JPE/JFIF/JIF/JFI, BMP/DIB, GIF, WebP, TIFF, TGA, ICO/ICNS, PBM/PGM/PPM, XBM/XPM, and SVG/SVGZ. An animated GIF imported with the normal image command uses its first frame; use **Video / GIF Import** for its complete timeline.

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

### Blur Brush

Enable **Blur Brush** to soften existing pixels under the pen cursor without painting the current foreground color:

- **Strength** (`0-100%`): blend ratio between the original image and the blurred result.
- **Radius** (`1-32 px`): Gaussian sampling radius. Larger values soften broader image detail.
- **Hardness** (`0-100%`): size of the fully affected brush center. Lower values create a wider feathered edge.
- **Preserve Alpha**: keeps every pixel's original transparency and modifies only RGB. This is enabled by default.

The defaults are 50% strength, a 4 px radius, 50% hardness, and Preserve Alpha enabled. Alpha-aware premultiplied sampling prevents invisible colors in transparent pixels from bleeding into visible edges. Each mouse-down captures a stable active-layer snapshot, so repeatedly crossing the same position in one stroke does not recursively blur the result. A rectangular or lasso selection limits changed pixels; without a selection, the circular brush can affect any pixel it crosses. Each completed stroke creates one undo/redo history entry and reports its changed-pixel count in the status bar. Eraser, fill, other layers, other frames, and edge-spill cleanup are unchanged.

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
2. Select **Color Consolidation**, then click the source color to match. Use **統一目標** to choose a separate replacement RGB, or **使用取樣色** to retain the sampled-color target.
3. Adjust the existing toolbar tolerance if needed. The red overlay updates immediately.
4. Press `Enter` to replace every matched RGB value with the sampled RGB, or `Esc` to cancel.

Unlike Paint Bucket, Color Consolidation does not require matching pixels to be connected. With synchronized range selection enabled, select multiple frames before drawing the region to process that same region on each active layer. A single frame without a region still processes its entire active layer. Every pixel is compared directly with the original sampled color, so tolerance cannot spread progressively through a gradient. Fully transparent pixels are ignored; visible and semitransparent pixels retain their original alpha values.

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

## Video / GIF Import Workflow

The animation importer supports choosing or dragging a video or GIF file.

### Video / GIF Preview Page

- The selected video or GIF loops inside the chosen start/end range. GIF transparency and individual frame delays are preserved.
- Use the green and red handles to set start and end time.
- Use the yellow playhead to scrub preview position.
- Dragging time handles pauses playback and resumes after release to reduce preview lockups.
- Use **Play/Pause** to control preview playback.
- Use `Ctrl+wheel` over the preview to zoom.
- Target FPS defaults to `12 FPS`.
- Videos support **Exact Time**, **Balanced** (default), and **Sharpness First** extraction. GIF files use exact-time mapping to retain their authored poses and held frames.
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

The packaging script reads the version from `pyproject.toml` to name the EXE and ZIP, and always uses the root-level `main.ico` as the EXE icon.

Generated build outputs are ignored by Git.

## License

This project is open source under the MIT License.
