# SpriteMaker PySide

[English README](README.md)

SpriteMaker PySide 是一款以 Python + PySide6 製作的本地桌面版 sprite 編輯工具。
它的目標是取代龐大的單檔 HTML 工作流程，讓影像處理、圖層操作、影片擷取、批次去色和動畫預覽都能在桌面程式中更穩定地執行。

## 下載

Windows 使用者可以到 GitHub Releases 下載已打包版本：

- `SpriteMakerPySide-2.0.0-win64.zip`

解壓縮後執行：

```text
SpriteMakerPySide-2.0.0.exe
```

Release 版本已包含 Python、PySide6、OpenCV 和必要執行檔，使用者不需要另外安裝 Python。

## 2.0.0 更新重點

- 啟動 EXE 後可選擇「匯入影片」或「進入編輯模式」。
- 影片匯入流程支援循環預覽、開始/結束時間拉桿、播放進度拉桿、暫停/播放，以及 `Ctrl + 滾輪` 縮放預覽。
- 目標 FPS 預設為 `12 FPS`。
- 擷取後進入 frame 篩選頁，包含動畫預覽、單張預覽、可拉扯調整大小的布局、已勾選 frame 播放，以及 `Ctrl + 滾輪` 縮放。
- frame 篩選頁的動畫預覽速度預設為 `24 FPS`。
- frame 縮圖下方只顯示編號。
- 支援長按 frame 進入範圍選取模式，快速加入或取消多個 frame。
- 儲存擷取 frame 時會產生 `matted_frames.zip`，ZIP 內依序命名為：

```text
matte_00001.png
matte_00002.png
matte_00003.png
...
```

## 編輯器功能

- 匯入 PNG/JPG 圖片作為動畫影格。
- 下方影格列支援複製、刪除、上一幀/下一幀與拖曳排序。
- 圖層視窗支援顯示/隱藏、不透明度、作用中圖層切換，關閉後可再次開啟。
- 工具包含畫筆、橡皮擦、填色、魔術棒、單幀去色與全域去色。
- 支援選取框與繩索選取框，可剪下、複製、貼上、移動、旋轉、翻轉與自由縮放。
- 主畫布、Spritesheet 預覽、動畫預覽與影片匯入預覽皆支援 `Ctrl + 滾輪` 縮放。
- 可自訂全域輸出畫布尺寸，畫面中會同步顯示輸出黑框。
- 可切換圖層中心線、透明格背景與純色背景預覽。
- 動畫預覽可指定播放影格區段。
- Spritesheet 預覽/輸出支援縮放、邊緣扣除 pixel、補外框黑線。
- Undo/Redo 歷史不會因切換 frame 而清空。
- 顏色選擇支援 Alpha 透明度，`Alt + 點擊` 可從畫面取樣目前顏色。

## 去色工具邏輯

- 魔術棒：點擊位置只決定起始相連區域，目標顏色使用工具列目前顏色 + 容差。
- 單幀去色：使用工具列目前顏色 + 容差，刪除目前 frame 所有圖層中的符合像素。
- 全域去色：使用工具列目前顏色 + 容差，刪除所有 frame、所有圖層中的符合像素。
- `Alt + 點擊`：從目前可見畫面取樣點擊像素，並更新工具列目前顏色。

## 快捷鍵

- `Ctrl+Z`：上一動作
- `Ctrl+Shift+Z`：下一動作
- `B`：畫筆
- `E`：橡皮擦
- `V`：選取框
- `L`：繩索選取框
- `G`：填色
- `W`：魔術棒
- `Shift+W`：單幀去色
- `U`：全域去色
- `Ctrl+C`：複製選取內容
- `Ctrl+X`：剪下選取內容
- `Ctrl+V`：貼上選取內容
- `Delete`：有選取框時刪除選取內容
- `R`：將浮動選取內容旋轉 90 度
- `H`：水平翻轉浮動選取內容
- `Shift+H`：垂直翻轉浮動選取內容
- 方向鍵：依目前狀態移動選取框或切換影格
- `Ctrl+0`：畫布縮放回 100%

## 從原始碼執行

系統需求：

- Python 3.9 或更新版本
- PySide6
- NumPy
- Pillow
- OpenCV

安裝依賴：

```powershell
py -m pip install -r requirements.txt
```

執行：

```powershell
py -m sprite_maker
```

或執行：

```powershell
.\start.ps1
```

## 打包 Windows App

先安裝依賴，然後執行：

```powershell
.\build_exe.ps1
```

打包完成後 exe 會產生在：

```text
dist\SpriteMakerPySide\SpriteMakerPySide.exe
```

`build/` 和 `dist/` 這類產物已在 `.gitignore` 中排除，不會被提交到 GitHub。

## 授權

本專案以 MIT License 開源。
