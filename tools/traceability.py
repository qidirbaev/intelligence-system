"""Machine check of docs/TRACEABILITY.md against TASKS.md, the code and the tests.

The register lists what you asked for. This module fails when:
  * a row claims work that does not exist (missing file or test),
  * a status contradicts the task list (e.g. 'Planned' but its task is already done),
  * a task exists that no requirement asks for (scope creep),
  * a deferred/changed item has no recorded deviation.

CLI:  python -m tools.traceability   (prints a summary, exit 1 on any error)
"""

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATUSES = {"Implemented", "Partial", "Planned", "Deferred", "Changed"}
REQ_ID = re.compile(r"^(V|U|CG|A|AC)-\d+$")
DEV_ID = re.compile(r"^D-\d+$")
TASK_ID = re.compile(r"T\d{2}[a-z]?")
TASK_ROW = re.compile(r"^\|\s*\[(x|~| )\]\s*\|\s*(T\d{2}[a-z]?)\s*\|\s*([^|]*)\|")
REF = re.compile(r"`([^`]+)`")


@dataclass
class Req:
    id: str
    text: str
    source: str
    status: str
    tasks: list[str]
    evidence: str

    @property
    def refs(self) -> list[str]:
        return [r for r in REF.findall(self.evidence) if "/" in r or "::" in r]


@dataclass
class Deviation:
    id: str
    what: str
    why: str
    decision: str


@dataclass
class Registry:
    requirements: list[Req] = field(default_factory=list)
    deviations: list[Deviation] = field(default_factory=list)


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse_tasks(tasks_md: str) -> dict[str, bool]:
    """task id -> done?"""
    tasks: dict[str, bool] = {}
    for line in tasks_md.splitlines():
        match = TASK_ROW.match(line)
        if match:
            tasks[match.group(2)] = match.group(1) == "x"
    return tasks


def parse_registry(md: str) -> Registry:
    registry = Registry()
    for line in md.splitlines():
        if not line.startswith("|"):
            continue
        cells = _cells(line)
        if REQ_ID.match(cells[0]) and len(cells) >= 6:
            tasks = TASK_ID.findall(cells[4])
            registry.requirements.append(
                Req(cells[0], cells[1], cells[2], cells[3], tasks, cells[5])
            )
        elif DEV_ID.match(cells[0]) and len(cells) >= 4:
            registry.deviations.append(Deviation(cells[0], cells[1], cells[2], cells[3]))
    return registry


def _ref_problem(ref: str, root: Path) -> str | None:
    path_part, _, name = ref.partition("::")
    path = root / path_part
    if not path.exists():
        return f"evidence file not found: {path_part}"
    if name and not re.search(rf"def {re.escape(name)}\(", path.read_text(encoding="utf-8")):
        return f"evidence test not found: {ref}"
    return None


def check(root: Path = ROOT) -> list[str]:
    """All problems found; an empty list means the register is consistent."""
    errors: list[str] = []
    tasks = parse_tasks((root / "TASKS.md").read_text(encoding="utf-8"))
    registry = parse_registry((root / "docs" / "TRACEABILITY.md").read_text(encoding="utf-8"))
    deviation_ids = {d.id for d in registry.deviations}

    seen: set[str] = set()
    referenced: set[str] = set()
    for req in registry.requirements:
        where = f"{req.id}"
        if req.id in seen:
            errors.append(f"{where}: duplicate id")
        seen.add(req.id)
        if req.status not in STATUSES:
            errors.append(f"{where}: unknown status '{req.status}'")
            continue
        referenced.update(req.tasks)
        for task_id in req.tasks:
            if task_id not in tasks:
                errors.append(f"{where}: unknown task {task_id}")
        done = [t for t in req.tasks if tasks.get(t)]
        todo = [t for t in req.tasks if t in tasks and not tasks[t]]

        for ref in req.refs:
            problem = _ref_problem(ref, root)
            if problem:
                errors.append(f"{where}: {problem}")

        if req.status == "Planned":
            if not req.tasks:
                errors.append(f"{where}: Planned needs at least one task")
            if done:
                errors.append(
                    f"{where}: Planned but {', '.join(done)} already done -> update status"
                )
        elif req.status == "Partial":
            if not (done and todo):
                errors.append(
                    f"{where}: Partial needs a done task and a not-done task ({req.tasks})"
                )
            if not req.refs:
                errors.append(f"{where}: Partial needs evidence (path or path::test)")
        elif req.status == "Implemented":
            if todo:
                errors.append(f"{where}: Implemented but {', '.join(todo)} not done")
            if not req.refs:
                errors.append(f"{where}: Implemented needs evidence (path or path::test)")
        else:  # Deferred / Changed
            ids = re.findall(r"D-\d+", req.evidence)
            if not ids:
                errors.append(f"{where}: {req.status} must cite a deviation (D-n) in Evidence")
            for dev in ids:
                if dev not in deviation_ids:
                    errors.append(f"{where}: unknown deviation {dev}")

    for dev in registry.deviations:
        if dev.decision not in {"Yes", "No"}:
            errors.append(f"{dev.id}: 'Needs your decision' must be Yes or No")

    for task_id in sorted(tasks):
        if task_id not in referenced:
            errors.append(
                f"{task_id}: no requirement asks for this task (scope creep or missing row)"
            )
    if not registry.requirements:
        errors.append("no requirement rows found in docs/TRACEABILITY.md")
    return errors


def summary(root: Path = ROOT) -> dict[str, int]:
    registry = parse_registry((root / "docs" / "TRACEABILITY.md").read_text(encoding="utf-8"))
    counts = {status: 0 for status in sorted(STATUSES)}
    for req in registry.requirements:
        counts[req.status] = counts.get(req.status, 0) + 1
    counts["total"] = len(registry.requirements)
    counts["decisions_needed"] = sum(1 for d in registry.deviations if d.decision == "Yes")
    return counts


def main() -> int:
    errors = check()
    counts = summary()
    print("requirements:", ", ".join(f"{k}={v}" for k, v in counts.items()))
    for error in errors:
        print("PROBLEM:", error)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
