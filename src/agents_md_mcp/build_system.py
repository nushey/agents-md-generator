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
    detected_extras: dict = {}

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
            # Extract dependency names (no versions)
            npm_packages = sorted({
                *data.get("dependencies", {}).keys(),
                *data.get("devDependencies", {}).keys(),
            })
            if npm_packages:
                detected_extras["npm_packages"] = npm_packages
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

            # Extract dependency names (no versions)
            all_deps = (
                toml.get("project", {}).get("dependencies", [])
                + [d for deps in toml.get("project", {}).get("optional-dependencies", {}).values() for d in deps]
            )
            dep_names = [d.split(">=")[0].split("==")[0].split("[")[0].split("<")[0].split("~")[0].split("!")[0].strip().lower() for d in all_deps]
            python_packages = sorted(set(dep_names))
            if python_packages:
                detected_extras["python_packages"] = python_packages

            # Detect test runner
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

    # Parse go.mod — extract direct dependency module paths (no versions)
    go_mod = root / "go.mod"
    if go_mod.exists():
        try:
            go_packages = []
            in_require_block = False
            for line in go_mod.read_text(encoding="utf-8", errors="replace").splitlines():
                stripped = line.strip()
                if stripped.startswith("require ("):
                    in_require_block = True
                    continue
                if in_require_block:
                    if stripped == ")":
                        in_require_block = False
                        continue
                    if stripped and not stripped.startswith("//"):
                        # "github.com/foo/bar v1.2.3" or "github.com/foo/bar v1.2.3 // indirect"
                        parts = stripped.split()
                        if parts and "// indirect" not in stripped:
                            go_packages.append(parts[0])
                elif stripped.startswith("require ") and "(" not in stripped:
                    # Single-line require: "require github.com/foo/bar v1.2.3"
                    parts = stripped.split()
                    if len(parts) >= 2 and "// indirect" not in stripped:
                        go_packages.append(parts[1])
            if go_packages:
                detected_extras["go_packages"] = sorted(go_packages)
        except OSError:
            pass

    # Parse .csproj files (only for dotnet projects)
    _SYSTEM_REF_PREFIXES = ("System", "Microsoft.", "mscorlib", "PresentationCore", "WindowsBase")

    def _iter_tag(xml_root: ET.Element, tag: str):
        """Iterate elements by local name, ignoring XML namespace."""
        for el in xml_root.iter():
            if el.tag.split("}")[-1] == tag:
                yield el

    def _find_text_tag(xml_root: ET.Element, tag: str) -> str | None:
        el = next(_iter_tag(xml_root, tag), None)
        return el.text.strip() if el is not None and el.text else None

    dotnet_projects = []
    if "dotnet" in detected:
        for csproj in sorted(root.rglob("*.csproj")):
            try:
                tree = ET.parse(csproj)
                xml_root = tree.getroot()

                # TargetFramework (SDK-style) or TargetFrameworkVersion (Framework-style)
                target = (
                    _find_text_tag(xml_root, "TargetFramework")
                    or _find_text_tag(xml_root, "TargetFrameworks")
                    or _find_text_tag(xml_root, "TargetFrameworkVersion")
                )
                output_type = _find_text_tag(xml_root, "OutputType")

                packages = []
                # SDK-style: <PackageReference Include="Name" Version="x" />
                for ref in _iter_tag(xml_root, "PackageReference"):
                    name = ref.get("Include") or ref.get("include")
                    if name:
                        packages.append(name)

                # Framework-style: <Reference Include="Name"> with <HintPath> (external DLL)
                if not packages:
                    for ref in _iter_tag(xml_root, "Reference"):
                        name = (ref.get("Include") or "").split(",")[0].strip()
                        has_hint = next(_iter_tag(ref, "HintPath"), None) is not None
                        if name and has_hint and not name.startswith(_SYSTEM_REF_PREFIXES):
                            packages.append(name)

                packages = packages[:15]

                proj_refs = []
                for ref in _iter_tag(xml_root, "ProjectReference"):
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

    # Deduplicate dotnet packages: extract common ones shared across >50% of projects
    if dotnet_projects and len(dotnet_projects) > 1:
        pkg_counts: dict[str, int] = {}
        for proj in dotnet_projects:
            for pkg in proj.get("packages", []):
                pkg_counts[pkg] = pkg_counts.get(pkg, 0) + 1
        cutoff = len(dotnet_projects) * 0.5
        common_pkgs = sorted(pkg for pkg, count in pkg_counts.items() if count >= cutoff)
        common_set = set(common_pkgs)
        if common_pkgs:
            for proj in dotnet_projects:
                proj["packages"] = [p for p in proj["packages"] if p not in common_set]
            detected_extras["dotnet_common_packages"] = common_pkgs

    return {
        "detected": detected,
        "package_files": package_files,
        "scripts": scripts,
        **detected_extras,
        **({"dotnet_projects": dotnet_projects} if dotnet_projects else {}),
    }
