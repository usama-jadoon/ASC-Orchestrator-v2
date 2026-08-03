from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from asc_orchestrator.config import ConfigurationError, load_config
from asc_orchestrator.cli import main


class LoadConfigTests(unittest.TestCase):
    def test_loads_and_resolves_default_configuration(self) -> None:
        root = Path(__file__).resolve().parents[1]
        config = load_config(root)
        self.assertEqual(config.protocol_version, "ACP/v1.0")
        self.assertEqual(config.registry_dir, root / ".project-os/COMPANY/DEPARTMENTS")

    def test_rejects_missing_required_value(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "asc-orchestrator.toml").write_text(
                "[runtime]\nproject_os_dir = '.project-os'\n", encoding="utf-8"
            )
            with self.assertRaises(ConfigurationError):
                load_config(root)

    def test_rejects_wrong_protocol_version(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "asc-orchestrator.toml").write_text(
                "[runtime]\n"
                "project_os_dir = '.project-os'\n"
                "registry_dir = '.project-os/COMPANY/DEPARTMENTS'\n"
                "audit_dir = '.project-os/AUDIT'\n"
                "protocol_version = 'ACP/v2.0'\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ConfigurationError, "ACP/v1.0"):
                load_config(root)

    def test_cli_validates_configuration(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(main(["--root", str(root), "config"]), 0)
