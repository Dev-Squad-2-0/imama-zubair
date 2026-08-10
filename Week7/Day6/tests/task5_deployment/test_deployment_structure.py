import ast
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


class DeploymentStructureTests(unittest.TestCase):
    def test_required_deployment_files_exist(self):
        required = [
            ROOT / "Dockerfile",
            ROOT / "docker-compose.yml",
            ROOT / ".dockerignore",
            ROOT / ".env.example",
            ROOT / "scripts" / "healthcheck.py",
            ROOT / "src" / "deployment_api.py",
            ROOT / "src" / "logging_config.py",
            ROOT / ".github" / "workflows" / "ci.yml",
        ]

        for path in required:
            self.assertTrue(path.exists(), str(path))

    def test_fastapi_has_required_health_routes(self):
        text = (ROOT / "src" / "deployment_api.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"/health/live"', text)
        self.assertIn('"/health/ready"', text)
        self.assertIn('"/health"', text)
        self.assertIn('"/metrics/summary"', text)
        self.assertIn('"/v1/conversation/turn"', text)

    def test_deployment_api_uses_current_graph(self):
        text = (ROOT / "src" / "deployment_api.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("import graph", text)
        self.assertIn("graph.run_turn", text)

    def test_docker_runs_deployment_api(self):
        text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("src.deployment_api:app", text)
        self.assertIn("HEALTHCHECK", text)

    def test_env_example_does_not_contain_real_secrets(self):
        text = (ROOT / ".env.example").read_text(encoding="utf-8")
        dangerous_examples = [
            "sk-proj-",
            "gsk_",
            "AIzaSy",
        ]
        for value in dangerous_examples:
            self.assertNotIn(value, text)

    def test_ci_builds_and_smoke_tests_container(self):
        text = (
            ROOT / ".github" / "workflows" / "ci.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("docker build", text)
        self.assertIn("/health/live", text)
        self.assertIn("/health/ready", text)


if __name__ == "__main__":
    unittest.main()
