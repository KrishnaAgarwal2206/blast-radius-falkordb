"""Run the app's smoke checks in a throw-away virtualenv with the proposed upgrades applied.
These checks show the app still starts and exercises its dependency paths. They do NOT prove the vulnerability is fixed:
that claim comes from the advisory's fixed-version range (OSV) and is reported separately."""
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .. import config
from .apps import APPS, RUNNER_PYTHON

CHECKS = {
    "httpie": [
        ("httpie --version", ["-m", "httpie", "--version"]),
        ("build a GET request offline (requests session + proxies + urllib3 pool)", ["-m", "httpie", "--ignore-stdin", "--offline", "GET", "http://example.org/anything", "q==1"]),
        ("build a POST with JSON body offline", ["-m", "httpie", "--ignore-stdin", "--offline", "POST", "http://example.org/post", "a=b"]),
    ],
    "precommit": [
        ("pre-commit --version", ["-m", "pre_commit", "--version"]),
        ("validate a config file (YAML load path)", ["-m", "pre_commit", "validate-config", "{tmp}/.pre-commit-config.yaml"]),
    ],
    "cookiecutter": [
        ("cookiecutter --version", ["-m", "cookiecutter", "--version"]),
        ("render a template (Jinja2 + click + file generation)", ["-m", "cookiecutter", "{tmp}/tpl", "--no-input", "-o", "{tmp}/out"]),
    ],
    "yamlfull": [
        ("load a settings file", ["-c", "from yamlfull.config import load_settings; print(load_settings('{tmp}/s.yaml'))"]),
    ],
}


def run_checks(app: str, pins: dict, upgrades: dict, label: str, log=print) -> dict:
    """pins: name->version (baseline). upgrades: name->version overrides. Returns {installed, checks:[...]}."""
    spec = APPS[app]
    venv = Path(tempfile.mkdtemp(prefix=f"sc-{app}-{label}-", dir=str(config.ROOT / "data" / "envs")))
    py = venv / ("Scripts" if sys.platform == "win32" else "bin") / ("python.exe" if sys.platform == "win32" else "python")
    out = dict(label=label, installed={}, checks=[], install_ok=False)
    t0 = time.perf_counter()
    try:
        subprocess.run([RUNNER_PYTHON if Path(RUNNER_PYTHON).exists() else sys.executable, "-m", "venv", str(venv)], check=True, capture_output=True, timeout=180)
        want = {**pins, **upgrades}
        req = venv / "req.txt"
        req.write_text("\n".join(f"{k}=={v}" for k, v in want.items()))
        r = subprocess.run([str(py), "-m", "pip", "install", "--only-binary", ":all:", "--no-deps", "-q", "-r", str(req)],
                           capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            lines = (r.stderr or r.stdout).strip().splitlines()
            out["install_error"] = ([l for l in lines if "ERROR" in l] or lines or ["pip failed"])[-1][:300]
            return out
        out["install_ok"], out["installed"] = True, want
        tmp = venv / "work"
        tmp.mkdir()
        (tmp / ".pre-commit-config.yaml").write_text("repos: []\n")
        (tmp / "s.yaml").write_text("debug: true\nport: 8080\n")
        (tmp / "tpl" / "{{cookiecutter.name}}").mkdir(parents=True)
        (tmp / "tpl" / "cookiecutter.json").write_text('{"name": "demo", "greeting": "hello"}')
        (tmp / "tpl" / "{{cookiecutter.name}}" / "README.md").write_text("{{ cookiecutter.greeting|upper }} from {{ cookiecutter.name|title }}\n")
        env = {"PYTHONPATH": spec["repo"], "PATH": str(py.parent), "SYSTEMROOT": "C:\\Windows", "HOME": str(tmp), "USERPROFILE": str(tmp)}
        for title, argv in CHECKS[app]:
            argv = [a.replace("{tmp}", tmp.as_posix()) for a in argv]
            t1 = time.perf_counter()
            try:
                p = subprocess.run([str(py), *argv], capture_output=True, text=True, timeout=120, cwd=str(tmp), env=env)
                ok, tail = p.returncode == 0, re.sub(r"[A-Za-z]:[\\/][^\s'\"]*", "<path>", ((p.stdout + p.stderr).strip().splitlines() or [""])[-1])[:200]
            except subprocess.TimeoutExpired:
                ok, tail = False, "timed out"
            out["checks"].append(dict(title=title, ok=ok, ms=round((time.perf_counter() - t1) * 1000), tail=tail))
    finally:
        out["ms"] = round((time.perf_counter() - t0) * 1000)
        shutil.rmtree(venv, ignore_errors=True)
    return out
