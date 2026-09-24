import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_INGEST_ENV = (
    "QUE_INGEST_INBOX",
    "QUE_INGEST_MEMEX_RAW_DROPBOX",
    "QUE_INGEST_FLYWHEEL_RAW",
)


def _reload_config(extra_env=None):
    env = {key: value for key, value in os.environ.items() if key not in _INGEST_ENV}
    if extra_env:
        env.update(extra_env)
    with patch.dict(os.environ, env, clear=True):
        import config
        return importlib.reload(config)


class IngestConfigTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        import config
        importlib.reload(config)

    def test_default_inbox_is_home_queinbox(self):
        cfg = _reload_config()
        self.assertEqual(cfg.INBOX_DIR, Path.home() / "QueInbox")
        self.assertEqual([target["key"] for target in cfg.INGEST_TARGETS], ["inbox"])

    def test_env_overrides_paths_and_omits_blank_targets(self):
        with tempfile.TemporaryDirectory() as td:
            inbox = Path(td) / "inbox"
            memex = Path(td) / "memex"
            cfg = _reload_config({
                "QUE_INGEST_INBOX": str(inbox),
                "QUE_INGEST_MEMEX_RAW_DROPBOX": str(memex),
                "QUE_INGEST_FLYWHEEL_RAW": "",
            })
            self.assertEqual(cfg.INBOX_DIR, inbox)
            self.assertEqual(
                [target["key"] for target in cfg.INGEST_TARGETS],
                ["inbox", "memex-raw-dropbox"],
            )

    def test_blank_targets_make_ensure_inbox_a_noop(self):
        cfg = _reload_config({
            "QUE_INGEST_INBOX": "",
            "QUE_INGEST_MEMEX_RAW_DROPBOX": "",
            "QUE_INGEST_FLYWHEEL_RAW": "",
        })
        self.assertEqual(cfg.INGEST_TARGETS, ())
        self.assertIsNone(cfg.ensure_inbox())

    def test_ensure_inbox_creates_configured_path(self):
        with tempfile.TemporaryDirectory() as td:
            inbox = Path(td) / "inbox"
            cfg = _reload_config({"QUE_INGEST_INBOX": str(inbox)})
            created = cfg.ensure_inbox()
            self.assertEqual(created, inbox)
            self.assertTrue(inbox.is_dir())

    def test_options_use_home_tilde_not_absolute_home(self):
        cfg = _reload_config({"QUE_INGEST_INBOX": str(Path.home() / "QueInbox")})
        relative = cfg.ingest_target_options()[0]["relative_path"]
        self.assertTrue(relative.startswith("~"))
        self.assertNotIn(str(Path.home()), relative)


if __name__ == "__main__":
    unittest.main()
