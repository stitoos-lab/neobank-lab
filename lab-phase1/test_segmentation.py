import subprocess
import sys

# (service source, cible, doit réussir ?)
TESTS = [
    ("web", "api", True),
    ("api", "db", True),
    ("web", "db", False),
]

def ping(source, target):
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", source, "ping", "-c", "1", target],
        capture_output=True,
    )
    return result.returncode == 0


failures = 0
for source, target, expected in TESTS:
    actual = ping(source, target)
    ok = actual == expected
    failures += not ok
    print(f"{'OK  ' if ok else 'FAIL'} {source} -> {target} (attendu : {'joignable' if expected else 'bloqué'})")

sys.exit(1 if failures else 0)