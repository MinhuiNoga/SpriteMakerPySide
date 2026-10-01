"""Shared image formats for editor and sprite import file selection/drop."""

IMAGE_EXTENSION_ORDER = (
    ".png",
    ".jpg",
    ".jpeg",
    ".jpe",
    ".jfif",
    ".jif",
    ".jfi",
    ".bmp",
    ".dib",
    ".gif",
    ".webp",
    ".tif",
    ".tiff",
    ".tga",
    ".ico",
    ".icns",
    ".pbm",
    ".pgm",
    ".ppm",
    ".xbm",
    ".xpm",
    ".svg",
    ".svgz",
)
IMAGE_EXTENSIONS = frozenset(IMAGE_EXTENSION_ORDER)
IMAGE_FILE_FILTER = "支援的圖片 (" + " ".join(f"*{extension}" for extension in IMAGE_EXTENSION_ORDER) + ")"
