"""Exercise deployment control flow with fake Docker/HTTP; never touch a server."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/deploy_backend.sh'


class DeployBackendTests(unittest.TestCase):
    def run_deploy(self, mode):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / 'calls'
            scripts = {
                'docker': '''#!/bin/bash
printf '%s\\n' "$*" >> "$CALL_LOG"
if [[ "$MODE" == migration-fails && "$*" == *migrate* ]]; then exit 1; fi
exit 0
''',
                'curl': '#!/bin/bash\n[[ "$MODE" != unhealthy ]]\n',
                'sleep': '#!/bin/bash\nexit 0\n',
            }
            for name, content in scripts.items():
                file = root / name
                file.write_text(content)
                file.chmod(0o755)
            env = {**os.environ, 'PATH': str(root) + ':' + os.environ['PATH'],
                   'CALL_LOG': str(log), 'MODE': mode}
            result = subprocess.run(['bash', str(SCRIPT), 'test-image', '--env-file', 'test.env'],
                                    env=env, capture_output=True, text=True)
            return result.returncode, log.read_text()

    def test_migration_failure_preserves_running_container(self):
        code, calls = self.run_deploy('migration-fails')
        self.assertNotEqual(code, 0)
        self.assertNotIn('stop paper-scholar', calls)
        self.assertNotIn('rm -f', calls)

    def test_unhealthy_release_rolls_back_and_fails(self):
        code, calls = self.run_deploy('unhealthy')
        self.assertNotEqual(code, 0)
        self.assertIn('rename paper-scholar-previous paper-scholar', calls)
        self.assertIn('start paper-scholar', calls)

    def test_success_keeps_previous_container(self):
        code, calls = self.run_deploy('healthy')
        self.assertEqual(code, 0)
        self.assertIn('rename paper-scholar paper-scholar-previous', calls)
        self.assertNotIn('rename paper-scholar-previous paper-scholar', calls)
        self.assertIn('-e DEBUG=False', calls)
        self.assertIn('127.0.0.1:8000:8000', calls)
