"""Config path resolution tests (pure, no filesystem side effects)."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from labguide.config import load_config, resolve_config_path


class ResolveConfigPathTests(unittest.TestCase):
    def test_explicit_path_wins(self) -> None:
        explicit = Path("somewhere/else.toml")
        with mock.patch.dict(os.environ, {"LABGUIDE_CONFIG": "env.toml"}):
            self.assertEqual(resolve_config_path(explicit), explicit)

    def test_env_var_wins_over_defaults(self) -> None:
        with mock.patch.dict(os.environ, {"LABGUIDE_CONFIG": "env.toml"}):
            self.assertEqual(resolve_config_path(), Path("env.toml"))

    def test_cwd_config_preferred_over_exe_and_user(self) -> None:
        with TemporaryDirectory() as tmp:
            cwd_config = Path(tmp) / "labguide.toml"
            cwd_config.write_text("[backend]\n", encoding="utf-8")
            exe_dir = Path(tmp) / "exe"
            user_dir = Path(tmp) / "user"
            exe_dir.mkdir()
            user_dir.mkdir()
            (exe_dir / "labguide.toml").write_text("[backend]\n", encoding="utf-8")
            (user_dir / "labguide.toml").write_text("[backend]\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("LABGUIDE_CONFIG", None)
                with (
                    mock.patch("labguide.config._sidecar_exe_dir", return_value=exe_dir),
                    mock.patch("labguide.config._user_config_dir", return_value=user_dir),
                    mock.patch("labguide.config.Path.cwd", return_value=Path(tmp)),
                ):
                    self.assertEqual(resolve_config_path(), cwd_config)

    def test_exe_dir_config_used_when_cwd_has_none(self) -> None:
        with TemporaryDirectory() as tmp:
            exe_dir = Path(tmp) / "exe"
            exe_dir.mkdir()
            (exe_dir / "labguide.toml").write_text("[backend]\n", encoding="utf-8")
            empty_dir = Path(tmp) / "empty"
            empty_dir.mkdir()
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("LABGUIDE_CONFIG", None)
                with (
                    mock.patch("labguide.config._sidecar_exe_dir", return_value=exe_dir),
                    mock.patch("labguide.config._user_config_dir", return_value=empty_dir),
                    mock.patch("labguide.config.Path.cwd", return_value=empty_dir),
                ):
                    self.assertEqual(resolve_config_path(), exe_dir / "labguide.toml")

    def test_user_config_dir_used_as_last_resort(self) -> None:
        with TemporaryDirectory() as tmp:
            user_dir = Path(tmp) / "user"
            user_dir.mkdir()
            (user_dir / "labguide.toml").write_text("[backend]\n", encoding="utf-8")
            empty_dir = Path(tmp) / "empty"
            empty_dir.mkdir()
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("LABGUIDE_CONFIG", None)
                with (
                    mock.patch("labguide.config._sidecar_exe_dir", return_value=empty_dir),
                    mock.patch("labguide.config._user_config_dir", return_value=user_dir),
                    mock.patch("labguide.config.Path.cwd", return_value=empty_dir),
                ):
                    self.assertEqual(resolve_config_path(), user_dir / "labguide.toml")

    def test_no_config_anywhere_returns_conventional_path(self) -> None:
        with TemporaryDirectory() as tmp:
            empty_dir = Path(tmp) / "empty"
            empty_dir.mkdir()
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("LABGUIDE_CONFIG", None)
                with (
                    mock.patch("labguide.config._sidecar_exe_dir", return_value=empty_dir),
                    mock.patch("labguide.config._user_config_dir", return_value=empty_dir),
                    mock.patch("labguide.config.Path.cwd", return_value=empty_dir),
                ):
                    self.assertEqual(resolve_config_path(), empty_dir / "labguide.toml")


class LoadConfigIntegrationTests(unittest.TestCase):
    def test_load_config_reads_exe_dir_config(self) -> None:
        with TemporaryDirectory() as tmp:
            exe_dir = Path(tmp)
            (exe_dir / "labguide.toml").write_text(
                "[backend]\nmodel = \"from-exe-dir\"\n",
                encoding="utf-8",
            )
            empty_dir = Path(tmp) / "empty"
            empty_dir.mkdir()
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("LABGUIDE_CONFIG", None)
                with (
                    mock.patch("labguide.config._sidecar_exe_dir", return_value=exe_dir),
                    mock.patch("labguide.config._user_config_dir", return_value=empty_dir),
                    mock.patch("labguide.config.Path.cwd", return_value=empty_dir),
                ):
                    config = load_config()
                    self.assertEqual(config.backend.model, "from-exe-dir")


if __name__ == "__main__":
    unittest.main()
