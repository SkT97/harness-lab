"""Read Harbor v0.26.0 trial result documents without executing a benchmark."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

HARBOR_VERSION = "0.26.0"


class HarborError(ValueError):
    """An input cannot be reported unambiguously."""


def _object(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise HarborError(f"{field} must be an object")
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise HarborError("duplicate JSON key")
        result[key] = value
    return result


def _read(path: Path) -> dict[str, Any]:
    try:
        return _object(
            json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object),
            "document",
        )
    except (UnicodeError, ValueError) as exc:
        if isinstance(exc, HarborError):
            raise
        raise HarborError("invalid JSON document") from exc


def _label(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or any(ord(char) < 32 for char in value):
        raise HarborError(f"{field} must be a non-empty string without control characters")
    return value


def _version(value: object, kind: str) -> None:
    if type(value) is not int or value != 1:
        raise HarborError(f"unsupported {kind} schema")


def _identity(record: dict[str, Any]) -> dict[str, str]:
    return {
        field: _label(record.get(field), field)
        for field in ("trial_name", "task_name", "task_checksum")
    }


def _load_plan(path: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    raw = _read(path)
    _version(raw.get("schema_version"), "manifest")
    if raw.get("harbor_version") != HARBOR_VERSION:
        raise HarborError("unsupported manifest Harbor version")
    campaign = {
        field: _label(raw.get(field), field)
        for field in ("campaign", "benchmark", "benchmark_revision")
    }
    raw_limits = _object(raw.get("limits"), "limits")
    limits = {}
    for field in ("timeout_seconds", "max_input_tokens", "max_output_tokens"):
        if field in raw_limits:
            value = raw_limits[field]
            if type(value) is not int or value <= 0:
                raise HarborError(f"{field} must be a positive integer")
            limits[field] = value
    raw_trials = raw.get("trials")
    if not isinstance(raw_trials, list) or not raw_trials:
        raise HarborError("manifest trials must be a non-empty array")
    planned = {}
    cells = set()
    for row in raw_trials:
        item = _object(row, "manifest trial")
        identity = _identity(item)
        repeat = item.get("repeat")
        if type(repeat) is not int or repeat < 0:
            raise HarborError("repeat must be a non-negative integer")
        configuration = _label(item.get("configuration"), "configuration")
        cell = (identity["task_name"], identity["task_checksum"], configuration, repeat)
        name = identity["trial_name"]
        if name in planned or cell in cells:
            raise HarborError("duplicate planned trial")
        cells.add(cell)
        planned[name] = {**identity, "configuration": configuration, "repeat": repeat}
    return {**campaign, "limits": limits}, planned


def _exception_type(record: dict[str, Any]) -> str | None:
    if record.get("exception_info") is None:
        return None
    info = _object(record["exception_info"], "exception_info")
    name = info.get("exception_type")
    # Preserve class-like labels only. Exception messages and paths can contain secrets.
    if (
        isinstance(name, str)
        and len(name) <= 100
        and all(part.isidentifier() for part in name.split("."))
    ):
        return name
    return "unclassified"


def _trial(path: Path, reward_key: str) -> dict[str, Any]:
    raw = _read(path)
    _version(raw.get("schema_version", 1), "trial")
    identity = _identity(raw)
    agent_info = _object(raw.get("agent_info"), "agent_info")
    agent = {
        field: _label(agent_info.get(field), f"agent {field}") for field in ("name", "version")
    }
    if agent_info.get("model_info") is not None:
        model_info = _object(agent_info["model_info"], "model_info")
        agent["model"] = _label(model_info.get("name"), "model name")
        if model_info.get("provider") is not None:
            agent["provider"] = _label(model_info["provider"], "model provider")

    steps = raw.get("step_results")
    if steps is not None and not isinstance(steps, list):
        raise HarborError("step_results must be an array or null")
    exceptions = sorted(
        {
            name
            for entry in [raw, *(_object(step, "step result") for step in steps or [])]
            if (name := _exception_type(entry)) is not None
        }
    )
    reward = None
    verifier_result = raw.get("verifier_result")
    if verifier_result is not None:
        rewards = _object(verifier_result, "verifier_result").get("rewards")
        if rewards is not None:
            reward = _object(rewards, "rewards").get(reward_key)
    if reward is not None and (
        type(reward) not in (int, float) or (type(reward) is float and not math.isfinite(reward))
    ):
        raise HarborError("reward must be a finite number or null")

    reward_valid = raw.get("reward_valid", True)
    if type(reward_valid) is not bool:
        raise HarborError("reward_valid must be a boolean")
    if exceptions or not reward_valid or reward not in (0, 1):
        outcome = "unevaluable"
    else:
        outcome = "pass" if reward == 1 else "fail"
    return {
        **identity,
        "agent": agent,
        "reward": reward,
        "reward_valid": raw.get("reward_valid"),
        "exceptions": exceptions,
        "outcome": outcome,
    }


def harbor_report(job_dir: Path, manifest: Path | None, reward_key: str) -> dict[str, Any]:
    """Use the planned denominator only when declared by the caller."""
    campaign, planned = _load_plan(manifest) if manifest is not None else (None, {})
    observed = {}
    for directory in sorted(job_dir.iterdir()):
        if directory.is_symlink() or directory.is_junction() or not directory.is_dir():
            continue
        path = directory / "result.json"
        if path.is_symlink() or not path.is_file():
            continue
        trial = _trial(path, reward_key)
        name = trial["trial_name"]
        if name in observed:
            raise HarborError("duplicate observed trial name")
        if manifest is not None:
            plan = planned.get(name)
            if plan is None or any(
                trial[field] != plan[field] for field in ("task_name", "task_checksum")
            ):
                raise HarborError("observed trial does not match manifest")
            trial.update(configuration=plan["configuration"], repeat=plan["repeat"])
        observed[name] = trial
    if not observed and manifest is None:
        raise HarborError("no Harbor trial result documents found")

    trials = [observed[name] for name in sorted(observed)]
    missing = [planned[name] for name in sorted(planned.keys() - observed.keys())]
    passed = sum(row["outcome"] == "pass" for row in trials)
    failed = sum(row["outcome"] == "fail" for row in trials)
    eligible = passed + failed
    return {
        "schema_version": 1,
        "adapter": f"harbor/{HARBOR_VERSION}",
        "reward_key": reward_key,
        "campaign": campaign,
        "counts": {
            "planned": len(planned) if manifest is not None else None,
            "observed": len(trials),
            "missing_planned": len(missing) if manifest is not None else None,
            "evaluable_binary": eligible,
            "passed": passed,
            "failed": failed,
            "exceptions": sum(bool(row["exceptions"]) for row in trials),
            "missing_reward": sum(row["reward"] is None for row in trials),
            "invalid_reward": sum(row["reward_valid"] is False for row in trials),
            "non_binary": sum(
                row["reward"] is not None and row["reward"] not in (0, 1) for row in trials
            ),
        },
        "rates": {
            "success_per_planned": passed / len(planned) if planned else None,
            "observed_per_planned": len(trials) / len(planned) if planned else None,
            "success_per_evaluable": passed / eligible if eligible else None,
        },
        "trials": trials,
        "missing_trials": missing if manifest is not None else None,
    }
