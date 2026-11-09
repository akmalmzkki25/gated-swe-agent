"""Check the pinned model and decoding parameters against the live endpoint.

Makes a handful of tiny calls (a few hundred tokens) and writes configs/model_smoke.json:
which parameters were accepted, the modelVersion the API reports, token usage and the
LiteLLM cost estimate. The API key is read from .env and never printed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import litellm
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
PROMPT = [{"role": "user", "content": "Reply with exactly the word: pong"}]


def load_model_config() -> dict:
    cfg = yaml.safe_load((ROOT / "configs/model.yaml").read_text(encoding="utf-8"))
    cfg["model_name"] = os.getenv("MODEL_NAME") or cfg["model_name"]
    if os.getenv("API_BASE"):
        cfg["model_kwargs"]["api_base"] = os.environ["API_BASE"]
    return cfg


def _call(model: str, kwargs: dict) -> dict:
    try:
        r = litellm.completion(model=model, messages=PROMPT, **kwargs)
    except Exception as e:  # recorded, not raised: the point is to learn what the endpoint accepts
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}"}
    hidden = getattr(r, "_hidden_params", {}) or {}
    return {
        "ok": True,
        "text": (r.choices[0].message.content or "").strip()[:50],
        "response_model": r.model,
        # Gemini's modelVersion field, as LiteLLM surfaces it
        "model_version": hidden.get("provider_response_model"),
        "reasoning_tokens": getattr(getattr(r.usage, "completion_tokens_details", None), "reasoning_tokens", None),
        "usage": r.usage.model_dump() if r.usage else None,
        "cost_usd": litellm.completion_cost(completion_response=r),
    }


def main() -> None:
    load_dotenv(ROOT / ".env")
    if not os.getenv("GEMINI_API_KEY") and not os.getenv("API_BASE"):
        raise SystemExit("GEMINI_API_KEY is not set (put it in .env)")
    cfg = load_model_config()
    model = cfg["model_name"]
    # drop_params off here, so an unsupported parameter errors instead of vanishing silently
    base = {**cfg["model_kwargs"], "drop_params": False}
    results = {
        "model_name": model,
        "pinned_kwargs": base,
        "pinned_with_seed_0": _call(model, {**base, "seed": 0}),
        "pinned_with_seed_0_again": _call(model, {**base, "seed": 0}),
        "pinned_with_seed_1": _call(model, {**base, "seed": 1}),
    }
    for p in ("temperature", "top_p", "reasoning_effort", "seed"):
        probe = {k: v for k, v in base.items() if k != p}
        results[f"without_{p}"] = _call(model, probe)
    out = ROOT / "configs/model_smoke.json"
    out.write_text(json.dumps(results, indent=2, default=str) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
