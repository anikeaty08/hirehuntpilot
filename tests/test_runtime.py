import csv
import json
import os
import unittest
from pathlib import Path

from hirehuntpilot.browser.session import BrowserSessionManager
import hirehuntpilot.config as config_module
from hirehuntpilot.config import AppConfig, app_home
from hirehuntpilot.models import ApplicationStatus, TaskType
from hirehuntpilot.runtime import build_supervisor


class RuntimeFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path("runtime_test_artifacts")
        self.root.mkdir(exist_ok=True)
        self.original_home = os.environ.get("HIREHUNTPILOT_HOME")
        os.environ["HIREHUNTPILOT_HOME"] = str((self.root / "app_home").resolve())
        config_module._APP_HOME = None
        self.resume_json = self.root / "resume.json"
        self.resume_json.write_text(
            json.dumps(
                {
                    "name": "A",
                    "summary": "Python developer",
                    "skills": ["python", "sql", "automation"],
                    "experience": [{"company": "DemoCo", "position": "Engineer", "summary": "Built automation flows"}],
                    "projects": [{"name": "Resume Builder", "summary": "Generated tailored resumes"}],
                    "education": [{"institution": "Demo University", "area": "Computer Science"}],
                }
            ),
            encoding="utf-8",
        )
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir(exist_ok=True)
        self.rendercv_cmd = self.bin_dir / "rendercv.cmd"
        self.rendercv_cmd.write_text(
            "@echo off\n"
            "if not exist \"%~4\" mkdir \"%~4\"\n"
            "echo pdf>\"%~4\\%~n2.pdf\"\n",
            encoding="utf-8",
        )
        self.original_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{self.bin_dir};{self.original_path}"

    def tearDown(self) -> None:
        os.environ["PATH"] = self.original_path
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

    def _config(self) -> AppConfig:
        config = AppConfig()
        config.runtime.sqlite_path = str(self.root / "runtime.db")
        config.resume.json_path = str(self.resume_json)
        config.resume.rendercv_path = str(self.root / "rendercv" / "resume.yaml")
        config.preferences.role = "python developer"
        config.preferences.cities = ["Bengaluru"]
        config.preferences.sources = ["naukri", "internshala"]
        return config

    def test_end_to_end_local_flow(self) -> None:
        supervisor = build_supervisor(self._config())
        supervisor.enqueue(
            TaskType.SEARCH_SOURCES,
            {"query": "python developer", "cities": ["Bengaluru"], "sources": ["naukri"], "limit": 2},
        )
        supervisor.run_until_idle()
        qualified = [item for item in supervisor.state.list_applications() if item.status is ApplicationStatus.QUALIFIED]
        self.assertTrue(qualified)

        for item in qualified:
            supervisor.enqueue(TaskType.PREPARE_APPLICATION, {"job_id": item.job_id}, job_id=item.job_id)
        supervisor.run_until_idle()
        ready = [item for item in supervisor.state.list_applications() if item.status is ApplicationStatus.READY_TO_APPLY]
        self.assertTrue(ready)

        for item in ready:
            supervisor.enqueue(TaskType.DRY_RUN_APPLICATION, {"job_id": item.job_id}, job_id=item.job_id)
        supervisor.run_until_idle()
        dry = [item for item in supervisor.state.list_applications() if item.status is ApplicationStatus.DRY_RUN_ONLY]
        self.assertTrue(dry)

        for item in dry:
            supervisor.enqueue(TaskType.SUBMIT_APPLICATION, {"job_id": item.job_id}, job_id=item.job_id)
        supervisor.run_until_idle()
        applied = [item for item in supervisor.state.list_applications() if item.status is ApplicationStatus.APPLIED]
        self.assertTrue(applied)

    def test_local_ledger_written(self) -> None:
        supervisor = build_supervisor(self._config())
        supervisor.enqueue(
            TaskType.SEARCH_SOURCES,
            {"query": "python developer", "cities": ["Bengaluru"], "sources": ["naukri"], "limit": 1},
        )
        supervisor.run_until_idle()
        ledger = app_home() / "applications.csv"
        self.assertTrue(ledger.exists())
        with ledger.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertTrue(rows)

    def test_notification_log_written(self) -> None:
        supervisor = build_supervisor(self._config())
        supervisor.enqueue(TaskType.SEND_NOTIFICATION, {"message": "test notification"})
        supervisor.run_until_idle()
        log_file = app_home() / "logs" / "notifications.log"
        self.assertTrue(log_file.exists())
        self.assertIn("test notification", log_file.read_text(encoding="utf-8"))

    def test_session_refresh_creates_stub(self) -> None:
        manager = BrowserSessionManager()
        ok, detail = manager.refresh_session("naukri", email="demo@example.com", headed=True)
        self.assertTrue(ok)
        self.assertTrue(Path(detail).exists())


if __name__ == "__main__":
    unittest.main()
