"""Repository-local environment loading tests use temporary fixtures only."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from app.backend.local_env import DEFAULT_DOTENV_PATH, load_repo_dotenv


class LocalEnvironmentTests(unittest.TestCase):
    def test_default_path_is_repo_root_dotenv(self):
        self.assertEqual(DEFAULT_DOTENV_PATH, Path(__file__).resolve().parents[2] / ".env")

    def test_absent_dotenv_is_a_noop(self):
        with TemporaryDirectory() as temporary_directory:
            loader = Mock()
            self.assertFalse(load_repo_dotenv(Path(temporary_directory) / ".env", loader=loader))
            loader.assert_not_called()

    def test_explicit_shell_values_take_precedence_over_temporary_dotenv(self):
        with TemporaryDirectory() as temporary_directory:
            dotenv_path = Path(temporary_directory) / ".env"
            dotenv_path.write_text(
                "ASSESSMENT_DOTENV_TEST_VALUE=from-file\nASSESSMENT_DOTENV_FILE_ONLY=from-file\n",
                encoding="utf-8",
            )

            def fake_dotenv_loader(*, dotenv_path: Path, override: bool) -> bool:
                self.assertEqual(dotenv_path, Path(temporary_directory) / ".env")
                self.assertFalse(override)
                for line in dotenv_path.read_text(encoding="utf-8").splitlines():
                    name, value = line.split("=", 1)
                    if override or name not in os.environ:
                        os.environ[name] = value
                return True

            with patch.dict(os.environ, {"ASSESSMENT_DOTENV_TEST_VALUE": "from-shell"}, clear=False):
                os.environ.pop("ASSESSMENT_DOTENV_FILE_ONLY", None)
                self.assertTrue(load_repo_dotenv(dotenv_path, loader=fake_dotenv_loader))
                self.assertEqual(os.environ["ASSESSMENT_DOTENV_TEST_VALUE"], "from-shell")
                self.assertEqual(os.environ["ASSESSMENT_DOTENV_FILE_ONLY"], "from-file")


if __name__ == "__main__":
    unittest.main()
