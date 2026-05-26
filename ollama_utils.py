"""Ollama lifecycle utilities — shared by main.py and mcp_server.py."""

import json
import subprocess
import time
from pathlib import Path

import requests

from config import OLLAMA_URL, OLLAMA_MODEL

COMPOSE_FILE = Path(__file__).parent / "docker-compose.yml"


def reachable() -> bool:
    try:
        return requests.get(f"{OLLAMA_URL}/api/tags", timeout=5).status_code == 200
    except Exception:
        return False


def model_present() -> bool:
    try:
        resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        models = [m["name"] for m in resp.json().get("models", [])]
        return any(OLLAMA_MODEL.split(":")[0] in m for m in models)
    except Exception:
        return False


def try_docker_start() -> bool:
    if not COMPOSE_FILE.exists():
        return False
    for cmd in (["docker", "compose"], ["docker-compose"]):
        try:
            result = subprocess.run(
                cmd + ["-f", str(COMPOSE_FILE), "up", "-d"],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                return True
        except FileNotFoundError:
            continue
    return False


def wait_for_ollama(timeout: int = 60, silent: bool = False) -> bool:
    if not silent:
        print("        Waiting for Ollama", end="", flush=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if reachable():
            if not silent:
                print(" ready")
            return True
        if not silent:
            print(".", end="", flush=True)
        time.sleep(2)
    if not silent:
        print(" timed out")
    return False


def pull_model(silent: bool = False) -> bool:
    if not silent:
        print(f"        Pulling {OLLAMA_MODEL} (one-time, ~2 GB)...", flush=True)
    try:
        with requests.post(
            f"{OLLAMA_URL}/api/pull",
            json={"name": OLLAMA_MODEL, "stream": True},
            stream=True,
            timeout=600,
        ) as resp:
            for line in resp.iter_lines():
                if line and not silent:
                    try:
                        data = json.loads(line)
                        status = data.get("status", "")
                        if "pulling" in status or "verifying" in status:
                            total = data.get("total", 0)
                            completed = data.get("completed", 0)
                            if total:
                                pct = int(completed / total * 100)
                                print(f"\r        {status} {pct}%   ", end="", flush=True)
                    except json.JSONDecodeError:
                        pass
        if not silent:
            print()
        return model_present()
    except Exception as e:
        if not silent:
            print(f"\n        Pull failed: {e}")
        return False


def ensure(silent: bool = False) -> tuple[bool, str]:
    """
    Guarantee Ollama is running and the model is available.
    Returns (success, error_message).
    """
    if not reachable():
        if not silent:
            print("        Not reachable — attempting to start via Docker...")
        if not try_docker_start():
            msg = (
                f"Could not start Ollama. Run manually:\n"
                f"  docker compose -f {COMPOSE_FILE} up -d\n"
                f"  ollama serve"
            )
            return False, msg
        if not wait_for_ollama(silent=silent):
            return False, "Ollama did not become ready in time."
    elif not silent:
        print("        Ollama reachable")

    if not model_present():
        if not pull_model(silent=silent):
            return False, f"Could not pull {OLLAMA_MODEL}."

    if not silent:
        print(f"        Model ready ({OLLAMA_MODEL})")
    return True, ""
