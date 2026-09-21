"""Bounded Actions worker; the workflow starts a successor after five hours."""
import argparse
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args, timeout=60):
    return subprocess.run(args, cwd=ROOT, check=True, timeout=timeout)


def next_tick(started, finished, interval):
    """Skip missed slots after a slow fetch; never overlap fetches."""
    return started + (int((finished - started) // interval) + 1) * interval


def cycle(branch):
    # Restore only generated files in this disposable Actions checkout.
    run('git', 'restore', '--staged', '--worktree', '--', 'data')
    run('git', 'pull', '--ff-only', 'origin', branch)
    run(sys.executable, 'scripts/fetch_data.py', timeout=240)
    run('git', 'add', '--', 'data')
    changed = subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=ROOT).returncode
    if changed == 0:
        return
    if changed != 1:
        raise RuntimeError('Could not inspect generated data')
    stamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    run('git', 'commit', '-m', 'data: refresh ' + stamp)
    # Never force-push or resolve a rejected push with an older snapshot.
    run('git', 'push', 'origin', 'HEAD:' + branch)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--duration-seconds', type=int, default=18000)
    parser.add_argument('--interval-seconds', type=int, default=300)
    args = parser.parse_args()
    if args.duration_seconds < 1 or args.interval_seconds < 60:
        parser.error('duration must be positive and interval at least 60 seconds')
    branch = os.environ['DEFAULT_BRANCH']
    run('git', 'config', 'user.name', 'github-actions[bot]')
    run('git', 'config', 'user.email', 'github-actions[bot]@users.noreply.github.com')
    started = time.monotonic()
    deadline = started + args.duration_seconds
    while time.monotonic() < deadline:
        try:
            cycle(branch)
        except (subprocess.SubprocessError, RuntimeError) as exc:
            # A successor uses a clean checkout and reruns checks. Do not
            # continue from a rejected commit or a partly generated snapshot.
            print('::warning::Refresh interrupted: ' + type(exc).__name__, flush=True)
            return
        tick = next_tick(started, time.monotonic(), args.interval_seconds)
        time.sleep(max(0, min(tick, deadline) - time.monotonic()))


if __name__ == '__main__':
    main()
