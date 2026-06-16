import json
import os
import unittest
from pathlib import Path

import hirehuntpilot.config as config_module
from hirehuntpilot.config import ConfigManager
from hirehuntpilot.setup import evaluate_setup, ready_for_prepare, ready_for_run


class SetupConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path("setup_test_artifacts")
        self.root.mkdir(exist_ok=True)
        self.original_home = os.environ.get("HIREHUNTPILOT_HOME")
        os.environ["HIREHUNTPILOT_HOME"] = str((self.root / "app_home").resolve())
        config_module._APP_HOME = None

    def tearDown(self) -> None:
        if self.original_home is None:
            os.environ.pop("HIREHUNTPILOT_HOME", None)
        else:
            os.environ["HIREHUNTPILOT_HOME"] = self.original_home
        config_module._APP_HOME = None
        for path in sorted(self.root.glob("**/*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        if self.root.exists():
            self.root.rmdir()

    def test_setup_state_and_nested_portal_update_persist(self) -> None:
        manager = ConfigManager()
        config = manager.bootstrap_defaults()
        manager.update("portals", {"naukri": {"email": "demo@example.com"}})
        manager.set_setup_step("profile", status="complete", detail="profile saved")
        manager.set_setup_step("portals.naukri", status="complete", detail="session saved")
        loaded = manager.load()
        self.assertEqual(loaded.portals["naukri"].email, "demo@example.com")
        self.assertEqual(loaded.setup.profile.status, "complete")
        self.assertEqual(loaded.setup.portals["naukri"].detail, "session saved")
        self.assertTrue(Path(config.resume.json_path).exists())
        self.assertIn("database", config.resume.json_path.casefold())
        self.assertIn("database", config.runtime.sqlite_path.casefold())

    def test_readiness_requires_profile_resume_and_ai_for_prepare(self) -> None:
        manager = ConfigManager()
        config = manager.bootstrap_defaults()
        ready, issues = ready_for_run(config)
        self.assertFalse(ready)
        self.assertIn("personal.email missing", issues)

        manager.update("personal", {"name": "A", "email": "a@example.com"})
        config = manager.load()
        ready, issues = ready_for_run(config)
        self.assertTrue(ready)
        self.assertEqual(issues, [])

        ready, issues = ready_for_prepare(config)
        self.assertFalse(ready)
        self.assertTrue(any(issue.startswith("ai setup incomplete") for issue in issues))

    def test_run_readiness_fails_when_all_portals_are_skipped(self) -> None:
        manager = ConfigManager()
        manager.bootstrap_defaults()
        manager.update("personal", {"name": "A", "email": "a@example.com"})
        manager.update("preferences", {"sources": []})
        ready, issues = ready_for_run(manager.load())
        self.assertFalse(ready)
        self.assertIn("no job portals enabled", issues)

    def test_evaluate_setup_reflects_skipped_optional_integrations(self) -> None:
        manager = ConfigManager()
        config = manager.bootstrap_defaults()
        manager.update("personal", {"name": "A", "email": "a@example.com"})
        checks = {check.key: check for check in evaluate_setup(manager.load())}
        self.assertTrue(checks["profile"].ok)
        self.assertTrue(checks["resume"].ok)
        self.assertTrue(checks["notifications"].ok)


if __name__ == "__main__":
    unittest.main()
