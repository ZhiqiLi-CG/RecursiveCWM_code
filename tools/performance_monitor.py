#!/usr/bin/env python3
"""Low-frequency Linux resource sampling and incremental RCWM trace monitoring.

No third-party packages, network calls, subprocesses, or agent-log scans.
"""
import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import signal
import sys
import stat
import time


READ_LIMIT = 256 * 1024  # Maximum new trace bytes per run per sample.


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class TraceTail:
    def __init__(self):
        self.identity = None
        self.offset = 0
        self.pending = b''
        self.discard_line = False
        self.active = set()
        self.starts = self.ends = self.peak = self.malformed = 0
        self.last_event = None
        self.stopped = False

    def poll(self, path):
        try:
            # Nonblocking open plus a regular-file check avoids hanging on a stray FIFO.
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            with os.fdopen(fd, 'rb') as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode):
                    return None
                identity = (info.st_dev, info.st_ino)
                if self.identity != identity or info.st_size < self.offset:
                    self.__init__()
                    self.identity = identity
                stream.seek(self.offset)
                chunk = stream.read(READ_LIMIT)
                self.offset = stream.tell()
                backlog = max(0, info.st_size - self.offset)
        except OSError:
            return None
        if self.discard_line:
            _, separator, chunk = chunk.partition(b'\n')
            self.discard_line = not bool(separator)
        lines = (self.pending + chunk).split(b'\n')
        self.pending = lines.pop()
        # Bound memory even for a corrupt trace with no newline.
        if len(self.pending) > READ_LIMIT:
            self.pending = b''
            self.discard_line = True
            self.malformed += 1
        for line in lines:
            try:
                event = json.loads(line)
                node = event['node_id']
                kind = event['event']
                if not isinstance(node, str) or not isinstance(kind, str):
                    raise ValueError('invalid node')
            except (ValueError, KeyError, TypeError, RecursionError):
                self.malformed += 1
                continue
            self.last_event = event.get('ts') if isinstance(event.get('ts'), str) else None
            if kind == 'session_start':
                self.active.add(node)
                self.starts += 1
                self.stopped = False
            elif kind == 'session_end':
                self.active.discard(node)
                self.ends += 1
            elif kind == 'stop':
                self.active.discard(node)
                if event.get('parent_id') in ('-', None) and event.get('depth') == 0:
                    self.stopped = True
                    self.active.clear()
            self.peak = max(self.peak, len(self.active))
        return dict(active_sessions=len(self.active), session_starts=self.starts,
                    session_ends=self.ends, trace_peak_active=self.peak,
                    root_stopped=self.stopped, last_event=self.last_event,
                    malformed_lines=self.malformed, unread_bytes=backlog)


def trace_paths(target):
    # Fixed-depth discovery only: never walk node directories or dependency trees.
    paths = set()
    direct = target / 'trace/events.jsonl'
    if direct.is_file():
        paths.add(direct)
    for pattern in ('runs/*/trace/events.jsonl', '*/runs/*/trace/events.jsonl'):
        paths.update(target.glob(pattern))
    return sorted(paths)


def process_stat(pid, proc=Path('/proc'), strict=False):
    try:
        raw = (proc / str(pid) / 'stat').read_text()
        fields = raw[raw.rfind(')') + 2:].split()
        return dict(state=fields[0], ticks=int(fields[11]) + int(fields[12]),
                    start=int(fields[19]), rss_pages=int(fields[21]))
    except (FileNotFoundError, ProcessLookupError):
        return None
    except (OSError, ValueError, IndexError):
        if strict:
            raise
        return None


def process_tree(pid, proc=Path('/proc'), exclude=None):
    result = {}
    todo = [pid]
    visited = set()
    while todo:
        current = todo.pop()
        if current in visited or current == exclude:
            continue
        visited.add(current)
        stat = process_stat(current, proc)
        if stat is None or stat['state'] == 'Z':
            continue
        result[(current, stat['start'])] = stat
        try:
            children = (proc / str(current) / 'task' / str(current) / 'children').read_text()
            todo.extend(map(int, children.split()))
        except (OSError, ValueError):
            pass
    return result


def cpu_delta(previous, current):
    # /proc/stat guest times are already included in user/nice; exclude duplicates.
    deltas = [max(0, b - a) for a, b in zip(previous[:8], current[:8])]
    total = sum(deltas)
    if len(deltas) < 5 or not total:
        return None, None
    return (100 * (total - deltas[3] - deltas[4]) / total,
            100 * deltas[4] / total)


class Resources:
    def __init__(self, pid=None, proc=Path('/proc')):
        self.pid, self.proc = pid, proc
        self.previous_cpu = None
        self.previous_tree = {}
        self.previous_time = None
        self.hz = os.sysconf('SC_CLK_TCK')
        self.page_size = os.sysconf('SC_PAGE_SIZE')

    def sample(self, now):
        result = dict.fromkeys(('host_cpu_busy_pct', 'host_cpu_iowait_pct', 'host_load1',
                                'host_memory_total_mib', 'host_memory_available_mib',
                                'host_swap_used_mib'))
        self.errors = []
        try:
            cpu = list(map(int, (self.proc / 'stat').read_text().splitlines()[0].split()[1:]))
            if len(cpu) < 5:
                raise ValueError('incomplete CPU counters')
            if self.previous_cpu is not None:
                result['host_cpu_busy_pct'], result['host_cpu_iowait_pct'] = cpu_delta(self.previous_cpu, cpu)
            self.previous_cpu = cpu
        except (OSError, ValueError, IndexError) as error:
            self.previous_cpu = None  # A later sample must not attribute a gap to one interval.
            self.errors.append(f'host CPU: {error}')
        try:
            mem = {}
            for line in (self.proc / 'meminfo').read_text().splitlines():
                key, value = line.split(':', 1)
                mem[key] = int(value.split()[0])
            result.update(host_memory_total_mib=mem['MemTotal'] / 1024,
                          host_memory_available_mib=(mem['MemAvailable'] if 'MemAvailable' in mem
                                                     else mem['MemFree']) / 1024,
                          host_swap_used_mib=(mem['SwapTotal'] - mem['SwapFree']) / 1024)
        except (OSError, ValueError, KeyError, IndexError) as error:
            self.errors.append(f'host memory: {error}')
        try:
            value = float((self.proc / 'loadavg').read_text().split()[0])
            if not math.isfinite(value):
                raise ValueError('nonfinite load')
            result['host_load1'] = value
        except (OSError, ValueError, IndexError) as error:
            self.errors.append(f'host load: {error}')
        if self.pid is not None:
            result.update(process_count=None, process_cpu_pct=None, process_rss_sum_mib=None)
            try:
                process_stat(self.pid, self.proc, strict=True)
            except (OSError, ValueError, IndexError) as error:
                self.errors.append(f'process tree: {error}')
                self.previous_tree = {}
                self.previous_time = now
                return result
            tree = process_tree(self.pid, self.proc, exclude=os.getpid())
            elapsed = now - self.previous_time if self.previous_time is not None else 0
            ticks = sum(max(0, value['ticks'] - self.previous_tree[key]['ticks'])
                        for key, value in tree.items() if key in self.previous_tree)
            result.update(process_count=len(tree),
                          process_cpu_pct=100 * ticks / self.hz / elapsed if elapsed > 0 else None,
                          process_rss_sum_mib=sum(x['rss_pages'] for x in tree.values())
                          * self.page_size / 1024 ** 2)
            self.previous_tree = tree
        self.previous_time = now
        return result


def finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def render_report(log):
    count = 0
    duration = 0
    aggregates = {}
    runs = {}
    metadata = {}
    reason = 'still running or interrupted without a final record'
    skipped = warnings = 0
    with log.open(errors='replace') as stream:
        for line in stream:
            try:
                row = json.loads(line)
            except (ValueError, RecursionError):
                skipped += 1
                continue  # Allow reports while the last line is being written.
            if not isinstance(row, dict):
                skipped += 1
                continue
            if row.get('type') == 'metadata':
                metadata = row
            elif row.get('type') == 'end':
                reason = row.get('reason', 'unknown')
            elif row.get('type') == 'sample':
                elapsed, weight = row.get('elapsed_seconds'), row.get('interval_seconds')
                if (not finite_number(elapsed) or not finite_number(weight)
                        or elapsed < 0 or weight < 0 or not isinstance(row.get('resources'), dict)):
                    skipped += 1
                    continue
                count += 1
                duration = max(duration, elapsed)
                warnings += len(row['warnings']) if isinstance(row.get('warnings'), list) else 0
                for name, value in row['resources'].items():
                    if not finite_number(value):
                        continue
                    item = aggregates.setdefault(name, [0, 0, value, value])
                    item[0] += value * weight
                    item[1] += weight
                    item[2] = min(item[2], value)
                    item[3] = max(item[3], value)
                if isinstance(row.get('runs'), dict):
                    runs.update({name: state for name, state in row['runs'].items()
                                 if isinstance(state, dict)})
    lines = ['# RCWM performance report', '', f"Target: `{metadata.get('target', '?')}`",
             f"Samples: {count}; observed duration: {duration / 60:.2f} minutes; stop: {reason}.",
             f'Skipped malformed/incomplete records: {skipped}; recorded sampling warnings: {warnings}.',
             '', '| Resource | Time-weighted mean | Minimum | Maximum |',
             '|---|---:|---:|---:|']
    for name, (total, weight, low, high) in aggregates.items():
        mean = f'{total / weight:.2f}' if weight else 'n/a'
        lines.append(f'| {name} | {mean} | {low:.2f} | {high:.2f} |')
    lines += ['', '## Recursion activity', '',
              '| Run (relative path) | Sessions started / ended | Peak active in trace | Active at last sample | Root stopped | Unread bytes |',
              '|---|---:|---:|---:|---|---:|']
    for run, state in sorted(runs.items()):
        lines.append(f"| {run} | {state.get('session_starts', '?')} / {state.get('session_ends', '?')} | "
                     f"{state.get('trace_peak_active', '?')} | {state.get('active_sessions', '?')} | "
                     f"{state.get('root_stopped', '?')} | {state.get('unread_bytes', '?')} |")
    lines += ['', '## Interpretation and limits', '',
              '- Host CPU percentages cover the whole machine, including unrelated workloads. '
              f"Logical CPUs reported: {metadata.get('logical_cpus', '?')}.",
              '- Process CPU uses 100% per fully occupied core. It covers sampled surviving '
              'processes under the watched PID, excluding this monitor. Short-lived processes, '
              'newly discovered processes, and detached/reparented workers can be missed.',
              '- Summed process RSS double-counts shared pages; it is not unique memory consumption. '
              'Low host available memory and swap use help identify possible memory pressure.',
              '- Recursion counts come from session start/end events, including history before attachment. '
              'An active session can be waiting on the API or tools. Missing events can leave stale counts; '
              'a root stop clears its active set. Unread bytes indicate trace catch-up is incomplete.',
              '- Sustained host CPU saturation or low available memory suggests local contention. '
              'Low CPU during active sessions is consistent with remote/tool waiting, but does not '
              'prove API throttling. This tool measures no provider latency, GPU utilization, or tokens.',
              '- Missing resource readings are null, not zero. Sampling warnings are recorded in the JSONL; '
              'transient read failures do not stop monitoring.',
              '- Resource statistics cover only the monitoring window; first-sample CPU is unavailable. '
              'A root stop event does not establish successful delivery.', '']
    return '\n'.join(lines)


def watch(args):
    if not Path('/proc/stat').exists():
        raise ValueError('watch requires Linux /proc')
    target = args.target.resolve()
    if not target.is_dir():
        raise ValueError(f'not a directory: {target}')
    identity = process_stat(args.pid, strict=True) if args.pid else None
    if args.pid and (not identity or identity['state'] == 'Z'):
        raise ValueError(f'PID {args.pid} is not running')
    log = args.output or target / (datetime.now(timezone.utc).strftime('performance-%Y%m%dT%H%M%S')
                                  + f'-{os.getpid()}.jsonl')
    log = log.resolve()
    if log.suffix != '.jsonl':
        raise ValueError('--output must have a .jsonl extension')
    report = log.with_suffix('.md')
    if report.exists():
        raise ValueError(f'report already exists: {report}')
    stop_requested = False

    def request_stop(*_):
        # Signal handlers must not acquire threading locks.
        nonlocal stop_requested
        stop_requested = True

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, request_stop)
    resources = Resources(args.pid)
    tails = {}
    start = previous = time.monotonic()
    reason = 'signal'
    created = False
    try:
        with log.open('x', buffering=1) as stream:
            created = True
            def emit(row):
                stream.write(json.dumps(row, allow_nan=False) + '\n')
            emit(dict(type='metadata', schema_version=1, ts=timestamp(), target=str(target),
                      watched_pid=args.pid, interval_seconds=args.interval,
                      logical_cpus=os.cpu_count()))
            print(f'Performance log: {log}', flush=True)
            try:
                while True:
                    now = time.monotonic()
                    runs, warnings = {}, []
                    try:
                        paths = trace_paths(target)
                    except OSError as error:
                        paths = []
                        warnings.append(f'trace discovery: {error}')
                    for path in sorted(set(paths) | set(tails)):
                        state = tails.setdefault(path, TraceTail()).poll(path)
                        if state is not None:
                            runs[str(path.parent.parent.relative_to(target))] = state
                        else:
                            warnings.append(f'trace unavailable or not a regular file: {path}')
                    usage = resources.sample(now)
                    warnings.extend(resources.errors)
                    exited = False
                    if args.pid:
                        try:
                            current = process_stat(args.pid, strict=True)
                            exited = (not current or current['state'] == 'Z'
                                      or current['start'] != identity['start'])
                        except (OSError, ValueError, IndexError) as error:
                            warnings.append(f'watched PID temporarily unreadable: {error}')
                    usage['monitor_sample_ms'] = (time.monotonic() - now) * 1000
                    emit(dict(type='sample', ts=timestamp(), elapsed_seconds=now - start,
                              interval_seconds=now - previous, resources=usage, runs=runs, warnings=warnings))
                    previous = now
                    if exited:
                        reason = 'watched process exited'
                        break
                    if args.duration and now - start >= args.duration:
                        reason = 'duration reached'
                        break
                    if stop_requested:
                        break
                    delay = args.interval
                    if args.duration:
                        delay = min(delay, max(0, args.duration - (time.monotonic() - start)))
                    deadline = time.monotonic() + delay
                    while not stop_requested and time.monotonic() < deadline:
                        time.sleep(min(0.5, max(0, deadline - time.monotonic())))
            except BaseException:
                reason = 'monitor error'
                raise
            finally:
                emit(dict(type='end', ts=timestamp(), reason=reason))
    finally:
        # Even if sampling or writing fails, summarize every intact record already on disk.
        # Never touch an existing log when exclusive creation itself failed.
        if created:
            sampling_failed = sys.exc_info()[0] is not None
            try:
                summary = render_report(log)
                with report.open('x') as output:
                    output.write(summary)
                print(f'Performance report: {report}', flush=True)
            except OSError as error:
                print(f'Could not write performance report: {error}; retained log: {log}',
                      file=sys.stderr, flush=True)
                if not sampling_failed:
                    raise


def positive(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError('must be a finite positive number')
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    sampling = commands.add_parser('watch', help='monitor a run, workspace, or batch directory')
    sampling.add_argument('target', type=Path)
    sampling.add_argument('--pid', type=int, help='batch/run PID; stop when it exits')
    sampling.add_argument('--interval', type=positive, default=10, help='seconds between samples (default: 10)')
    sampling.add_argument('--duration', type=positive, help='optional maximum monitoring seconds')
    sampling.add_argument('--output', type=Path, help='new JSONL path; refuses to overwrite')
    reporting = commands.add_parser('report', help='print a summary of a live or completed JSONL log')
    reporting.add_argument('log', type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'watch':
            if args.pid is not None and args.pid <= 0:
                parser.error('--pid must be positive')
            watch(args)
        else:
            print(render_report(args.log), end='')
    except (OSError, ValueError) as error:
        parser.exit(1, f'performance monitor: {error}\n')


if __name__ == '__main__':
    main()
