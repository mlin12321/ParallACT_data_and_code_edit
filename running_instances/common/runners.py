"""Factory: (harness, model_key) -> a Runner pointed at that model's vLLM endpoint.

Each runner gets its own per-model config (claude ~/.claude-<key>, opencode
opencode_configs/<key>.json; codex uses a fresh home per turn) so concurrent runs
of different models don't collide.
"""

from __future__ import annotations

import pathlib

import os

from endpoints import ENDPOINTS, get
from engine.runner.claude_code import ClaudeCodeRunner
from engine.runner.codex import CodexRunner
from engine.runner.director import DirectorRunner
from engine.runner.opencode import OpencodeRunner

HARNESSES = ("claude", "codex", "opencode", "director")
_HERE = pathlib.Path(__file__).resolve().parent
_REPO = _HERE.parent.parent


def _director_model(model_key: str) -> tuple[str, str | None, str]:
    """(LiteLLM model, base URL, output-namespace name) for the director.

    A key of the endpoint table is that vLLM model; anything else is a LiteLLM
    model name used as it is, e.g. `anthropic/claude-sonnet-5-5`.
    """
    if model_key in ENDPOINTS:
        ep = get(model_key)
        return f"openai/{ep.served_name}", ep.openai_base, ep.served_name
    return model_key, os.environ.get("DIRECTOR_BASE_URL"), model_key.split("/")[-1]


def _director_runner(model_key: str, timeout: int) -> DirectorRunner:
    """The director, set up from the environment:

    DIRECTOR_SDK         software-director-sdk checkout (default: beside this repo)
    DIRECTOR_BENCH       director-bench checkout (default: beside this repo)
    DIRECTOR_API_KEY_ENV name of the variable with the API key (ANTHROPIC_API_KEY)
    DIRECTOR_MAX_DEPTH   most levels of teams; 1 forbids sub-teams (a solo run)
    DIRECTOR_COST_LIMIT  dollars one turn may spend
    DIRECTOR_BUDGET_FILE, DIRECTOR_BUDGET_USD  a cap shared by every turn
    """
    model, base_url, served = _director_model(model_key)
    env = os.environ.get
    depth = env("DIRECTOR_MAX_DEPTH")
    return DirectorRunner(
        model,
        name=f"director__{served}",
        sdk=env("DIRECTOR_SDK") or str(_REPO.parent / "software-director-sdk"),
        bench=env("DIRECTOR_BENCH") or str(_REPO.parent / "director-bench"),
        keep_root=str(_REPO / ".local" / "director_state" / served),
        base_url=base_url,
        api_key_env=env("DIRECTOR_API_KEY_ENV") or "ANTHROPIC_API_KEY",
        timeout=timeout,
        max_depth=int(depth) if depth else None,
        cost_limit=float(env("DIRECTOR_COST_LIMIT")) if env("DIRECTOR_COST_LIMIT") else None,
        budget_file=env("DIRECTOR_BUDGET_FILE"),
        budget_usd=float(env("DIRECTOR_BUDGET_USD")) if env("DIRECTOR_BUDGET_USD") else None,
    )


def harness_model_label(harness: str, model_key: str) -> str:
    """Output-namespace segment, e.g. claude__qwen3-flash-next."""
    if harness == "director":
        # A solo run (no sub-teams) is kept apart from one that may split.
        solo = "-solo" if os.environ.get("DIRECTOR_MAX_DEPTH") == "1" else ""
        return f"director{solo}__{_director_model(model_key)[2]}"
    return f"{harness}__{get(model_key).served_name}"


def make_runner(harness: str, model_key: str, timeout: int = 3600):
    if harness == "director":
        return _director_runner(model_key, timeout)
    ep = get(model_key)
    if harness == "claude":
        return ClaudeCodeRunner.for_vllm(
            served_name=ep.served_name,
            base_url=ep.base_url,
            config_dir=f"~/.claude-{ep.key}",
            name=f"claude__{ep.key}",
            effort=ep.reasoning_effort,
            timeout=timeout,
        )
    if harness == "codex":
        return CodexRunner(
            ep.served_name,
            ep.base_url,
            config_home=f"~/.codex-{ep.key}-run",
            name=f"codex__{ep.key}",
            reasoning=ep.reasoning_effort,
            timeout=timeout,
        )
    if harness == "opencode":
        return OpencodeRunner(
            ep.served_name,
            ep.base_url,
            config_path=str(_HERE / "opencode_configs" / f"{ep.key}.json"),
            name=f"opencode__{ep.key}",
            reasoning=ep.reasoning_effort,
            timeout=timeout,
        )
    raise SystemExit(f"unknown harness {harness!r}; use one of {HARNESSES}")
