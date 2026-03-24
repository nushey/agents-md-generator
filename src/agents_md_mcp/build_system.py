"""Detects build tools, package managers, and scripts for a project."""

import json
import tomllib
from pathlib import Path

_BUILD_MARKERS: dict[str, list[str]] = {
    "dotnet": ["*.sln", "*.csproj", "global.json", "Directory.Build.props"],
    "npm": ["package.json"],
    "go": ["go.mod"],
    "make": ["Makefile", "makefile", "GNUmakefile"],
    "python": ["pyproject.toml", "setup.py", "setup.cfg", "Pipfile"],
    "rust": ["Cargo.toml"],
    "maven": ["pom.xml"],
    "gradle": ["build.gradle", "build.gradle.kts"],
    "ruby": ["Gemfile"],
}


def _detect_build_systems(root: Path) -> dict:
    detected = []
    package_files = []

    for system, markers in _BUILD_MARKERS.items():
        for marker in markers:
            matches = list(root.glob(marker))
            if matches:
                detected.append(system)
                for m in matches:
                    rel = str(m.relative_to(root))
                    if rel not in package_files:
                        package_files.append(rel)
                break  # one match per system is enough

    scripts: dict[str, dict] = {}

    # Parse npm scripts
    pkg_json = root / "package.json"
    if pkg_json.exists():
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
            if "scripts" in data:
                scripts["npm"] = data["scripts"]
            # Detect package manager
            if "packageManager" in data:
                pm = data["packageManager"].split("@")[0]
                if pm not in detected:
                    detected.append(pm)
        except (json.JSONDecodeError, OSError):
            pass

    # Parse pyproject.toml — entry points, test runner, package manager
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        try:
            with open(pyproject, "rb") as f:
                toml = tomllib.load(f)

            py_scripts: dict[str, str] = {}

            # Detect package manager from lock file presence
            runner = "python"
            if (root / "uv.lock").exists():
                runner = "uv run"
                if "uv" not in detected:
                    detected.append("uv")
            elif (root / "poetry.lock").exists():
                runner = "poetry run"
                if "poetry" not in detected:
                    detected.append("poetry")

            # Install command
            if runner == "uv run":
                py_scripts["install"] = "uv sync"
            elif runner == "poetry run":
                py_scripts["install"] = "poetry install"

            # [project.scripts] → CLI entry points
            project_scripts = toml.get("project", {}).get("scripts", {})
            for name, target in project_scripts.items():
                py_scripts[name] = f"{runner} {name}" if runner != "python" else name

            # Detect test runner from dependencies
            all_deps = (
                toml.get("project", {}).get("dependencies", [])
                + [d for deps in toml.get("project", {}).get("optional-dependencies", {}).values() for d in deps]
            )
            dep_names = [d.split(">=")[0].split("==")[0].split("[")[0].strip().lower() for d in all_deps]
            if "pytest" in dep_names:
                py_scripts["test"] = f"{runner} pytest"
            elif "unittest" in dep_names:
                py_scripts["test"] = f"{runner} python -m unittest"

            if py_scripts:
                scripts["python"] = py_scripts
        except (OSError, tomllib.TOMLDecodeError):
            pass

    # Parse Makefile targets (first word of non-indented lines ending with :)
    makefile = root / "Makefile"
    if not makefile.exists():
        makefile = root / "makefile"
    if makefile.exists():
        try:
            targets = []
            for line in makefile.read_text(encoding="utf-8", errors="replace").splitlines():
                if line and not line.startswith("\t") and not line.startswith("#") and ":" in line:
                    target = line.split(":")[0].strip()
                    if target and not target.startswith(".") and " " not in target:
                        targets.append(target)
            if targets:
                scripts["make"] = {t: f"make {t}" for t in targets[:20]}
        except OSError:
            pass

    return {
        "detected": detected,
        "package_files": package_files,
        "scripts": scripts,
    }
