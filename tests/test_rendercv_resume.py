import unittest

from hirehuntpilot.ai.adapter import AIAdapter
from hirehuntpilot.config import AIConfig, PersonalConfig, ResumeConfig
from hirehuntpilot.models import JobRecord
from hirehuntpilot.resume.builder import build_rendercv_payload


class RenderCvResumeTests(unittest.TestCase):
    def test_build_rendercv_payload_maps_structured_resume(self) -> None:
        resume_data = {
            "name": "Jane Doe",
            "summary": "Backend engineer focused on Python systems.",
            "skills": ["python", "sql"],
            "experience": [{"company": "Acme", "position": "Engineer", "summary": "Built APIs"}],
            "projects": [{"name": "Pipeline", "summary": "Automated resume generation"}],
            "education": [{"institution": "State U", "area": "Computer Science"}],
        }
        payload = build_rendercv_payload(
            resume_data,
            PersonalConfig(email="jane@example.com", github="https://github.com/janedoe"),
            ResumeConfig(rendercv_theme="moderncv"),
        )
        self.assertEqual(payload["design"]["theme"], "moderncv")
        self.assertEqual(payload["cv"]["name"], "Jane Doe")
        self.assertIn("Experience", payload["cv"]["sections"])
        self.assertIn("Skills", payload["cv"]["sections"])

    def test_fallback_tailor_resume_content_selects_ranked_entries(self) -> None:
        adapter = AIAdapter(AIConfig(provider="none"))
        job = JobRecord(
            source_job_id="1",
            title="Python Automation Engineer",
            company="Example",
            source="demo",
            job_url="https://example.com/job",
            description="Looking for python automation and api experience",
            skills=["python", "automation", "api"],
        )
        resume_data = {
            "name": "Jane Doe",
            "summary": "Generalist engineer.",
            "skills": ["python", "excel", "automation", "support"],
            "experience": [
                {"company": "A", "position": "Engineer", "summary": "Built python automation flows"},
                {"company": "B", "position": "Support", "summary": "Handled customer tickets"},
            ],
        }
        tailored = adapter.tailor_resume_content(job, resume_data)
        self.assertIn("python", " ".join(tailored["skills"]).casefold())
        self.assertEqual(tailored["experience"][0]["company"], "A")


if __name__ == "__main__":
    unittest.main()
