"""Machine/user config layering tests (pure, temporary directories)."""

from __future__ import annotations

import contextlib
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from labguide.config import _merge_config_layers, load_config


def write_config(directory: Path, content: str) -> Path:
    path = directory / "labguide.toml"
    path.write_text(content, encoding="utf-8")
    return path


@contextlib.contextmanager
def locations(machine_dir: Path, user_dir: Path, cwd: Path):
    """Pin every config-search location so tests never touch real config."""
    with (
        mock.patch("labguide.config._machine_config_dir", return_value=machine_dir),
        mock.patch("labguide.config._user_config_dir", return_value=user_dir),
        mock.patch("labguide.config._sidecar_exe_dir", return_value=cwd),
        mock.patch("labguide.config.Path.cwd", return_value=cwd),
        mock.patch.dict(os.environ, {}, clear=False),
    ):
        os.environ.pop("LABGUIDE_CONFIG", None)
        yield


class MergeLayersTests(unittest.TestCase):
    def test_machine_layer_wins_per_key(self) -> None:
        user = {"backend": {"model": "user-model", "base_url": "http://user"}}
        machine = {"backend": {"model": "machine-model"}}
        merged = _merge_config_layers(user, machine)
        self.assertEqual(merged["backend"]["model"], "machine-model")
        self.assertEqual(merged["backend"]["base_url"], "http://user")

    def test_user_fills_keys_machine_omits(self) -> None:
        user = {"backend": {"base_url": "http://user"}, "capture": {"ui_enabled": True}}
        machine = {"backend": {"model": "machine-model"}}
        merged = _merge_config_layers(user, machine)
        self.assertEqual(merged["capture"], {"ui_enabled": True})
        self.assertEqual(merged["backend"]["base_url"], "http://user")

    def test_machine_only(self) -> None:
        merged = _merge_config_layers({}, {"backend": {"model": "machine-model"}})
        self.assertEqual(merged["backend"]["model"], "machine-model")

    def test_empty_layers(self) -> None:
        self.assertEqual(_merge_config_layers({}, {}), {})


class LoadConfigLayeringTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.machine_dir = root / "machine"
        self.user_dir = root / "user"
        self.cwd = root / "cwd"
        for directory in (self.machine_dir, self.user_dir, self.cwd):
            directory.mkdir()

    def test_machine_layer_applies_to_every_user(self) -> None:
        write_config(
            self.machine_dir,
            '[backend]\nmodel = "pratt-agent"\nbase_url = "https://llm.pratt.edu/v1"\n',
        )
        write_config(
            self.user_dir,
            '[backend]\nmodel = "user-model"\n[session]\nlog_path = "user-log.jsonl"\n',
        )
        with locations(self.machine_dir, self.user_dir, self.cwd):
            config = load_config()
        # Machine wins where it sets a key; the user layer fills the rest.
        self.assertEqual(config.backend.model, "pratt-agent")
        self.assertEqual(config.backend.base_url, "https://llm.pratt.edu/v1")
        self.assertEqual(config.session.log_path, "user-log.jsonl")

    def test_machine_layer_without_user_config(self) -> None:
        write_config(self.machine_dir, '[backend]\nmodel = "pratt-agent"\n')
        with locations(self.machine_dir, self.user_dir, self.cwd):
            config = load_config()
        self.assertEqual(config.backend.model, "pratt-agent")
        # Untouched keys stay at defaults.
        self.assertEqual(config.backend.timeout_seconds, 30.0)

    def test_user_config_alone_when_no_machine_layer(self) -> None:
        write_config(self.user_dir, '[backend]\nmodel = "user-model"\n')
        with locations(self.machine_dir, self.user_dir, self.cwd):
            config = load_config()
        self.assertEqual(config.backend.model, "user-model")

    def test_explicit_path_bypasses_machine_layer(self) -> None:
        write_config(self.machine_dir, '[backend]\nmodel = "machine-model"\n')
        explicit = write_config(self.cwd, '[backend]\nmodel = "explicit-model"\n')
        with locations(self.machine_dir, self.user_dir, self.cwd):
            config = load_config(explicit)
        self.assertEqual(config.backend.model, "explicit-model")


if __name__ == "__main__":
    unittest.main()
