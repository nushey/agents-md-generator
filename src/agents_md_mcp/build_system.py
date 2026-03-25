"""Detects build tools, package managers, and scripts for a project."""

import json
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

from .path_utils import rel_posix

_BUILD_MARKERS: dict[str, list[str]] = {
    "dotnet": ["*.sln", "**/*.csproj", "global.json", "Directory.Build.props"],
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
                    rel = rel_posix(m, root)
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

    # Parse .csproj files (only for dotnet projects)
    dotnet_projects = []
    if "dotnet" in detected:
        for csproj in sorted(root.rglob("*.csproj")):
            try:
                tree = ET.parse(csproj)
                xml_root = tree.getroot()

                def _find_text(tag: str) -> str | None:
                    el = xml_root.find(f".//{tag}")
                    return el.text.strip() if el is not None and el.text else None

                target = _find_text("TargetFramework") or _find_text("TargetFrameworks")
                output_type = _find_text("OutputType")

                packages = []
                for ref in xml_root.iter("PackageReference"):
                    name = ref.get("Include") or ref.get("include")
                    ver_el = ref.find("Version")
                    version = ref.get("Version") or ref.get("version") or (ver_el.text.strip() if ver_el is not None and ver_el.text else None)
                    if name:
                        packages.append(f"{name}@{version}" if version else name)
                packages = packages[:15]

                proj_refs = []
                for ref in xml_root.iter("ProjectReference"):
                    inc = ref.get("Include") or ref.get("include")
                    if inc:
                        proj_refs.append(inc.replace("\\", "/"))

                dotnet_projects.append({
                    "file": rel_posix(csproj, root),
                    "target_framework": target,
                    "output_type": output_type,
                    "packages": packages,
                    "project_references": proj_refs,
                })
            except (ET.ParseError, OSError):
                continue

    return {
        "detected": detected,
        "package_files": package_files,
        "scripts": scripts,
        **({"dotnet_projects": dotnet_projects} if dotnet_projects else {}),
    }
