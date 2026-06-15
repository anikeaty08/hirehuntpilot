from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from hirehuntpilot.ai.adapter import AIAdapter
from hirehuntpilot.config import app_home
from hirehuntpilot.models import ApplicationStatus, ArtifactRecord, TaskRecord, TaskType
from hirehuntpilot.resume.builder import load_resume_data, render_resume_text, render_resume_text_data, write_rendercv_yaml
from hirehuntpilot.resume.extractor import extract_pdf_text


class ResumeAgent:
    def __init__(self, ai: AIAdapter) -> None:
        self.ai = ai

    def handles(self) -> set[TaskType]:
        return {TaskType.PREPARE_APPLICATION}

    def process(self, task: TaskRecord, supervisor) -> None:
        job_id = task.payload["job_id"]
        job = supervisor.state.get_job(job_id)
        application = supervisor.state.get_application(job_id)
        if not job or not application:
            raise ValueError(f"missing state for {job_id}")
        resume_data = self._load_resume_data(supervisor)
        tailored_data = self.ai.tailor_resume_content(job, resume_data)
        tailored_text = render_resume_text_data(tailored_data)
        cover_letter = self.ai.generate_cover_letter(job, tailored_text)

        output_dir = app_home() / "resumes"
        output_dir.mkdir(parents=True, exist_ok=True)
        safe_job_id = self._safe_name(job_id)
        resume_path = output_dir / f"resume_{safe_job_id}.txt"
        cover_letter_path = output_dir / f"cover_{safe_job_id}.txt"
        resume_path.write_text(tailored_text, encoding="utf-8")
        cover_letter_path.write_text(cover_letter, encoding="utf-8")

        supervisor.state.add_artifact(ArtifactRecord(job_id=job_id, artifact_type="tailored_resume", path=str(resume_path)))
        supervisor.state.add_artifact(ArtifactRecord(job_id=job_id, artifact_type="cover_letter", path=str(cover_letter_path)))
        self._generate_rendercv(supervisor, safe_job_id, job_id, tailored_data)
        application.status = ApplicationStatus.READY_TO_APPLY
        application.resume_version = f"resume_{safe_job_id}.pdf"
        application.notes = "job-specific rendercv resume prepared"
        supervisor.state.upsert_application(application)
        supervisor.enqueue(TaskType.SYNC_TRACKING, {"job_id": job_id}, job_id=job_id)

    def _load_resume_text(self, supervisor) -> str:
        config = supervisor.config.resume
        resume_json_path = Path(config.json_path)
        base_pdf_path = Path(config.base_pdf_path)
        if resume_json_path.exists():
            rendered = render_resume_text(resume_json_path)
            if rendered:
                return rendered
            return resume_json_path.read_text(encoding="utf-8")
        if base_pdf_path.exists():
            extracted = extract_pdf_text(base_pdf_path)
            if extracted:
                return extracted
        return "{}"

    def _load_resume_data(self, supervisor) -> dict:
        config = supervisor.config.resume
        resume_json_path = Path(config.json_path)
        if resume_json_path.exists():
            data = load_resume_data(resume_json_path)
            if data:
                return data
        resume_text = self._load_resume_text(supervisor)
        return {"summary": resume_text}

    def _generate_rendercv(self, supervisor, safe_job_id: str, job_id: str, tailored_data: dict) -> None:
        binary = shutil.which("rendercv")
        if not binary and not sys.executable:
            raise RuntimeError("rendercv CLI is required but was not found")
        configured_path = Path(supervisor.config.resume.rendercv_path)
        output_dir = configured_path.parent if configured_path.parent != Path(".") else app_home() / "resumes"
        stem = configured_path.stem or "resume_rendercv"
        yaml_path = output_dir / f"{stem}_{safe_job_id}.yaml"
        pdf_path = output_dir / f"resume_{safe_job_id}.pdf"
        output_dir.mkdir(parents=True, exist_ok=True)
        self._write_rendercv_from_data(supervisor, yaml_path, tailored_data)
        supervisor.state.add_artifact(ArtifactRecord(job_id=job_id, artifact_type="rendercv_yaml", path=str(yaml_path)))
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "rendercv",
                "render",
                str(yaml_path),
                "--pdf-path",
                pdf_path.name,
                "--dont-generate-html",
                "--dont-generate-markdown",
                "--dont-generate-png",
                "--quiet",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "rendercv render failed")
        if not pdf_path.exists():
            raise RuntimeError(f"rendercv did not produce expected PDF: {pdf_path}")
        supervisor.state.add_artifact(ArtifactRecord(job_id=job_id, artifact_type="rendercv_pdf", path=str(pdf_path)))

    def _write_rendercv_from_data(self, supervisor, output_path: Path, tailored_data: dict) -> None:
        temp_json_path = output_path.with_suffix(".json")
        temp_json_path.write_text(json.dumps(tailored_data, indent=2), encoding="utf-8")
        write_rendercv_yaml(
            temp_json_path,
            output_path,
            supervisor.config.personal,
            supervisor.config.resume,
        )
        temp_json_path.unlink(missing_ok=True)

    def _safe_name(self, value: str) -> str:
        return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)
