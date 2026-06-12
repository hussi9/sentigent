#!/usr/bin/env python3
"""Test runner that captures pytest output to a file.

Run with: /Users/airbook/devpro/sentigent/.venv/bin/python /Users/airbook/devpro/sentigent/run_tests.py
"""
import subprocess
import sys
import os

os.chdir('/Users/airbook/devpro/sentigent')

result = subprocess.run(
    ['/Users/airbook/devpro/sentigent/.venv/bin/python', '-m', 'pytest', 'tests/', '-v', '--tb=short'],
    capture_output=True,
    text=True,
    cwd='/Users/airbook/devpro/sentigent',
    timeout=120
)

output_path = '/Users/airbook/devpro/sentigent/test_output.txt'
with open(output_path, 'w') as f:
    f.write('=== STDOUT ===\n')
    f.write(result.stdout if result.stdout else '(empty)\n')
    f.write('\n=== STDERR ===\n')
    f.write(result.stderr if result.stderr else '(empty)\n')
    f.write('\n=== RETURN CODE ===\n')
    f.write(str(result.returncode) + '\n')
