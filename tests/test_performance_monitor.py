"""Run without extra packages: python3 -m unittest discover -s tests -p test_performance_monitor.py."""
import importlib.util
import json
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'tools/performance_monitor.py'
SPEC = importlib.util.spec_from_file_location('performance_monitor', SCRIPT)
monitor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(monitor)


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def event(self, kind, node='scene', **fields):
        return json.dumps(dict(event=kind, node_id=node, ts='2026-09-17T00:00:00Z', **fields)) + '\n'

    def test_incremental_partial_lines_and_truncation(self):
        path = self.root / 'events.jsonl'
        first = self.event('session_start')
        path.write_text(first + '{"event":')
        tail = monitor.TraceTail()
        self.assertEqual(tail.poll(path)['active_sessions'], 1)
        with path.open('a') as stream:
            stream.write('"session_start","node_id":"child"}\ninvalid\n')
        state = tail.poll(path)
        self.assertEqual(state['active_sessions'], 2)
        self.assertEqual(state['trace_peak_active'], 2)
        self.assertEqual(state['malformed_lines'], 1)
        self.assertEqual(tail.poll(path)['session_starts'], 2)
        path.write_text(first)
        self.assertEqual(tail.poll(path)['session_starts'], 1)

    def test_root_stop_and_resume(self):
        path = self.root / 'events.jsonl'
        path.write_text(self.event('session_start') + self.event('session_start', 'child')
                        + self.event('stop', parent_id='-', depth=0))
        tail = monitor.TraceTail()
        state = tail.poll(path)
        self.assertEqual(state['active_sessions'], 0)
        self.assertTrue(state['root_stopped'])
        with path.open('a') as stream:
            stream.write(self.event('session_start'))
        state = tail.poll(path)
        self.assertEqual(state['active_sessions'], 1)
        self.assertFalse(state['root_stopped'])

    def test_discovery_of_later_sequential_runs(self):
        for name in ('medieval-r1', 'city-r1'):
            path = self.root / name / 'runs' / name / 'trace/events.jsonl'
            path.parent.mkdir(parents=True)
            path.write_text('')
            self.assertIn(path, monitor.trace_paths(self.root))
            self.assertEqual(monitor.trace_paths(path.parent.parent), [path])
        self.assertEqual(len(monitor.trace_paths(self.root)), 2)

    def test_trace_read_is_bounded(self):
        path = self.root / 'events.jsonl'
        path.write_text(self.event('session_start') * 10)
        tail = monitor.TraceTail()
        with patch.object(monitor, 'READ_LIMIT', 100):
            state = tail.poll(path)
        self.assertEqual(tail.offset, 100)
        self.assertGreater(state['unread_bytes'], 0)

    def test_cpu_excludes_duplicate_guest_counters(self):
        busy, wait = monitor.cpu_delta([0] * 10, [20, 0, 10, 60, 10, 0, 0, 0, 20, 0])
        self.assertEqual(busy, 30)
        self.assertEqual(wait, 10)

    def test_process_tree_handles_spaces_in_names_and_exclusion(self):
        def process(pid, children):
            directory = self.root / str(pid)
            (directory / 'task' / str(pid)).mkdir(parents=True)
            fields = ['S'] + ['0'] * 21
            fields[11], fields[12], fields[19], fields[21] = '10', '20', '123', '5'
            (directory / 'stat').write_text(f'{pid} (name with ) spaces) ' + ' '.join(fields))
            (directory / 'task' / str(pid) / 'children').write_text(children)
        process(100, '101 102')
        process(101, '')
        tree = monitor.process_tree(100, self.root, exclude=101)
        self.assertEqual(list(tree), [(100, 123)])
        self.assertEqual(tree[(100, 123)]['ticks'], 30)

    def test_report_weights_intervals_and_tolerates_partial_last_line(self):
        log = self.root / 'performance.jsonl'
        rows = [dict(type='metadata', target=str(self.root), logical_cpus=4)]
        for elapsed, interval, busy in ((1, 1, 20), (4, 3, 60)):
            rows.append(dict(type='sample', elapsed_seconds=elapsed, interval_seconds=interval,
                             resources={'host_cpu_busy_pct': busy}, runs={}))
        log.write_text(''.join(json.dumps(row) + '\n' for row in rows) + '{"type":')
        report = monitor.render_report(log)
        self.assertIn('| host_cpu_busy_pct | 50.00 | 20.00 | 60.00 |', report)

    @unittest.skipUnless(Path('/proc/stat').exists(), 'Linux only')
    def test_live_duration_and_no_overwrite(self):
        log = self.root / 'performance.jsonl'
        args = [sys.executable, str(SCRIPT), 'watch', str(self.root), '--interval', '0.03',
                '--duration', '0.08', '--output', str(log)]
        result = subprocess.run(args, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertGreaterEqual(sum(row['type'] == 'sample' for row in rows), 2)
        self.assertEqual(rows[-1]['reason'], 'duration reached')
        self.assertTrue(log.with_suffix('.md').exists())
        before = log.read_bytes()
        self.assertNotEqual(subprocess.run(args, capture_output=True, timeout=5).returncode, 0)
        self.assertEqual(log.read_bytes(), before)
        log.with_suffix('.md').unlink()
        self.assertNotEqual(subprocess.run(args, capture_output=True, timeout=5).returncode, 0)
        self.assertEqual(log.read_bytes(), before)

    @unittest.skipUnless(Path('/proc/stat').exists(), 'Linux only')
    def test_rejects_log_report_path_collision(self):
        path = self.root / 'performance.md'
        result = subprocess.run([sys.executable, str(SCRIPT), 'watch', str(self.root),
                                 '--duration', '0.01', '--output', str(path)],
                                capture_output=True, text=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(path.exists())

    @unittest.skipUnless(Path('/proc/stat').exists(), 'Linux only')
    def test_signal_writes_report_without_killing_watched_process(self):
        sleeper = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        log = self.root / 'signal.jsonl'
        process = subprocess.Popen([sys.executable, str(SCRIPT), 'watch', str(self.root),
                                    '--pid', str(sleeper.pid), '--output', str(log)],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 5
            while not log.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(log.exists())
            process.send_signal(signal.SIGTERM)
            _, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, stderr)
            self.assertIsNone(sleeper.poll())
            self.assertTrue(log.with_suffix('.md').exists())
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate()
            sleeper.terminate()
            sleeper.wait(timeout=5)

    @unittest.skipUnless(Path('/proc/stat').exists(), 'Linux only')
    def test_auto_stop_on_watched_process_exit(self):
        sleeper = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(0.4)'])
        try:
            result = subprocess.run([sys.executable, str(SCRIPT), 'watch', str(self.root),
                                     '--pid', str(sleeper.pid), '--interval', '0.03'],
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            log = next(self.root.glob('*.jsonl'))
            self.assertEqual(json.loads(log.read_text().splitlines()[-1])['reason'],
                             'watched process exited')
        finally:
            if sleeper.poll() is None:
                sleeper.terminate()
            sleeper.wait(timeout=5)


    def fake_host(self):
        (self.root / 'stat').write_text('cpu 10 0 10 80 0 0 0 0 0 0\n')
        (self.root / 'meminfo').write_text('MemTotal: 2048 kB\nMemAvailable: 1024 kB\n'
                                           'SwapTotal: 1024 kB\nSwapFree: 512 kB\n')
        (self.root / 'loadavg').write_text('0.5 0.2 0.1 1/10 123\n')

    def test_resource_failure_is_null_and_recovers_without_cpu_spike(self):
        self.fake_host()
        resource = monitor.Resources(proc=self.root)
        self.assertIsNone(resource.sample(1)['host_cpu_busy_pct'])
        (self.root / 'stat').unlink()
        failed = resource.sample(2)
        self.assertIsNone(failed['host_cpu_busy_pct'])
        self.assertEqual(failed['host_memory_available_mib'], 1)
        self.assertEqual(len(resource.errors), 1)
        (self.root / 'stat').write_text('cpu 1000 0 1000 8000 0 0 0 0\n')
        self.assertIsNone(resource.sample(3)['host_cpu_busy_pct'])
        (self.root / 'stat').write_text('cpu 1010 0 1010 8080 0 0 0 0\n')
        self.assertEqual(resource.sample(4)['host_cpu_busy_pct'], 20)
        self.assertEqual(resource.errors, [])

    def test_missing_memory_and_bad_load_do_not_hide_cpu(self):
        self.fake_host()
        resource = monitor.Resources(proc=self.root)
        resource.sample(1)
        (self.root / 'meminfo').write_text('unexpected\n')
        (self.root / 'loadavg').write_text('nan\n')
        (self.root / 'stat').write_text('cpu 20 0 20 160 0 0 0 0\n')
        result = resource.sample(2)
        self.assertEqual(result['host_cpu_busy_pct'], 20)
        self.assertIsNone(result['host_memory_total_mib'])
        self.assertIsNone(result['host_load1'])
        self.assertEqual(len(resource.errors), 2)

    def test_pid_reuse_does_not_inherit_old_cpu_counters(self):
        self.fake_host()
        resource = monitor.Resources(pid=123, proc=self.root)
        old = {(123, 100): dict(ticks=10, rss_pages=1)}
        reused = {(123, 200): dict(ticks=50000, rss_pages=1)}
        with patch.object(monitor, 'process_tree', side_effect=[old, reused]):
            resource.sample(1)
            self.assertEqual(resource.sample(2)['process_cpu_pct'], 0)

    def test_unreadable_pid_is_not_reported_as_idle(self):
        self.fake_host()
        resource = monitor.Resources(pid=123, proc=self.root)
        with patch.object(monitor, 'process_stat', side_effect=PermissionError('denied')):
            result = resource.sample(1)
        self.assertIsNone(result['process_cpu_pct'])
        self.assertIsNone(result['process_count'])
        self.assertTrue(resource.errors)

    def test_trace_rotation_and_temporary_disappearance(self):
        path = self.root / 'events.jsonl'
        path.write_text(self.event('session_start', 'old'))
        tail = monitor.TraceTail()
        self.assertEqual(tail.poll(path)['session_starts'], 1)
        path.rename(self.root / 'events.old')
        self.assertIsNone(tail.poll(path))
        path.write_text(self.event('session_start', 'new') + self.event('session_end', 'new'))
        result = tail.poll(path)
        self.assertEqual(result['session_starts'], 1)
        self.assertEqual(result['active_sessions'], 0)

    def test_oversize_and_deeply_nested_trace_records_are_skipped(self):
        path = self.root / 'events.jsonl'
        path.write_text('x' * 300 + '\n' + self.event('session_start'))
        tail = monitor.TraceTail()
        with patch.object(monitor, 'READ_LIMIT', 100):
            for _ in range(5):
                result = tail.poll(path)
        self.assertEqual(result['session_starts'], 1)
        with path.open('a') as stream:
            stream.write('[' * 2000 + '0' + ']' * 2000 + '\n' + self.event('session_end'))
        result = tail.poll(path)
        self.assertEqual(result['active_sessions'], 0)
        self.assertGreaterEqual(result['malformed_lines'], 2)

    @unittest.skipUnless(hasattr(__import__('os'), 'mkfifo'), 'POSIX only')
    def test_fifo_does_not_block_trace_poll(self):
        import os
        path = self.root / 'events.jsonl'
        os.mkfifo(path)
        self.assertIsNone(monitor.TraceTail().poll(path))

    def test_report_tolerates_valid_json_with_wrong_shapes(self):
        path = self.root / 'damaged.jsonl'
        path.write_text('[]\nnull\n{"type":"sample"}\n'
                        '{"type":"sample","elapsed_seconds":NaN,"interval_seconds":1,"resources":{}}\n'
                        '{"type":"sample","elapsed_seconds":2,"interval_seconds":1,'
                        '"resources":{"host_load1":null,"bad":"string","bad2":Infinity},"runs":{"a":null}}\n')
        report = monitor.render_report(path)
        self.assertIn('Samples: 1;', report)
        self.assertIn('Skipped malformed/incomplete records: 4', report)
        self.assertNotIn('| bad', report)

    @unittest.skipUnless(Path('/proc/stat').exists(), 'Linux only')
    def test_sampling_error_still_writes_report(self):
        from argparse import Namespace
        log = self.root / 'failure.jsonl'
        args = Namespace(target=self.root, pid=None, output=log, interval=0.01, duration=1)
        with patch.object(monitor.signal, 'signal'), \
             patch.object(monitor.Resources, 'sample', side_effect=OSError('injected read failure')):
            with self.assertRaises(OSError):
                monitor.watch(args)
        self.assertIn('monitor error', log.with_suffix('.md').read_text())
        self.assertEqual(json.loads(log.read_text().splitlines()[-1])['type'], 'end')

    @unittest.skipUnless(Path('/proc/stat').exists(), 'Linux only')
    def test_failed_log_write_preserves_prior_records_and_report(self):
        from argparse import Namespace
        import errno
        log = self.root / 'write-failure.jsonl'
        args = Namespace(target=self.root, pid=None, output=log, interval=0.01, duration=1)
        original_open = Path.open

        class FailingWriter:
            def __init__(self, stream):
                self.stream = stream
                self.writes = 0

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.stream.close()

            def write(self, value):
                self.writes += 1
                if self.writes > 2:
                    raise OSError(errno.ENOSPC, 'injected full disk')
                return self.stream.write(value)

        def open_file(path, *args, **kwargs):
            stream = original_open(path, *args, **kwargs)
            return FailingWriter(stream) if path == log and args and args[0] == 'x' else stream

        with patch.object(monitor.signal, 'signal'), patch.object(Path, 'open', open_file):
            with self.assertRaises(OSError):
                monitor.watch(args)
        self.assertEqual(len(log.read_text().splitlines()), 2)
        self.assertIn('Samples: 1;', log.with_suffix('.md').read_text())

    @unittest.skipUnless(Path('/proc/stat').exists(), 'Linux only')
    def test_four_sequential_runs_with_parallel_children(self):
        batch_code = r'''
import json, pathlib, subprocess, sys, time
root = pathlib.Path(sys.argv[1])
while not (root / 'go').exists():
    time.sleep(0.01)
for name in ('medieval-r1', 'medieval-r2', 'city-r1', 'city-r2'):
    trace = root / name / 'runs' / name / 'trace/events.jsonl'
    trace.parent.mkdir(parents=True)
    def emit(kind, node='scene', **extra):
        line = json.dumps(dict(event=kind, node_id=node, **extra)) + '\n'
        with trace.open('a') as stream:
            stream.write(line[:12]); stream.flush(); time.sleep(0.005)
            stream.write(line[12:])
    emit('session_start')
    emit('session_end')
    emit('session_start', 'a')
    emit('session_start', 'b')
    children = [subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(0.12)']) for _ in range(2)]
    for child in children:
        child.wait()
    emit('session_end', 'a')
    emit('session_end', 'b')
    emit('session_start')
    emit('session_end')
    emit('stop', parent_id='-', depth=0)
'''
        batch = subprocess.Popen([sys.executable, '-c', batch_code, str(self.root)])
        log = self.root / 'four-runs.jsonl'
        watcher = subprocess.Popen([sys.executable, str(SCRIPT), 'watch', str(self.root),
                                    '--pid', str(batch.pid), '--interval', '0.02', '--output', str(log)],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 5
            while not log.exists() and watcher.poll() is None and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(log.exists())
            (self.root / 'go').touch()
            batch.wait(timeout=10)
            _, stderr = watcher.communicate(timeout=10)
            self.assertEqual(batch.returncode, 0)
            self.assertEqual(watcher.returncode, 0, stderr)
            rows = [json.loads(line) for line in log.read_text().splitlines()]
            samples = [row for row in rows if row['type'] == 'sample']
            self.assertEqual(len(samples[-1]['runs']), 4)
            for state in samples[-1]['runs'].values():
                self.assertEqual((state['session_starts'], state['session_ends']), (4, 4))
                self.assertEqual(state['trace_peak_active'], 2)
                self.assertEqual(state['active_sessions'], 0)
                self.assertTrue(state['root_stopped'])
                self.assertEqual(state['malformed_lines'], 0)
            self.assertEqual(rows[-1]['reason'], 'watched process exited')
            self.assertTrue(log.with_suffix('.md').exists())
        finally:
            for process in (batch, watcher):
                if process.poll() is None:
                    process.kill()
            batch.wait()
            watcher.communicate()


    @unittest.skipUnless(Path('/proc/stat').exists(), 'Linux only')
    def test_watch_retries_unreadable_pid_then_detects_reuse(self):
        from argparse import Namespace
        log = self.root / 'pid-reuse.jsonl'
        args = Namespace(target=self.root, pid=123, output=log, interval=0.001, duration=1)
        identity = dict(start=100, state='S')
        with patch.object(monitor.signal, 'signal'), patch.object(monitor, 'Resources') as resources, \
             patch.object(monitor, 'process_stat', side_effect=[
                 identity, PermissionError('temporary'), identity, dict(start=200, state='S')]):
            resources.return_value.sample.return_value = {}
            resources.return_value.errors = []
            monitor.watch(args)
        rows = [json.loads(line) for line in log.read_text().splitlines()]
        samples = [row for row in rows if row['type'] == 'sample']
        self.assertEqual(len(samples), 3)
        self.assertIn('temporarily unreadable', samples[0]['warnings'][0])
        self.assertEqual(rows[-1]['reason'], 'watched process exited')

    @unittest.skipUnless(Path('/proc/stat').exists(), 'Linux only')
    def test_report_survives_monitor_sigkill(self):
        log = self.root / 'killed.jsonl'
        watcher = subprocess.Popen([sys.executable, str(SCRIPT), 'watch', str(self.root),
                                    '--output', str(log)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if log.exists() and len(log.read_text().splitlines()) >= 2:
                    break
                time.sleep(0.01)
            self.assertTrue(log.exists())
            watcher.kill()
            watcher.communicate(timeout=5)
            result = subprocess.run([sys.executable, str(SCRIPT), 'report', str(log)],
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Samples: 1;', result.stdout)
            self.assertIn('interrupted without a final record', result.stdout)
        finally:
            if watcher.poll() is None:
                watcher.kill()
            watcher.communicate()


if __name__ == '__main__':
    unittest.main()
