"""Universal ASC v2.3.0 - Mission Specification Parser

Parses YAML or JSON mission specifications and validates them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Union

import yaml

from .models import MissionDefaults, MissionSpec, Task, VerificationCommand


class MissionSpecParser:
    """Parses and validates mission specifications from YAML/JSON."""

    @staticmethod
    def parse(content: str) -> MissionSpec:
        """Parse mission spec from string (auto-detects YAML/JSON)."""
        content = content.strip()
        if content.startswith("{") or content.startswith("["):
            return MissionSpecParser.from_json(content)
        else:
            return MissionSpecParser.from_yaml(content)

    @staticmethod
    def from_yaml(content: str) -> MissionSpec:
        """Parse mission spec from YAML string."""
        data = yaml.safe_load(content)
        return MissionSpecParser._parse_dict(data)

    @staticmethod
    def from_json(content: str) -> MissionSpec:
        """Parse mission spec from JSON string."""
        data = json.loads(content)
        return MissionSpecParser._parse_dict(data)

    @staticmethod
    def from_file(path: Union[str, Path]) -> MissionSpec:
        """Parse mission spec from file (YAML or JSON)."""
        content = Path(path).read_text(encoding="utf-8")
        return MissionSpecParser.parse(content)

    @staticmethod
    def _parse_dict(data: Dict[str, Any]) -> MissionSpec:
        """Parse mission spec from dictionary."""
        # Validate required fields
        if "id" not in data:
            raise ValueError("Mission spec missing required field: 'id'")
        if "goal" not in data:
            raise ValueError("Mission spec missing required field: 'goal'")
        if "tasks" not in data:
            raise ValueError("Mission spec missing required field: 'tasks'")

        task_dicts = data["tasks"]
        if not isinstance(task_dicts, list):
            raise ValueError("'tasks' must be a list")

        # Parse defaults
        defaults_data = data.get("defaults", {})
        if isinstance(defaults_data, MissionDefaults):
            defaults = defaults_data
        elif isinstance(defaults_data, dict):
            defaults = MissionDefaults(
                max_attempts=int(defaults_data.get("max_attempts", 3)),
                execution_timeout=int(defaults_data.get("execution_timeout", 600)),
                verification_timeout=int(
                    defaults_data.get("verification_timeout", 300)
                ),
                executor=str(defaults_data.get("executor", "omp")),
                working_directory=defaults_data.get("working_directory"),
                model=defaults_data.get("model"),
                system_changes=str(defaults_data.get("system_changes", "DENIED")),
            )
        else:
            defaults = MissionDefaults()

        spec_executor = data.get("executor") or defaults.executor
        spec_working_directory = (
            data.get("working_directory") or defaults.working_directory
        )
        spec_model = data.get("model") or defaults.model
        spec_execution_timeout = (
            data.get("execution_timeout") or defaults.execution_timeout
        )
        spec_verification_timeout = (
            data.get("verification_timeout") or defaults.verification_timeout
        )
        spec_system_changes = str(
            data.get("system_changes") or defaults.system_changes or "DENIED"
        )

        task_ids = set()
        tasks = []

        for i, task_data in enumerate(task_dicts):
            if not isinstance(task_data, dict):
                raise ValueError(f"Task at index {i} must be a dictionary")

            # Validate required fields
            if "id" not in task_data:
                raise ValueError(f"Task at index {i} missing required field: 'id'")
            if "title" not in task_data:
                raise ValueError(
                    f"Task '{task_data.get('id', f'at index {i}')}' missing required field: 'title'"
                )
            if "prompt" not in task_data:
                raise ValueError(
                    f"Task '{task_data.get('id', f'at index {i}')}' missing required field: 'prompt'"
                )

            task_id = task_data["id"]
            if task_id in task_ids:
                raise ValueError("Duplicate task IDs")
            task_ids.add(task_id)

            # Process dependencies
            depends_on = task_data.get("depends_on", [])
            if not isinstance(depends_on, list):
                raise ValueError(f"Task '{task_id}' depends_on must be a list")

            # Validate self-dependency
            if task_id in depends_on:
                raise ValueError(
                    f"Task '{task_id}' cannot depend on itself: cyclic dependencies detected"
                )

            # Validate all dependencies exist
            for dep_id in depends_on:
                if dep_id not in task_ids:
                    raise ValueError(
                        f"Task validation failed: missing dependency '{dep_id}'"
                    )

            # Build task commands (multi-command verification support)
            command_data = task_data.get("command")
            if command_data is None:
                command_data = task_data.get("verify")

            commands: List[VerificationCommand] = []
            if command_data is not None:
                if isinstance(command_data, str):
                    commands = [VerificationCommand(command=command_data)]
                elif isinstance(command_data, dict):
                    commands = [VerificationCommand(**command_data)]
                elif isinstance(command_data, list):
                    for item in command_data:
                        if isinstance(item, str):
                            commands.append(VerificationCommand(command=item))
                        elif isinstance(item, dict):
                            commands.append(VerificationCommand(**item))

            primary_command = commands[0] if commands else None

            task_executor = task_data.get("executor")
            task_working_directory = task_data.get("working_directory")
            task_model = task_data.get("model")
            task_exec_timeout = task_data.get("execution_timeout")
            task_commit_paths = task_data.get("commit_paths")

            tasks.append(
                Task(
                    id=task_id,
                    title=task_data["title"],
                    prompt=task_data["prompt"],
                    depends_on=depends_on,
                    command=primary_command,
                    commands=commands,
                    executor=task_executor,
                    working_directory=task_working_directory,
                    model=task_model,
                    execution_timeout=task_exec_timeout,
                    commit_paths=task_commit_paths,
                    metadata=task_data.get("metadata", {}),
                )
            )

        return MissionSpec(
            id=data["id"],
            goal=data["goal"],
            tasks=tasks,
            defaults=defaults,
            executor=spec_executor,
            working_directory=spec_working_directory,
            model=spec_model,
            execution_timeout=spec_execution_timeout,
            verification_timeout=spec_verification_timeout,
            system_changes=spec_system_changes,
        )

    @staticmethod
    def validate(spec: MissionSpec) -> List[str]:
        """Validate a parsed mission spec and return list of warnings."""
        warnings = []

        # Check for cycles
        if not MissionSpecParser._check_cycles(spec.tasks):
            warnings.append("Cyclic dependencies detected in mission")

        return warnings

    @staticmethod
    def _check_cycles(tasks: List[Task]) -> bool:
        """Check for cycles in task dependencies using Kahn's algorithm."""
        # Build adjacency list and in-degree count
        adj: Dict[str, List[str]] = {task.id: [] for task in tasks}
        in_degree: Dict[str, int] = {task.id: 0 for task in tasks}

        for task in tasks:
            for dep_id in task.depends_on:
                if dep_id in adj:
                    adj[dep_id].append(task.id)
                    in_degree[task.id] += 1

        # Kahn's algorithm
        queue = [task_id for task_id, degree in in_degree.items() if degree == 0]
        processed = 0

        while queue:
            current = queue.pop(0)
            processed += 1
            for neighbor in adj[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        return processed == len(tasks)
