"""scripts/run_notebook.py runs a notebook as Colab's kernel does: cells share
one namespace, a %%bash cell sees what an earlier cell put in os.environ, and
a bash cell that exits non-zero or a Python cell that raises fails the run
by its cell number. The real notebooks run in .github/workflows/notebooks.yml,
since they clone the library from GitHub."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import run_notebook  # noqa: E402


def notebook(*sources):
    path = Path(tempfile.mkdtemp()) / "n.ipynb"
    cells = [{"cell_type": "code", "source": s, "outputs": [], "metadata": {}} for s in sources]
    path.write_text(json.dumps({"cells": cells, "metadata": {}, "nbformat": 4, "nbformat_minor": 5}))
    return str(path)


class Running(unittest.TestCase):
    def setUp(self):
        self.start = os.getcwd()
        self.addCleanup(os.chdir, self.start)

    def test_bash_sees_the_environment_python_set_and_the_namespace_is_shared(self):
        path = notebook("import os\nos.environ['LAB_X'] = 'here'\nN = 2", "assert N == 2",
                        '%%bash\ntest "$LAB_X" = here')
        self.assertIsNone(run_notebook.run_notebook(path))
        self.assertNotIn("LAB_X", os.environ)

    def test_a_failing_bash_cell_is_named(self):
        problem = run_notebook.run_notebook(notebook("x = 1", "%%bash\necho oops\nexit 3"))
        self.assertIn("cell 2 exited 3", problem)
        self.assertIn("oops", problem)

    def test_only_the_last_command_decides_as_without_dash_e(self):
        self.assertIsNone(run_notebook.run_notebook(notebook("%%bash\nfalse\necho fine")))

    def test_a_raising_python_cell_is_named(self):
        problem = run_notebook.run_notebook(notebook("raise ValueError('bad')"))
        self.assertIn("cell 1 raised ValueError: bad", problem)


if __name__ == "__main__":
    unittest.main()
