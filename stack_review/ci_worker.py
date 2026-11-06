"""Detached bounded CI polling worker. Holds no agent conversation and starts no agent."""
import argparse
from pathlib import Path
import time

from . import ci
from .core import Error, Run, lock, read_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True, type=Path)
    parser.add_argument("--run", required=True)
    parser.add_argument("--token", required=True)
    args = parser.parse_args()
    run = Run(args.home, args.run)
    try:
        with lock(run.directory / "ci/worker"):
            while True:
                try:
                    with lock(run.directory):
                        run = Run(args.home, args.run)
                        if run.state.get("ci", {}).get("worker_token") != args.token or not run.state.get("pushed"):
                            return
                        if time.time() >= run.state["ci"]["deadline"]:
                            run.state["ci"].update(state="timed_out", next_check_at=None)
                            run.state["ci"].pop("worker_token", None)
                            run.save()
                            ci.report(run)
                            return
                        ci.check(run)
                        if run.state["ci"]["state"] not in ("pending", "unavailable"):
                            run.state["ci"].pop("worker_token", None)
                            run.save()
                            return
                        delay = min(ci.policy(run)["poll_interval"], max(0, run.state["ci"]["deadline"] - time.time()))
                except Error:
                    delay = 1  # A foreground command owns the run; retry without stealing its lock.
                end = time.monotonic() + delay
                while time.monotonic() < end:
                    state = read_json(run.directory / "run.json")
                    if state.get("ci", {}).get("worker_token") != args.token:
                        return
                    time.sleep(min(1, max(0, end - time.monotonic())))
    except Error as exc:
        print(str(exc), flush=True)


if __name__ == "__main__":
    main()
