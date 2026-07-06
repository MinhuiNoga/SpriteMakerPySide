# SpriteMaker PySide

[繁體中文 README](README.zh-TW.md)

SpriteMaker PySide is a local desktop sprite editor rebuilt with Python and PySide6.
It was created to replace a large single-file HTML workflow with a faster desktop app that can use local memory, threaded batch processing, and native windows.

## Features

- Startup screen for choosing video import or the editor workflow.
- Video import workflow with start/end time, target FPS extraction, frame picking, PNG export, and import into the editor.
- Import PNG/JPG images as animation frames.
- Frame timeline with copy, delete, previous/next frame controls, and drag reordering.
- Layer dock with visibility, opacity, active layer switching, and reopenable layer window.
- Pen, eraser, fill, magic wand, single-frame color erase, and global color erase tools.
- Selection and lasso tools with cut, copy, paste, move, rotate, flip, free scale, and Shift proportional scaling.
- Ctrl+wheel zoom on the main canvas, spritesheet preview, and animation preview.
- Custom output canvas size with live preview frame.
- Toggle center lines and checker/solid background preview.
- Animation preview with selectable frame range.
- Spritesheet preview/export with zoom, edge trimming, and outline expansion.
- Undo/redo history shared across frame changes.
- Color picker supports alpha; Alt+click samples the visible pixel color into the current tool color.

## Tool Behavior

- Magic wand: click chooses the starting area; the target color is the current toolbar color plus tolerance, and only connected matching pixels are erased.
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

## Requirements

- Python 3.9 or newer
- PySide6
- NumPy
- Pillow
- PyInstaller, only needed when building an exe
- OpenCV, used for video frame extraction

Install dependencies:

```powershell
py -m pip install -r requirements.txt
```

## Run From Source

```powershell
py -m sprite_maker
```

or:

```powershell
.\start.ps1
```

## Build Windows App

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
