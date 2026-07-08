#!/usr/bin/env python3
"""Test runner that captures pytest output to a file.

Run with: python3 run_tests.py (from repo root)
"""
import subprocess
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent
venv_python = repo_root / '.venv' / 'bin' / 'python'

result = subprocess.run(
    [str(venv_python), '-m', 'pytest', 'tests/', '-v', '--tb=short'],
    capture_output=True,
    text=True,
    cwd=str(repo_root),
    timeout=120
)

output_path = repo_root / 'test_output.txt'
with open(str(output_path), 'w') as f:
    f.write('=== STDOUT ===\n')
    f.write(result.stdout if result.stdout else '(empty)\n')
    f.write('\n=== STDERR ===\n')
    f.write(result.stderr if result.stderr else '(empty)\n')
    f.write('\n=== RETURN CODE ===\n')
    f.write(str(result.returncode) + '\n')
