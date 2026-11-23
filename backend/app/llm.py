"""Model providers: Demo (simulated), Ollama (local) and any OpenAI-compatible API."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from dataclasses import dataclass
from typing import AsyncIterator

import httpx

from .config import settings


class ProviderError(Exception):
    """A problem the user can understand and fix."""


@dataclass
class Delta:
    text: str = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


def estimate_tokens(text: str) -> int:
    return max(1, int(len(text.split()) * 1.3))


class Provider:
    kind = "base"

    async def stream(
        self, model: str, messages: list[dict], *, temperature: float = 0.7, max_tokens: int = 120, json_mode: bool = False
    ) -> AsyncIterator[Delta]:
        raise NotImplementedError
        yield  # pragma: no cover  (makes this an async generator)

    async def list_models(self) -> list[str]:
        return []


# ====================================================================== Demo
_DEMO = {
    "advocate": [
        "The upside is real: it gives flexibility, faster progress and clear room to grow.",
        "Early benefits compound, and the people involved can start learning from real results straight away.",
        "Small steps keep this manageable, so the gains arrive well before the costs do.",
    ],
    "critic": [
        "The costs are underestimated. Complexity, time and upkeep add up quickly for a small team.",
        "The Advocate assumes everything goes smoothly, but there is no plan for what happens when it does not.",
        "A simpler option delivers most of the value with far less to maintain.",
    ],
    "risk": [
        "The main risk is committing time and budget before the approach has been proven.",
        "Ongoing maintenance and support effort is the cost most often forgotten.",
        "If priorities change, switching away later becomes slow and expensive.",
    ],
    "evidence": [
        "Claim: Benefits outweigh costs. Label: unsupported. The claim lacks cited empirical sources or benchmarks.",
        "Claim: Upkeep effort adds up quickly. Label: supported. High operational overhead for small teams is well-documented.",
        "Claim: A simpler option delivers most value. Label: contradicted. Complex workflows in production frequently invalidate oversimplified designs.",
    ],
}
_DEMO_ANSWERS = [
    ("Not now", "Start small and revisit once the basics are proven.", 80),
    ("Yes, start small", "Proceed in small steps and measure results early.", 72),
    ("It depends", "Decide after checking cost, time and team capacity.", 64),
    ("Not yet", "Prepare first, then commit when the risks are lower.", 76),
]


class DemoProvider(Provider):
    """Simulated agents. No model, no internet, no key. Output is scripted, not real reasoning."""

    kind = "demo"

    async def stream(self, model, messages, *, temperature=0.7, max_tokens=120, json_mode=False):
        system = messages[0]["content"]
        user = messages[-1]["content"]
        role = re.search(r"\[ROLE:(\w+)\]", system)
        role = role.group(1) if role else "advocate"
        seed = int(hashlib.sha1(user.split("DEBATE SO FAR")[0].encode()).hexdigest()[:8], 16)
        rnd = re.search(r"ROUND: (\d+)", user)
        round_no = int(rnd.group(1)) if rnd else 1
        qa = "[MODE:qa]" in system

        if role == "judge":
            if qa:
                text = json.dumps({"final_answer": self._qa_answer(user)})
            else:
                ans, summary, conf = _DEMO_ANSWERS[seed % len(_DEMO_ANSWERS)]
                text = json.dumps({
                    "answer": ans, "summary": summary, "confidence": conf,
                    "scores": {"advocate": 6 + seed % 2, "critic": 7 + (seed >> 2) % 2,
                               "evidence": 6 + (seed >> 3) % 3, "risk": 5 + (seed >> 4) % 3},
                })
            await asyncio.sleep(settings.demo_word_delay * 6)
        elif qa:
            text = "Answer: " + self._qa_answer(user)
        else:
            options = _DEMO[role if role in _DEMO else "advocate"]
            text = options[(round_no - 1 + seed) % len(options)]

        words = text.split(" ")
        for i, w in enumerate(words):
            yield Delta(text=w + (" " if i < len(words) - 1 else ""))
            await asyncio.sleep(settings.demo_word_delay)
        prompt = sum(estimate_tokens(m["content"]) for m in messages)
        yield Delta(prompt_tokens=prompt, completion_tokens=estimate_tokens(text))

    @staticmethod
    def _qa_answer(user: str) -> str:
        nums = re.findall(r"-?\d+(?:\.\d+)?", user.split("DEBATE SO FAR")[0])
        return nums[0] if nums else "0"


# ====================================================================== Ollama
class OllamaProvider(Provider):
    kind = "ollama"
    _cache: tuple[float, list[str]] | None = None

    async def list_models(self) -> list[str]:
        now = time.monotonic()
        if self._cache and now - self._cache[0] < 5:
            return self._cache[1]
        names: list[str] = []
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(2.0)) as client:
                r = await client.get(f"{settings.ollama_base_url}/api/tags")
                r.raise_for_status()
                for m in r.json().get("models", []):
                    name = m.get("name") or m.get("model")
                    if name and "embed" not in name.lower():
                        names.append(name)
        except Exception:
            names = []
        OllamaProvider._cache = (now, names)
        return names

    async def stream(self, model, messages, *, temperature=0.7, max_tokens=120, json_mode=False):
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "keep_alive": "10m",
            "options": {"temperature": temperature, "num_predict": max_tokens, "num_ctx": settings.ollama_num_ctx},
        }
        if json_mode:
            payload["format"] = "json"
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=5.0)) as client:
                async with client.stream("POST", f"{settings.ollama_base_url}/api/chat", json=payload) as r:
                    if r.status_code != 200:
                        body = (await r.aread()).decode("utf-8", "ignore")[:200]
                        raise ProviderError(f"Ollama returned {r.status_code}: {body}")
                    async for line in r.aiter_lines():
                        if not line.strip():
                            continue
                        data = json.loads(line)
                        if data.get("error"):
                            raise ProviderError(f"Ollama error: {data['error']}")
                        content = (data.get("message") or {}).get("content")
                        if content:
                            yield Delta(text=content)
                        if data.get("done"):
                            yield Delta(
                                prompt_tokens=data.get("prompt_eval_count"),
                                completion_tokens=data.get("eval_count"),
                            )
        except httpx.ConnectError:
            raise ProviderError(f"Cannot reach Ollama at {settings.ollama_base_url}. Is Ollama running?")
        except httpx.TimeoutException:
            raise ProviderError("The model took too long to answer. Try a smaller model.")


# ====================================================================== OpenAI-compatible
class OpenAICompatProvider(Provider):
    kind = "cloud"

    async def list_models(self) -> list[str]:
        return [settings.llm_model] if settings.cloud_ready else []

    async def stream(self, model, messages, *, temperature=0.7, max_tokens=120, json_mode=False):
        headers = {"Authorization": f"Bearer {settings.llm_api_key}", "Content-Type": "application/json"}
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream_options": {"include_usage": True},
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=8.0)) as client:
                async with client.stream("POST", f"{settings.llm_base_url}/chat/completions", json=payload, headers=headers) as r:
                    if r.status_code == 401:
                        raise ProviderError("The cloud API rejected the key (401). Check LLM_API_KEY in backend/.env.")
                    if r.status_code == 429:
                        raise ProviderError("The cloud API is rate limiting requests (429). Wait a moment and retry.")
                    if r.status_code != 200:
                        body = (await r.aread()).decode("utf-8", "ignore")[:200]
                        raise ProviderError(f"Cloud API returned {r.status_code}: {body}")
                    async for line in r.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        chunk = line[5:].strip()
                        if chunk == "[DONE]":
                            break
                        try:
                            data = json.loads(chunk)
                        except json.JSONDecodeError:
                            continue
                        for choice in data.get("choices") or []:
                            content = (choice.get("delta") or {}).get("content")
                            if content:
                                yield Delta(text=content)
                        usage = data.get("usage")
                        if usage:
                            yield Delta(prompt_tokens=usage.get("prompt_tokens"), completion_tokens=usage.get("completion_tokens"))
        except httpx.ConnectError:
            raise ProviderError(f"Cannot reach the cloud API at {settings.llm_base_url}.")
        except httpx.TimeoutException:
            raise ProviderError("The cloud API took too long to answer.")


demo = DemoProvider()
ollama = OllamaProvider()
cloud = OpenAICompatProvider()


# ====================================================================== model resolution
@dataclass
class Resolved:
    debater: Provider
    debater_model: str
    judge: Provider
    judge_model: str
    simulated: bool
    note: str

    @property
    def is_real(self) -> bool:
        return not self.simulated


def _pick_judge(models: list[str], debater: str) -> str:
    for m in models:
        if m != debater:
            return m
    return debater


def _note(r_debater: str, r_judge: str) -> str:
    return "judge: same model" if r_debater == r_judge else f"judge: {r_judge}"


async def available_models() -> list[dict]:
    items = [{"id": "auto", "label": "Auto"}, {"id": "demo", "label": "Demo"}]
    for name in await ollama.list_models():
        items.append({"id": f"ollama:{name}", "label": name})
    if settings.cloud_ready:
        items.append({"id": f"cloud:{settings.llm_model}", "label": settings.llm_model})
    return items


async def resolve(model_id: str) -> Resolved:
    model_id = (model_id or "auto").strip()
    if model_id == "demo":
        return Resolved(demo, "demo", demo, "demo", True, "demo mode (simulated)")

    local = await ollama.list_models()

    if model_id.startswith("ollama:"):
        name = model_id[7:]
        if name not in local:
            if not local:
                raise ProviderError(f"Cannot reach Ollama at {settings.ollama_base_url}. Is Ollama running?")
            raise ProviderError(f"Ollama model '{name}' is not installed. Run: ollama pull {name}")
        judge = _pick_judge(local, name)
        return Resolved(ollama, name, ollama, judge, False, _note(name, judge))

    if model_id.startswith("cloud:"):
        if not settings.cloud_ready:
            raise ProviderError("No cloud model is configured. Set LLM_API_KEY and LLM_MODEL in backend/.env.")
        judge = settings.llm_judge_model or settings.llm_model
        return Resolved(cloud, settings.llm_model, cloud, judge, False, _note(settings.llm_model, judge))

    # auto
    if local:
        debater = _preferred(local)
        judge = _pick_judge(local, debater)
        return Resolved(ollama, debater, ollama, judge, False, _note(debater, judge))
    if settings.cloud_ready:
        judge = settings.llm_judge_model or settings.llm_model
        return Resolved(cloud, settings.llm_model, cloud, judge, False, _note(settings.llm_model, judge))
    return Resolved(demo, "demo", demo, "demo", True, "demo mode (simulated)")


def _preferred(models: list[str]) -> str:
    """Prefer a small, fast general model when several are installed."""
    for key in ("llama3.2", "qwen2.5", "llama3.1", "gemma", "phi", "mistral"):
        for m in models:
            if key in m.lower():
                return m
    return models[0]
