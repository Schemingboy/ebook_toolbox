import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from web_api import validate_workflow_path


class WebApiPathValidationTests(unittest.TestCase):
    def test_rejects_relative_path_and_accepts_existing_absolute_path(self):
        with self.assertRaisesRegex(ValueError, "必须是完整路径"):
            validate_workflow_path("outputH:", "输出目录")

        with TemporaryDirectory() as temp_dir:
            self.assertEqual(
                validate_workflow_path(temp_dir, "本地电子书库", must_exist=True),
                Path(temp_dir),
            )


if __name__ == "__main__":
    unittest.main()
