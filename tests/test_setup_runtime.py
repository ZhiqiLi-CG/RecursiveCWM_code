"""Exercise Python setup without downloading packages or launching the renderer.

Run with: python3 -m unittest discover -s tests -p test_setup_runtime.py
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

REPO = Path(__file__).resolve().parents[1]


class PythonSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='rcwm-setup-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'runtime'
        self.log = self.base / 'calls.jsonl'
        self.env = dict(os.environ, SETUP_TEST_LOG=str(self.log), PYTHONOPTIMIZE='1')
        self.env.pop('PYTHON', None)

    def interpreter(self, path, version=(3, 12, 3), implementation='cpython'):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'#!{sys.executable}\n' + textwrap.dedent(f'''
            import json, os, pathlib, shutil, sys
            args = sys.argv[1:]
            with open(os.environ['SETUP_TEST_LOG'], 'a') as log:
                log.write(json.dumps(args) + '\\n')
            args = [arg for arg in args if arg not in ('-I', '--isolated')]
            if args[0] == '-':
                sys.version_info = {version!r}
                sys.version = {'.'.join(map(str, version))!r}
                sys.implementation.name = {implementation!r}
                sys.argv = ['-'] + args[1:]
                exec(compile(sys.stdin.read(), '<setup-check>', 'exec'))
            elif args[0] == '-c':
                print(str(pathlib.Path(__file__).resolve()))
            elif args[:2] == ['-m', 'venv']:
                dest = pathlib.Path(args[2]) / 'bin' / 'python'
                dest.parent.mkdir(parents=True)
                shutil.copy2(__file__, dest)
            elif args[:2] == ['-m', 'pip']:
                # Let installs be recorded; stop at pip check before any rendering setup.
                sys.exit(73 if args[2:] == ['check'] else 0)
            else:
                sys.exit('unexpected interpreter call: ' + repr(args))
        '''))
        path.chmod(0o755)
        return path

    def run_setup(self, *args):
        return subprocess.run(
            ['bash', str(REPO / 'setup/setup_runtime.sh'), str(self.root), *map(str, args)],
            env=self.env, capture_output=True, text=True,
        )

    def calls(self):
        return [[arg for arg in json.loads(line) if arg not in ('-I', '--isolated')]
                for line in self.log.read_text().splitlines()]

    def test_incompatible_python_rejected_before_venv_even_with_optimization(self):
        for minor in (9, 10, 11, 13, 14):
            with self.subTest(minor=minor):
                py = self.interpreter(self.base / 'python', (3, minor, 0))
                result = self.run_setup('--python', py)
                self.assertEqual(result.returncode, 1)
                self.assertIn('CPython 3.12.x required', result.stderr)
                self.assertIn(f'3.{minor}.0', result.stderr)
                self.assertFalse((self.root / '.venv').exists())
        self.assertTrue(all(args[0] == '-' for args in self.calls()))

    def test_pypy_is_rejected(self):
        result = self.run_setup('--python', self.interpreter(self.base / 'python', implementation='pypy'))
        self.assertEqual(result.returncode, 1)
        self.assertIn('got pypy', result.stderr)

    def test_supported_python_creates_venv_and_checks_packages(self):
        result = self.run_setup('--python', self.interpreter(self.base / 'python', (3, 12, 99)))
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertTrue((self.root / '.venv/bin/python').exists())
        self.assertIn(['-m', 'pip', 'check'], self.calls())
        self.assertFalse((self.root / '.render-tools').exists())

    def test_metrics_resolved_with_runtime_pins(self):
        result = self.run_setup('--python', self.interpreter(self.base / 'python'), '--metrics')
        self.assertEqual(result.returncode, 1, result.stderr)
        installs = [args for args in self.calls() if '-r' in args]
        self.assertEqual(installs, [[
            '-m', 'pip', 'install', '--quiet',
            '-r', str(REPO / 'setup/requirements-metrics.txt'),
        ]])

    def test_existing_invalid_venv_explains_recovery(self):
        old = self.interpreter(self.root / '.venv/bin/python', (3, 11, 0))
        original = old.read_text()
        result = self.run_setup('--python', self.interpreter(self.base / 'python'))
        self.assertEqual(result.returncode, 1)
        self.assertIn('--recreate-venv or choose a new runtime directory', result.stderr)
        self.assertIn('--python only selects', result.stderr)
        self.assertEqual(old.read_text(), original)
        self.assertFalse(any(args[0] == '-m' for args in self.calls()))

    def test_default_prefers_python312_over_python3(self):
        self.interpreter(self.base / 'bin/python3.12')
        self.interpreter(self.base / 'bin/python3', (3, 13, 0))
        self.env['PATH'] = str(self.base / 'bin') + os.pathsep + self.env['PATH']
        result = self.run_setup()
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_explicit_python_overrides_environment(self):
        self.env['PYTHON'] = str(self.interpreter(self.base / 'bad-python', (3, 11, 0)))
        result = self.run_setup('--python', self.interpreter(self.base / 'good-python'))
        self.assertEqual(result.returncode, 1, result.stderr)

    def conda(self, version, missing=False):
        prefix = self.base / 'conda-env'
        self.interpreter(prefix / 'bin/python', version)
        (prefix / 'conda-meta').mkdir()
        conda = self.base / 'conda'
        conda.write_text(f'#!{sys.executable}\n' + textwrap.dedent(f'''
            import json, os, sys
            args = sys.argv[1:]
            with open(os.environ['SETUP_TEST_LOG'], 'a') as log:
                log.write(json.dumps(args) + '\\n')
            if args[0] == 'create':
                sys.exit(0)
            if args[-1] == '--version':
                sys.exit({int(missing)})
            print({str(prefix)!r})
        '''))
        conda.chmod(0o755)
        self.env['RCWM_CONDA'] = str(conda)
        return prefix

    def test_invalid_conda_does_not_replace_existing_link(self):
        self.root.mkdir()
        old = self.base / 'old-env'
        old.mkdir()
        (self.root / '.venv').symlink_to(old)
        self.conda((3, 13, 0))
        result = self.run_setup('--conda', 'rcwm')
        self.assertEqual(result.returncode, 1)
        self.assertEqual((self.root / '.venv').resolve(), old)
        self.assertIn('CPython 3.12.x required', result.stderr)

    def test_new_conda_uses_canonical_version(self):
        prefix = self.conda((3, 12, 3), missing=True)
        result = self.run_setup('--conda', 'rcwm')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse((self.root / '.venv').is_symlink())
        self.assertIn(['-m', 'venv', str(self.root / '.venv')], self.calls())
        self.assertIn(['create', '-y', '-q', '--no-default-packages', '-n', 'rcwm', 'python=3.12'], self.calls())
        self.assertTrue((prefix / 'bin/python').exists())


    def test_recreate_backs_up_existing_environment(self):
        self.interpreter(self.root / '.venv/bin/python')
        (self.root / '.venv/old-package').write_text('preserve me')
        self.root.joinpath('runs').mkdir()
        self.root.joinpath('runs/result.json').write_text('{}')
        result = self.run_setup('--python', self.interpreter(self.base / 'python'), '--recreate-venv')
        self.assertEqual(result.returncode, 1)
        backups = list(self.root.glob('.venv-backup.*/.venv/old-package'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), 'preserve me')
        self.assertFalse((self.root / '.venv/old-package').exists())
        self.assertTrue((self.root / 'runs/result.json').exists())
        self.assertIn(['-m', 'pip', 'check'], self.calls())

    def test_old_conda_link_migrates_without_changing_source(self):
        prefix = self.conda((3, 12, 3))
        (prefix / 'old-package').write_text('preserve me')
        self.root.mkdir()
        (self.root / '.venv').symlink_to(prefix)
        result = self.run_setup()
        self.assertEqual(result.returncode, 1)
        self.assertFalse((self.root / '.venv').is_symlink())
        self.assertTrue((prefix / 'old-package').exists())
        backup = next(self.root.glob('.venv-backup.*/.venv'))
        self.assertTrue(backup.is_symlink())
        self.assertEqual(backup.resolve(), prefix)
        self.assertIn(['-m', 'pip', 'check'], self.calls())

    def test_python_and_pip_are_isolated(self):
        self.run_setup('--python', self.interpreter(self.base / 'python'))
        raw_calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        for args in raw_calls:
            self.assertEqual(args[0], '-I')
            if 'pip' in args:
                self.assertIn('--isolated', args)

    def test_pip_check_failure_explains_recovery(self):
        result = self.run_setup('--python', self.interpreter(self.base / 'python'))
        self.assertEqual(result.returncode, 1)
        self.assertIn('Runtime dependencies are inconsistent', result.stderr)
        self.assertIn('--recreate-venv', result.stderr)
        self.assertFalse((self.root / '.render-tools').exists())


if __name__ == '__main__':
    unittest.main()
