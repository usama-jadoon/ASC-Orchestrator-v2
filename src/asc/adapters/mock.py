from src.asc.models import Task


class MockResult:
    """Mock verification result."""
    def __init__(self, exit_code: int = 0, output: str = ""):
        self.exit_code = exit_code
        self.output = output


class MockAdapter:
    """Concrete mock adapter for testing."""
    def can_execute(self) -> bool:
        """Check if command can execute."""
        return True

    def prepare(self) -> None:
        """Prepare environment for command execution."""
        pass

    def execute(self, task: Task, context: dict) -> MockResult:
        """Execute command and return mock result."""
        return MockResult(exit_code=0, output="Verification passed")
