#!/usr/bin/env python3
"""Install/update the skill, or roll back/uninstall an owned installation."""
import argparse
import json
import os
from pathlib import Path
import sys

if sys.version_info < (3, 10):
    raise SystemExit('Stack review requires Python 3.10 or newer.')

from stack_review.core import Error, read_json
from stack_review.installation import install as managed_install, rollback, uninstall


def install(prefix, host=None, skills_dir=None):
    hosts = ['hermes', 'claude'] if host == 'both' else [host] if host else []
    result = managed_install(prefix, hosts, skills_dir)
    print(json.dumps(result, indent=2))
    return Path(result['installed'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', type=Path, default=Path.home() / '.local/opt/stack-review')
    parser.add_argument('--host', choices=('hermes', 'claude', 'both'))
    parser.add_argument('--skills-dir', type=Path, help='Exact destination for one host skill')
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--uninstall', action='store_true')
    actions.add_argument('--rollback', action='store_true')
    args = parser.parse_args()
    try:
        if args.uninstall or args.rollback:
            if args.host or args.skills_dir:
                parser.error('Rollback/uninstall uses the recorded installation, not --host or --skills-dir')
            print(json.dumps(rollback(args.prefix) if args.rollback else uninstall(args.prefix), indent=2))
            raise SystemExit(0)
        if args.skills_dir and not args.host:
            parser.error('--skills-dir requires --host')
        existing = args.prefix.expanduser().resolve() / 'installation.json'
        if not args.host and existing.is_file():
            hosts = [s['host'] for s in read_json(existing)['skills']]
            args.host = 'both' if len(hosts) == 2 else hosts[0] if hosts else None
        if not args.host:
            detected = []
            if Path(os.environ.get('HERMES_HOME', str(Path.home() / '.hermes'))).is_dir():
                detected.append('hermes')
            if (Path.home() / '.claude').is_dir():
                detected.append('claude')
            if len(detected) == 1:
                args.host = detected[0]
                print(f'Found {args.host}; installing its skill.')
            else:
                try:
                    answer = input('Install for [1] Hermes, [2] Claude Code, or [3] both? ').strip().lower()
                except EOFError:
                    parser.error('Choose a host with --host hermes, --host claude or --host both')
                args.host = {'1': 'hermes', '2': 'claude', '3': 'both', 'hermes': 'hermes', 'claude': 'claude', 'both': 'both'}.get(answer)
                if not args.host:
                    parser.error('Choose 1, 2 or 3')
        install(args.prefix, args.host, args.skills_dir)
    except Error as exc:
        parser.exit(3, f'stack-review: {exc}\n')
