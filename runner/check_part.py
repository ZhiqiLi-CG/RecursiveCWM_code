#!/usr/bin/env python3
"""Check v2 deliveries strictly; preserve explicit legacy read compatibility."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from delivery import validate, InvalidDelivery
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('part', type=Path)
p.add_argument('--strict', action='store_true', help='Require v2 (used for all new runs)')
a = p.parse_args()
try:
    data = json.loads(a.part.read_text())
    if a.strict or (isinstance(data, dict) and 'schema_version' in data):
        report = validate(a.part)
        print(f"ok schema_version=2 node={report['node_id']}")
    else:
        sys.exit(subprocess.call([sys.executable, str(Path(__file__).with_name('check_part_legacy.py')), str(a.part)]))
except (ValueError, OSError) as e:
    print(f'invalid_delivery: {e}'); sys.exit(1)
