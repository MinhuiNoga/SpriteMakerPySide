import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sprite_maker.app as app_module
from sprite_maker.bootstrap_v4 import install
from sprite_maker.video_import_v401 import VideoImportDialogV401


class V401BootstrapTests(unittest.TestCase):
    def test_bootstrap_installs_v401_importer(self):
        original = app_module.VideoImportDialog
        try:
            install(app_module)
            self.assertIs(app_module.VideoImportDialog, VideoImportDialogV401)
        finally:
            app_module.VideoImportDialog = original


if __name__ == "__main__":
    unittest.main()
