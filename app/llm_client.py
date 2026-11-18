"""Thin LLM client. Provider chosen by LLM_PROVIDER: replay | gemini | groq.

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
        if self.index >= len(self.calls):
            raise RuntimeError("this replay has no further recorded model output "
                               "(switch to a live provider to ask again)")
        out = self.calls[self.index]
        self.index += 1
        return json.dumps(out)


class GeminiClient:
    name = "gemini"

    def __init__(self, model: str = None):
        from google import genai
        self.client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

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

    def __init__(self, model: str = None):
        from groq import Groq
        self.client = Groq(api_key=os.environ["GROQ_API_KEY"])
        self.model = model or os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

    def generate(self, system: str, user: str) -> str:
        resp = self.client.chat.completions.create(
            model=self.model, temperature=TEMPERATURE,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
        return resp.choices[0].message.content


def make_client(provider: str, scenario_id: str = "scenario_2", model: str = None):
    provider = (provider or "replay").lower()
    if provider == "replay":
        return ReplayClient(scenario_id)
    if provider == "gemini":
        return GeminiClient(model)
    if provider == "groq":
        return GroqClient(model)
    raise ValueError(f"Unknown LLM_PROVIDER: {provider}")


# ---------------- Model lists (live, from each provider's API) ----------------

DEFAULT_MODEL_ENV = {"groq": "GROQ_MODEL", "gemini": "GEMINI_MODEL"}
WORKING_MODELS_FILE = ROOT / "data" / "working_models.json"
# Groq also serves speech, text-to-speech and safety-classifier models; they cannot produce a plan.
GROQ_EXCLUDE = ("whisper", "tts", "playai", "guard", "prompt-guard", "distil", "orpheus")
# Gemini also lists embedding, image, audio and live-streaming models.
GEMINI_EXCLUDE = ("embedding", "image", "tts", "audio", "live", "aqa", "imagen", "veo", "learnlm")


def filter_groq_models(models) -> list:
    """Keep active chat models. `models` are objects or dicts with id and (optionally) active."""
    out = []
    for m in models:
        mid = m["id"] if isinstance(m, dict) else m.id
        active = (m.get("active", True) if isinstance(m, dict) else getattr(m, "active", True))
        if active is not False and not any(x in mid.lower() for x in GROQ_EXCLUDE):
            out.append(mid)
    return sorted(set(out))


def filter_gemini_models(models) -> list:
    """Keep Gemini models that support generateContent; strip the 'models/' prefix."""
    out = []
    for m in models:
        name = m["name"] if isinstance(m, dict) else m.name
        actions = (m.get("supported_actions") if isinstance(m, dict) else getattr(m, "supported_actions", None)) or []
        short = name.split("/", 1)[-1]
        if "generateContent" in actions and short.startswith("gemini") and \
                not any(x in short.lower() for x in GEMINI_EXCLUDE):
            out.append(short)
    return sorted(set(out), reverse=True)  # newer version numbers first


def list_models(provider: str) -> list:
    """Ask the provider which models are available now. Raises on missing key or network failure."""
    provider = provider.lower()
    if provider == "groq":
        from groq import Groq
        return filter_groq_models(Groq(api_key=os.environ["GROQ_API_KEY"]).models.list().data)
    if provider == "gemini":
        from google import genai
        return filter_gemini_models(genai.Client(api_key=os.environ["GEMINI_API_KEY"]).models.list())
    return []


def load_working_models(path: Path = WORKING_MODELS_FILE) -> dict:
    """{provider: {model: how and when it was verified}} for models that produced a valid plan end to end."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if not k.startswith("_")}


def selectable_models(provider: str, live=None, working=None) -> list:
    """Verified models for this provider, kept only if the provider still serves them (when the live list is known)."""
    working = load_working_models() if working is None else working
    verified = list(working.get(provider, {}))
    return [m for m in verified if live is None or m in live]


def default_model(provider: str) -> str:
    env = DEFAULT_MODEL_ENV.get(provider)
    return os.getenv(env, "") if env else ""
