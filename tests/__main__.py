"""Run every check:  python -m tests          (add 'quick' to skip the video renders)

Each test_*.py file's test_* functions are run in order; a failure is printed with
its traceback and the run carries on, so one broken thing doesn't hide the others.
"""

import importlib
import sys
import time
import traceback

from tests.helpers import use_scratch_data

use_scratch_data()          # before anything from anonbrain is imported

MODULES = ["test_logic", "test_render", "test_ui"]


def main(argv) -> int:
    quick = "quick" in argv
    only = [a for a in argv if a not in ("quick",)]
    failed, passed = [], 0
    for name in MODULES:
        if quick and name == "test_render":
            continue
        mod = importlib.import_module(f"tests.{name}")
        tests = [(n, f) for n, f in vars(mod).items() if n.startswith("test_") and callable(f)]
        print(f"\n{name} ({len(tests)})")
        for n, f in tests:
            if only and not any(o in n for o in only):
                continue
            t = time.time()
            try:
                f()
            except Exception:
                failed.append(f"{name}.{n}")
                print(f"  FAIL {n}")
                traceback.print_exc()
            else:
                passed += 1
                print(f"  ok   {n}  ({time.time() - t:.1f}s)")
        if hasattr(mod, "teardown"):
            mod.teardown()
    print(f"\n{passed} passed, {len(failed)} failed")
    for f in failed:
        print("  -", f)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
