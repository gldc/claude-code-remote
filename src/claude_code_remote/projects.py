"""Project discovery and scanning."""

from pathlib import Path

from claude_code_remote.models import Project, ProjectType

PROJECT_INDICATORS = [".git", "package.json", "pyproject.toml", "Cargo.toml", "go.mod"]

TYPE_MAP = {
    "pyproject.toml": ProjectType.PYTHON,
    "setup.py": ProjectType.PYTHON,
    "package.json": ProjectType.NODE,
    "Cargo.toml": ProjectType.RUST,
    "go.mod": ProjectType.GO,
}


def detect_project_type(path: Path) -> ProjectType:
    for filename, ptype in TYPE_MAP.items():
        if (path / filename).exists():
            return ptype
    return ProjectType.UNKNOWN


def is_project(path: Path) -> bool:
    return any((path / ind).exists() for ind in PROJECT_INDICATORS)


def scan_directory(root: Path) -> list[Project]:
    projects = []
    if not root.is_dir():
        return projects
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        if is_project(child):
            projects.append(
                Project(
                    id=Project.id_from_path(str(child)),
                    name=child.name,
                    path=str(child),
                    type=detect_project_type(child),
                )
            )
    return projects
