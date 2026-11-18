"""Thin LLM client. Provider chosen by LLM_PROVIDER: replay | gemini | groq | ollama.

Every client exposes generate(system, user) -> raw text. Validation happens
elsewhere (validator.py): the model cannot enforce its own contract (L12).
"""
import json
import os
from pathlib import Path

from app.models import Plan

ROOT = Path(__file__).resolve().parent.parent
TEMPERATURE = 0.2


class ReplayClient:
    """Returns stored model outputs for a scenario, in order. No API key, deterministic."""
    name = "replay"

    def __init__(self, scenario_id: str):
        self.scenario = json.loads((ROOT / "replays" / f"{scenario_id}.json").read_text())
        self.calls = self.scenario["calls"]
        self.index = 0

    def generate(self, system: str, user: str) -> str:
        out = self.calls[min(self.index, len(self.calls) - 1)]
        self.index += 1
        return json.dumps(out)


class GeminiClient:
    name = "gemini"

    def __init__(self):
        from google import genai
        self.client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        self.model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    def generate(self, system: str, user: str) -> str:
        from google.genai import types
        config = dict(system_instruction=system, temperature=TEMPERATURE,
                      response_mime_type="application/json")
        try:  # constrained decoding where the model supports the schema
            resp = self.client.models.generate_content(
                model=self.model, contents=user,
                config=types.GenerateContentConfig(**config, response_schema=Plan))
        except Exception:  # fall back to JSON mode; the validator still checks the shape
            resp = self.client.models.generate_content(
                model=self.model, contents=user, config=types.GenerateContentConfig(**config))
        return resp.text


class GroqClient:
    name = "groq"

    def __init__(self):
        from groq import Groq
        self.client = Groq(api_key=os.environ["GROQ_API_KEY"])
        self.model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

    def generate(self, system: str, user: str) -> str:
        resp = self.client.chat.completions.create(
            model=self.model, temperature=TEMPERATURE,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
        return resp.choices[0].message.content


class OllamaClient:
    name = "ollama"

    def __init__(self):
        import ollama
        self.ollama = ollama
        self.model = os.getenv("OLLAMA_MODEL", "qwen3:8b")

    def generate(self, system: str, user: str) -> str:
        resp = self.ollama.chat(model=self.model, format=Plan.model_json_schema(),
                                options={"temperature": TEMPERATURE},
                                messages=[{"role": "system", "content": system},
                                          {"role": "user", "content": user}])
        return resp.message.content


def make_client(provider: str, scenario_id: str = "scenario_2"):
    provider = (provider or "replay").lower()
    if provider == "replay":
        return ReplayClient(scenario_id)
    if provider == "gemini":
        return GeminiClient()
    if provider == "groq":
        return GroqClient()
    if provider == "ollama":
        return OllamaClient()
    raise ValueError(f"Unknown LLM_PROVIDER: {provider}")
