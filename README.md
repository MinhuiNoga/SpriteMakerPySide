# SpriteMaker PySide

[繁體中文 README](README.zh-TW.md)

SpriteMaker PySide is a local desktop sprite editor rebuilt with Python and PySide6.
It replaces a large single-file HTML workflow with a native Windows app that can use local memory, threaded work, OpenCV video extraction, and a more responsive editing surface.

## Download

Windows users can download the packaged app from the GitHub Releases page:

- `SpriteMakerPySide-2.0.0-win64.zip`

Unzip the archive and run:

```text
SpriteMakerPySide-2.0.0.exe
```

The packaged app includes Python, PySide6, OpenCV, and the required runtime files. Users do not need to install Python when using the release build.

## What's New In 2.0.0

- Startup screen lets the user choose video import or the sprite editor.
- Video import workflow with looping preview, start/end range handles, a draggable playhead, pause/play, and `Ctrl+wheel` preview zoom.
- Target FPS extraction defaults to `12 FPS`.
- Extracted-frame review page with animation preview, single-frame preview, resizable panels, checked-frame playback, and `Ctrl+wheel` zoom.
- Frame review animation preview defaults to `24 FPS`.
- Frame thumbnails display only their frame number.
- Long-press frame range selection for quickly toggling many extracted frames.
- Saving extracted frames creates `matted_frames.zip` with ordered files:

```text
matte_00001.png
matte_00002.png
matte_00003.png
...
```

## Editor Features

- Import PNG/JPG images as animation frames.
- Frame timeline with copy, delete, previous/next frame controls, and drag reordering.
- Layer dock with visibility, opacity, active layer switching, and a reopenable layer window.
- Pen, eraser, fill, magic wand, single-frame color erase, and global color erase tools.
- Selection and lasso tools with cut, copy, paste, move, rotate, flip, free scale, and Shift proportional scaling.
- Ctrl+wheel zoom on the main canvas, spritesheet preview, animation preview, and video import previews.
- Custom global output canvas size with a live preview frame.
- Toggle center lines and checker/solid background preview.
- Animation preview with selectable frame range.
- Spritesheet preview/export with zoom, edge trimming, and outline expansion.
- Undo/redo history shared across frame changes.
- Color picker supports alpha; Alt+click samples the visible pixel color into the current tool color.

## Tool Behavior

- Magic wand: the click position chooses the starting connected area; the target color is the current toolbar color plus tolerance.
- Single-frame color erase: erases matching pixels from every layer in the current frame using the current toolbar color plus tolerance.
- Global color erase: erases matching pixels from every layer in every frame using the current toolbar color plus tolerance.
- Alt+click: samples the clicked visible pixel and updates the current toolbar color.

## Shortcuts

- `Ctrl+Z`: undo
- `Ctrl+Shift+Z`: redo
- `B`: pen
- `E`: eraser
- `V`: selection
- `L`: lasso selection
- `G`: fill
- `W`: magic wand
- `Shift+W`: single-frame color erase
- `U`: global color erase
- `Ctrl+C`: copy selection
- `Ctrl+X`: cut selection
- `Ctrl+V`: paste selection
- `Delete`: delete selected pixels when a selection exists
- `R`: rotate floating selection 90 degrees
- `H`: flip floating selection horizontally
- `Shift+H`: flip floating selection vertically
- Arrow keys: move selection or switch frames depending on context
- `Ctrl+0`: reset canvas zoom to 100%

## Run From Source

Requirements:

- Python 3.9 or newer
- PySide6
- NumPy
- Pillow
- OpenCV

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

The generated app is written to:

```text
dist\SpriteMakerPySide\SpriteMakerPySide.exe
```

Generated build outputs are ignored by Git.

## License

This project is open source under the MIT License.
