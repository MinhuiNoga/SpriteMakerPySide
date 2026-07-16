# SpriteMaker PySide

[繁體中文 README](README.zh-TW.md)

SpriteMaker PySide is a local Windows desktop sprite and frame-matting editor built with Python, PySide6, OpenCV, NumPy, and Pillow. It replaces a large single-file HTML workflow with a native app for drawing, layer editing, frame sequencing, video frame extraction, alpha/color cleanup, selected-color edge spill cleanup, animation preview, and spritesheet export.

## Download

Download the packaged Windows build from GitHub Releases:

- [SpriteMakerPySide-2.2.0-win64.zip](https://github.com/MinhuiNoga/SpriteMakerPySide/releases/latest)

Unzip it, then run:

```text
SpriteMakerPySide-2.2.0.exe
```

The release package includes Python, PySide6, OpenCV, and required runtime files. Users do not need to install Python to run the packaged app.

## What's New In 2.2.0

- Adds selected-color edge spill cleanup with nearby inner-color repair, transparent RGB padding, batch scopes, diagnostics, debug overlays, and undo/redo support.
- Makes edge spill cleanup selection-aware: rectangular and lasso selections limit all modified pixels while nearby clean-color sampling can still use adjacent pixels.
- Makes fill selection-aware: rectangular selections constrain flood fill, while clicking inside a lasso selection directly fills the entire lasso area.
- Opens frame PNG, frame ZIP, spritesheet, and extracted-video ZIP save dialogs in the most recently imported file's directory.

## Startup

When the app opens, choose one of two workflows:

- **Import Video**: open the video frame extraction workflow first.
- **Enter Editor Mode**: open the sprite editor directly.

From the video workflow, use **Switch to Editor Mode** to close the video importer and enter the editor.

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
- **Import Video**: open the video importer from editor mode.
- **Save Current Frame** (`Ctrl+S`): export the current composited frame as PNG.
- **Save ZIP**: export all frames to a ZIP file.

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
- The black rectangle shows the current global output canvas size.
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

### Tools

- **Selection** (`V`): rectangular selection.
- **Lasso** (`L`): freeform selection.
- **Pen** (`B`): draw with the current color and brush size.
- **Eraser** (`E`): erase with the current brush size.
- **Fill** (`G`): flood fill the active layer using the current color and tolerance. A rectangular selection limits the flood fill to that selection. With a lasso selection active, clicking inside it directly replaces the whole lasso area with the current color.
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
- Rotate floating content 90 degrees with `R`
- Flip floating content horizontally with `H`
- Flip floating content vertically with `Shift+H`

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
- Click **Extract frame** to sample frames from the selected time range.

### Frame Selection Page

After extraction, the app opens a clean frame selection page:

- Left top: animation preview of checked frames.
- Right top: single-frame preview.
- Bottom: extracted frame thumbnail list.
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
| `Delete` | Delete selected pixels or delete frame if no selection exists |
| `R` | Rotate floating selection 90 degrees |
| `H` | Flip floating selection horizontally |
| `Shift+H` | Flip floating selection vertically |
| Arrow keys | Move selection/floating selection |
| `Shift+Arrow keys` | Move selection/floating selection by 10 pixels |
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
