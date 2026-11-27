"""Agent-director backend: run a whole org of agents on the workspace.

One turn is one `director-bench run`: it starts a director server of its own,
opens an org on the workspace with the turn's prompt, and ends when the org's
accepted work landed in the workspace checkout. The driver's log is the
transcript; its report on whether the org used its teams is kept beside it as
`team_usage.json`, and the server's whole state (every agent's events) under
`keep_root`.

A turn that ran out of time or got stuck returns whatever landed, which may be
nothing: that is the org's result. A turn the driver could not run, or one the
spending cap ended, raises TurnFailure so that no bundle is written for it.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import time

from ..types import TurnFailure, TurnResult, Usage
from ..workspace import Workspace

# Driver exit codes (director_bench.run).
_LANDED, _NOT_LANDED, _OVER_BUDGET = 0, 1, 3


class DirectorRunner:
    def __init__(
        self,
        model: str,
        name: str,
        sdk: str,
        bench: str,
        keep_root: str,
        base_url: str | None = None,
        api_key_env: str = "ANTHROPIC_API_KEY",
        timeout: int = 3600,
        max_depth: int | None = None,
        cost_limit: float | None = None,
        budget_file: str | None = None,
        budget_usd: float | None = None,
        extra_args: tuple[str, ...] = (),
    ) -> None:
        self.model = model
        self.name = name
        self.sdk = sdk
        self.bench = bench
        self.keep_root = pathlib.Path(keep_root)
        self.base_url = base_url
        self.api_key_env = api_key_env
        self.timeout = timeout
        self.max_depth = max_depth
        self.cost_limit = cost_limit
        self.budget_file = budget_file
        self.budget_usd = budget_usd
        self.extra_args = extra_args
        # The org's sub-teams run on the model of the team above.
        self.subagent_model = model

    def run_turn(
        self,
        workspace: Workspace,
        agent: str,
        index: int,
        prompt: str,
        budget: int | None = None,
    ) -> TurnResult:
        out = self.keep_root / (
            f"{time.strftime('%Y%m%d-%H%M%S')}_{workspace.path.name}_{index:02d}_{agent}"
        )
        out.mkdir(parents=True, exist_ok=True)
        task = out / "task.md"
        task.write_text(prompt, encoding="utf-8")
        # The org merges accepted work into the branch that is checked out.
        if subprocess.run(
            ["git", "-C", str(workspace.path), "symbolic-ref", "-q", "HEAD"],
            capture_output=True,
        ).returncode:
            subprocess.run(
                ["git", "-C", str(workspace.path), "checkout", "-q", "-B", "director-bench"],
                check=True,
            )
        cmd = [
            sys.executable, "-m", "director_bench", "run",
            "--repo", str(workspace.path),
            "--prompt-file", str(task),
            "--out", str(out),
            "--sdk", self.sdk,
            "--model", self.model,
            "--api-key-env", self.api_key_env,
            "--timeout", str(self.timeout),
            "--drop-worktrees",
        ]  # fmt: skip
        if self.base_url:
            cmd += ["--base-url", self.base_url]
        if self.max_depth is not None:
            cmd += ["--max-depth", str(self.max_depth)]
        if self.cost_limit is not None:
            cmd += ["--cost-limit", str(self.cost_limit)]
        if self.budget_file:
            cmd += ["--budget-file", self.budget_file, "--budget-usd", str(self.budget_usd)]
        cmd += list(self.extra_args)
        env = dict(os.environ)
        env["PYTHONPATH"] = self.bench + os.pathsep + env.get("PYTHONPATH", "")
        try:
            p = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                # The driver ends the run itself; this only catches a hung driver.
                timeout=self.timeout + 600,
            )
        except subprocess.TimeoutExpired as e:
            raise TurnFailure(f"director turn {index} hung past {self.timeout}s") from e
        result = _read(out / "result.json")
        if p.returncode == _OVER_BUDGET:
            raise TurnFailure(
                f"director turn {index} ended by the spending cap ({result.get('outcome')})"
            )
        if p.returncode not in (_LANDED, _NOT_LANDED) or result.get("outcome") == "error":
            raise TurnFailure(
                f"director turn {index} exit {p.returncode}: "
                f"{result.get('error') or (p.stderr or p.stdout or '')[-300:]}"
            )
        extras = {
            name: (out / name).read_text(encoding="utf-8")
            for name in ("result.json", "team_usage.json")
            if (out / name).exists()
        }
        return TurnResult(
            index=index,
            agent=agent,
            prompt=prompt,
            transcript=f"# kept state: {out}\n{p.stdout}{p.stderr}",
            diff=workspace.diff_base(),
            usage=self._usage(result),
            extras=extras,
        )

    def _usage(self, result: dict) -> Usage:
        used = result.get("usage") or {}
        return Usage(
            cost_usd=result.get("cost"),
            cost_basis="computed",
            input_tokens=used.get("input_tokens", 0),
            output_tokens=used.get("output_tokens", 0),
            cache_read_tokens=used.get("cache_read_tokens", 0),
            num_turns=used.get("llm_calls"),
            duration_ms=int((result.get("wall_seconds") or 0) * 1000),
            is_error=result.get("outcome") != "landed",
            stop_reason=result.get("outcome"),
            by_model={
                self.model: {
                    "used_teams": int(bool(result.get("used_teams"))),
                    "cost_usd": result.get("cost"),
                }
            },
        )


def _read(path: pathlib.Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
