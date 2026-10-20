"""Run a notebook's code cells the way Colab's kernel does, with nothing to
install: the cells share one Python namespace in order, and a cell that opens
with %%bash runs its body in bash with the kernel's environment, so what an
earlier cell put in os.environ (the practice folder, PYTHONPATH) reaches it.
A cell that raises, or a bash cell whose script exits non-zero (Colab raises
CalledProcessError there; like Colab, bash runs without -e), fails the run and
names the cell. This is how the notebooks under notebooks/ are tested end to end,
against the public library they clone, before a reader opens one in Colab.

    python3 scripts/run_notebook.py notebooks/*.ipynb
"""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def code_cells(path):
    notebook = json.loads(Path(path).read_text(encoding="utf-8"))
    return ["".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code"]


def run_bash(body):
    done = subprocess.run(["bash", "-c", body], capture_output=True, text=True,
                          env=dict(os.environ), timeout=300)
    return done.returncode, done.stdout + done.stderr


def run_python(source, namespace):
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        exec(compile(source, "<cell>", "exec"), namespace)
    return printed.getvalue()


def run_notebook(path):
    """Return None when every cell ran, else a line saying which cell failed and why."""
    saved = dict(os.environ)
    namespace = {"__name__": "__main__"}
    try:
        with tempfile.TemporaryDirectory() as home:
            os.chdir(home)
            for number, source in enumerate(code_cells(path), 1):
                if source.startswith("%%bash"):
                    code, printed = run_bash(source.split("\n", 1)[1] if "\n" in source else "")
                    if code:
                        return f"{path}: cell {number} exited {code}:\n{printed}"
                    continue
                try:
                    run_python(source, namespace)
                except BaseException as error:  # a cell's SystemExit fails it too
                    return f"{path}: cell {number} raised {type(error).__name__}: {error}"
    finally:
        os.environ.clear()
        os.environ.update(saved)
    return None


def main(paths):
    start = os.getcwd()
    failures = []
    for path in paths:
        problem = run_notebook(str(Path(start, path)))
        os.chdir(start)
        print(f"{'FAIL' if problem else 'ok  '} {path}")
        if problem:
            failures.append(problem)
    for problem in failures:
        print(problem, file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
