from __future__ import annotations

import json
import re
from typing import Any

from hirehuntpilot.config import AIConfig
from hirehuntpilot.models import JobRecord


class AIAdapter:
    def __init__(self, config: AIConfig) -> None:
        self.config = config

    def tailor_resume(self, job: JobRecord, resume_text: str) -> str:
        prompt = (
            "Tailor this resume conservatively for the role. Keep claims truthful, "
            "front-load matching keywords, and do not invent experience.\n\n"
            f"Role: {job.title}\nCompany: {job.company}\nDescription: {job.description}\n\nResume:\n{resume_text}"
        )
        return self._generate(prompt, fallback=self._fallback_resume(job, resume_text))

    def parse_resume_text(self, resume_text: str) -> dict[str, Any]:
        fallback = self._fallback_parse_resume_text(resume_text)
        provider = self.config.provider.casefold()
        if provider in {"", "none"}:
            return fallback
        prompt = (
            "You are converting a raw pasted resume into structured JSON for a job application CLI.\n"
            "Return JSON only. Fix spelling conservatively, normalize formatting, and do not invent facts.\n"
            "Use this shape:\n"
            '{"name":"","headline":"","summary":"","skills":[],"experience":[],"projects":[],"education":[]}\n\n'
            f"Resume text:\n{resume_text}"
        )
        try:
            raw = self._generate(prompt, fallback="")
            parsed = self._parse_json_payload(raw)
        except Exception:
            return fallback
        if not isinstance(parsed, dict):
            return fallback
        return self._merge_resume_payload(fallback, parsed)

    def chat_response(self, message: str, *, context: str = "") -> str:
        provider = self.config.provider.casefold()
        fallback = (
            "Available actions: paste resume text with /resume, then use /run, /prepare, /apply dry-run, "
            "/apply commit, /status, /doctor, or /verify."
        )
        if provider in {"", "none"}:
            return fallback
        prompt = (
            "You are the CLI copilot for a job-application agent.\n"
            "Reply concisely. Focus on what the user can do next in the CLI.\n\n"
            f"Context:\n{context}\n\n"
            f"User message:\n{message}"
        )
        return self._generate(prompt, fallback=fallback)

    def plan_chat_action(self, message: str, *, context: str = "") -> dict[str, Any]:
        fallback = self._fallback_chat_action(message)
        provider = self.config.provider.casefold()
        if provider in {"", "none"}:
            return fallback
        prompt = (
            "You are converting a CLI chat request into structured automation intent.\n"
            "Return JSON only with this shape:\n"
            '{"intent":"chat|search|search_apply|prepare|apply|status|doctor|verify","role":"","city":"","limit":25,"commit":false,"missing":[]}\n'
            "Only include facts that are explicit or strongly implied. If something essential is missing, list it in missing.\n\n"
            f"Context:\n{context}\n\n"
            f"User message:\n{message}"
        )
        try:
            raw = self._generate(prompt, fallback="")
            parsed = self._parse_json_payload(raw)
        except Exception:
            return fallback
        if not isinstance(parsed, dict):
            return fallback
        merged = dict(fallback)
        merged.update(parsed)
        missing = merged.get("missing", [])
        merged["missing"] = missing if isinstance(missing, list) else []
        merged = self._normalize_action(message, merged)
        return merged

    def normalize_resume_profile(self, resume_data: dict[str, Any]) -> dict[str, Any]:
        provider = self.config.provider.casefold()
        if provider in {"", "none"}:
            return resume_data
        prompt = (
            "You are cleaning a candidate profile for resume generation.\n"
            "Return JSON only. Fix spelling, normalize formatting, and improve clarity conservatively. "
            "Do not invent achievements, dates, roles, metrics, or skills.\n\n"
            "Keep the same top-level structure and preserve factual content.\n\n"
            f"Profile:\n{json.dumps(resume_data, ensure_ascii=True)}"
        )
        try:
            raw = self._generate(prompt, fallback="")
            parsed = self._parse_json_payload(raw)
        except Exception:
            return resume_data
        if not isinstance(parsed, dict):
            return resume_data
        merged = dict(resume_data)
        for key, value in parsed.items():
            if key in merged:
                merged[key] = value
        return merged

    def tailor_resume_content(self, job: JobRecord, resume_data: dict[str, Any]) -> dict[str, Any]:
        fallback = self._fallback_resume_content(job, resume_data)
        provider = self.config.provider.casefold()
        if provider in {"", "none"}:
            return fallback
        prompt = (
            "You are tailoring a resume for a job application.\n"
            "Return JSON only. Use only facts already present in the source resume data. "
            "You may reorder, omit, compress, and rewrite wording conservatively, but do not invent achievements.\n\n"
            "Required JSON shape:\n"
            '{"name":"","headline":"","summary":"","skills":[],"experience":[],"projects":[],"education":[]}\n\n'
            f"Job:\n{json.dumps(job.to_dict(), ensure_ascii=True)}\n\n"
            f"Source resume data:\n{json.dumps(resume_data, ensure_ascii=True)}"
        )
        try:
            raw = self._generate(prompt, fallback="")
            parsed = self._parse_json_payload(raw)
        except Exception:
            return fallback
        if not isinstance(parsed, dict):
            return fallback
        return self._merge_resume_payload(fallback, parsed)

    def generate_cover_letter(self, job: JobRecord, resume_text: str) -> str:
        prompt = (
            "Write a concise 3 paragraph cover letter grounded in the resume.\n\n"
            f"Role: {job.title}\nCompany: {job.company}\nDescription: {job.description}\n\nResume:\n{resume_text}"
        )
        fallback = (
            f"Dear Hiring Team,\n\nI am applying for the {job.title} role at {job.company}. "
            "My background aligns with the role requirements, and I have attached a tailored resume.\n\n"
            "I would value the chance to discuss how my experience can contribute to your team.\n\nRegards"
        )
        return self._generate(prompt, fallback=fallback)

    def answer_question(self, question: str, job: JobRecord, resume_text: str) -> str:
        prompt = (
            "Answer this application question honestly in under 150 words.\n\n"
            f"Question: {question}\nRole: {job.title}\nCompany: {job.company}\nResume:\n{resume_text}"
        )
        fallback = f"My experience and projects align with the {job.title} role, and I can discuss relevant details based on the attached resume."
        return self._generate(prompt, fallback=fallback)

    def _generate(self, prompt: str, *, fallback: str) -> str:
        provider = self.config.provider.casefold()
        try:
            if provider == "openai":
                return self._openai(prompt)
            if provider == "local":
                return self._local(prompt)
            if provider == "groq":
                return self._groq(prompt)
            if provider == "anthropic":
                return self._anthropic(prompt)
            if provider == "google":
                return self._google(prompt)
            if provider == "mistral":
                return self._mistral(prompt)
            if provider in {"none", ""}:
                return fallback
        except Exception:
            return fallback
        return fallback

    def healthcheck(self) -> tuple[bool, str]:
        provider = self.config.provider.casefold()
        if provider in {"", "none"}:
            return True, "no provider configured; fallback prompts only"
        if provider != "local" and not self.config.api_key:
            return False, f"{provider} missing api key"
        try:
            output = self._generate("Reply with exactly: ok", fallback="")
        except Exception as exc:  # pragma: no cover - network/provider dependent
            return False, str(exc)
        if not output.strip():
            return False, f"{provider} returned empty output"
        return True, f"{provider} model check ok"

    def _openai(self, prompt: str) -> str:
        from openai import OpenAI

        client = OpenAI(api_key=self.config.api_key, base_url=self.config.base_url or None)
        response = client.responses.create(
            model=self.config.model or "gpt-4o-mini",
            input=prompt,
        )
        return getattr(response, "output_text", "") or ""

    def _groq(self, prompt: str) -> str:
        from groq import Groq

        client = Groq(api_key=self.config.api_key)
        response = client.chat.completions.create(
            model=self.config.model or "llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content or ""

    def _anthropic(self, prompt: str) -> str:
        from anthropic import Anthropic

        client = Anthropic(api_key=self.config.api_key)
        response = client.messages.create(
            model=self.config.model or "claude-3-5-sonnet-latest",
            max_tokens=128,
            messages=[{"role": "user", "content": prompt}],
        )
        parts = []
        for block in getattr(response, "content", []):
            text = getattr(block, "text", "")
            if text:
                parts.append(text)
        return "\n".join(parts)

    def _google(self, prompt: str) -> str:
        import google.generativeai as genai

        genai.configure(api_key=self.config.api_key)
        model = genai.GenerativeModel(self.config.model or "gemini-1.5-flash")
        response = model.generate_content(prompt)
        return getattr(response, "text", "") or ""

    def _mistral(self, prompt: str) -> str:
        import requests

        response = requests.post(
            (self.config.base_url or "https://api.mistral.ai") + "/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.config.model or "mistral-small-latest",
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        return payload["choices"][0]["message"]["content"]

    def _local(self, prompt: str) -> str:
        from openai import OpenAI

        client = OpenAI(
            api_key=self.config.api_key or "local",
            base_url=self.config.base_url or "http://localhost:11434/v1",
        )
        response = client.chat.completions.create(
            model=self.config.model or "llama3.1:8b",
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content or ""

    def _fallback_resume(self, job: JobRecord, resume_text: str) -> str:
        lines = [line.rstrip() for line in resume_text.splitlines() if line.strip()]
        summary = f"Target role: {job.title} at {job.company}"
        if not lines:
            return summary
        return "\n".join([summary, "", *lines])

    def _fallback_resume_content(self, job: JobRecord, resume_data: dict[str, Any]) -> dict[str, Any]:
        keywords = self._job_keywords(job)
        tailored = {
            "name": resume_data.get("name", ""),
            "headline": self._tailored_headline(job, resume_data),
            "summary": self._tailored_summary(job, resume_data),
            "skills": self._select_skills(resume_data.get("skills"), keywords),
            "experience": self._select_ranked_entries(resume_data.get("experience"), keywords, limit=4),
            "projects": self._select_ranked_entries(resume_data.get("projects"), keywords, limit=3),
            "education": self._select_ranked_entries(resume_data.get("education"), keywords, limit=2),
        }
        return tailored

    def _merge_resume_payload(self, fallback: dict[str, Any], parsed: dict[str, Any]) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for key, default_value in fallback.items():
            value = parsed.get(key, default_value)
            if isinstance(default_value, list):
                merged[key] = value if isinstance(value, list) else default_value
            elif isinstance(default_value, str):
                merged[key] = str(value) if value is not None else default_value
            else:
                merged[key] = value
        return merged

    def _job_keywords(self, job: JobRecord) -> set[str]:
        parts = [job.title, job.company, job.description, " ".join(job.skills)]
        tokens = set()
        for part in parts:
            for raw in part.casefold().replace("/", " ").replace("-", " ").split():
                token = raw.strip(".,:;()[]{}")
                if len(token) >= 3:
                    tokens.add(token)
        return tokens

    def _tailored_headline(self, job: JobRecord, resume_data: dict[str, Any]) -> str:
        source = resume_data.get("headline") or resume_data.get("title") or ""
        return source or job.title

    def _tailored_summary(self, job: JobRecord, resume_data: dict[str, Any]) -> str:
        summary = str(resume_data.get("summary", "")).strip()
        if not summary:
            return f"Candidate aligned with {job.title} roles, emphasizing relevant experience and skills from prior work."
        return f"{summary} Targeting {job.title} opportunities with emphasis on matching experience and skills."

    def _select_skills(self, skills: Any, keywords: set[str]) -> list[str]:
        if not isinstance(skills, list):
            return []
        ranked = sorted(
            (str(skill) for skill in skills if skill),
            key=lambda skill: (self._score_text(skill, keywords), skill.casefold()),
            reverse=True,
        )
        return ranked[:8] if ranked else []

    def _select_ranked_entries(self, entries: Any, keywords: set[str], *, limit: int) -> list[Any]:
        if not isinstance(entries, list):
            return []
        scored: list[tuple[int, int, Any]] = []
        for index, entry in enumerate(entries):
            text = json.dumps(entry, ensure_ascii=True) if isinstance(entry, dict) else str(entry)
            scored.append((self._score_text(text, keywords), -index, entry))
        scored.sort(reverse=True)
        selected = [entry for _, _, entry in scored[:limit]]
        return selected or list(entries[:limit])

    def _score_text(self, text: str, keywords: set[str]) -> int:
        haystack = text.casefold()
        return sum(1 for token in keywords if token in haystack)

    def _fallback_parse_resume_text(self, resume_text: str) -> dict[str, Any]:
        lines = [line.strip() for line in resume_text.splitlines() if line.strip()]
        payload: dict[str, Any] = {
            "name": lines[0] if lines else "",
            "headline": "",
            "summary": "",
            "skills": [],
            "experience": [],
            "projects": [],
            "education": [],
        }
        section_map = {
            "summary": "summary",
            "skills": "skills",
            "experience": "experience",
            "projects": "projects",
            "education": "education",
        }
        current_section = ""
        summary_lines: list[str] = []
        for line in lines[1:]:
            key = line.casefold().rstrip(":")
            if key in section_map:
                current_section = section_map[key]
                continue
            if current_section == "summary":
                summary_lines.append(line.lstrip("- ").strip())
            elif current_section == "skills":
                value = line.split(":", 1)[-1] if ":" in line else line
                parts = [part.strip(" -") for part in value.split(",") if part.strip(" -")]
                payload["skills"].extend(parts)
            elif current_section in {"experience", "projects", "education"}:
                cleaned = line.lstrip("- ").strip()
                if not cleaned:
                    continue
                if current_section == "experience":
                    payload["experience"].append({"company": cleaned, "position": "", "summary": ""})
                elif current_section == "projects":
                    payload["projects"].append({"name": cleaned, "summary": ""})
                else:
                    payload["education"].append({"institution": cleaned, "area": "", "degree": "", "summary": ""})
            elif not payload["headline"]:
                payload["headline"] = line
            else:
                summary_lines.append(line)
        payload["summary"] = " ".join(summary_lines).strip()
        return payload

    def _fallback_chat_action(self, message: str) -> dict[str, Any]:
        lowered = message.casefold().strip()
        action = {
            "intent": "chat",
            "role": "",
            "city": "",
            "limit": 25,
            "commit": False,
            "missing": [],
            "sources": [],
        }
        count_match = re.search(r"(\d+)\s+jobs?", lowered)
        if count_match:
            action["limit"] = int(count_match.group(1))
        elif "a job" in lowered or "one job" in lowered:
            action["limit"] = 1
        if "apply" in lowered and ("search" in lowered or "find" in lowered):
            action["intent"] = "search_apply"
            action["commit"] = True
        elif "apply" in lowered:
            action["intent"] = "apply"
            action["commit"] = "commit" in lowered or "real" in lowered or "submit" in lowered
        elif "prepare" in lowered:
            action["intent"] = "prepare"
        elif "status" in lowered:
            action["intent"] = "status"
        elif "doctor" in lowered:
            action["intent"] = "doctor"
        elif "verify" in lowered or "check" in lowered:
            action["intent"] = "verify"
        elif "search" in lowered or "find me" in lowered or "find " in lowered:
            action["intent"] = "search"

        city_match = re.search(r"\bin\s+([a-zA-Z][a-zA-Z\s]+?)(?:\s+as\s+|$)", lowered)
        if city_match:
            action["city"] = city_match.group(1).strip().title()

        role_match = re.search(r"\bas\s+([a-zA-Z0-9\/\-\+\s]+)$", lowered)
        if role_match:
            action["role"] = role_match.group(1).strip()
        elif "backend" in lowered:
            action["role"] = "backend developer"
        elif "python developer" in lowered:
            action["role"] = "python developer"

        source_aliases = {
            "linkedin": "linkedin",
            "linkedln": "linkedin",
            "linkdin": "linkedin",
            "naukri": "naukri",
            "internshala": "internshala",
            "indeed": "indeed",
            "unstop": "unstop",
            "shine": "shine",
        }
        action["sources"] = [target for alias, target in source_aliases.items() if alias in lowered]
        action["sources"] = sorted(set(action["sources"]))

        if action["intent"] in {"search", "search_apply"}:
            if not action["role"]:
                action["missing"].append("role")
            if not action["city"]:
                action["missing"].append("city")
        return action

    def _normalize_action(self, message: str, action: dict[str, Any]) -> dict[str, Any]:
        lowered = message.casefold()
        normalized = dict(action)
        try:
            normalized["limit"] = max(1, int(normalized.get("limit", 25) or 25))
        except Exception:
            normalized["limit"] = 25
        if normalized["intent"] in {"search", "search_apply"} and normalized["limit"] <= 0:
            normalized["limit"] = 25
        if "a job" in lowered or "one job" in lowered:
            normalized["limit"] = 1
        if "apply" in lowered and any(term in lowered for term in ("search", "find", "job", "jobs")):
            normalized["intent"] = "search_apply"
            normalized["commit"] = True
        sources = normalized.get("sources", [])
        normalized["sources"] = [str(source).casefold() for source in sources if source]
        return normalized

    def _parse_json_payload(self, raw: str) -> Any:
        stripped = raw.strip()
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass
        if "```json" in stripped:
            segment = stripped.split("```json", 1)[1].split("```", 1)[0].strip()
            return json.loads(segment)
        if "```" in stripped:
            segment = stripped.split("```", 1)[1].split("```", 1)[0].strip()
            return json.loads(segment)
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(stripped[start : end + 1])
        raise json.JSONDecodeError("Unable to extract JSON object", raw, 0)
