"""The lessons under lessons/, which teach the protocol by running it: the
check runs every command they show, and the Colab notebooks under
notebooks/ are made from them.

A lesson is a Markdown file whose fenced blocks marked "bash run" are
commands and whose blocks marked "output" say what the block before them
prints. `test` runs every lesson in a practice folder of its own against
this checkout's package and fails when an output no longer appears, so a
lesson cannot drift from the code it teaches. The comparison is by lines,
in order, each expected line found within an actual one, so a lesson quotes
the part that matters and not a hash or a date.

Each block runs in a bash of its own and opens with `cd "$LAB"`, the
practice folder, written on the page so a reader pasting it gets the same,
because that is how a notebook's %%bash cells run; the notebook made from a
lesson (`notebooks`) is then the same commands, cell for cell, and `check`
fails when a notebook is out of date with its lesson. A lesson's one block
marked "bash setup" makes $LAB for a reader at a terminal; the check makes
its own, and a notebook's first cell takes its place, cloning the newest
release, so a notebook describes released code and never an unreleased
change on main.

    python3 scripts/lessons.py test
    python3 scripts/lessons.py check
    python3 scripts/lessons.py notebooks
"""

import argparse
import json
import os
import posixpath
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LESSONS = ROOT / "lessons"
NOTEBOOKS = ROOT / "notebooks"
LIBRARY_URL = "https://github.com/OpenSpineConsortium/symphony-protocol"
COLAB = "https://colab.research.google.com/github/OpenSpineConsortium/symphony-protocol/blob/main/notebooks/"
FENCE = re.compile(r"^```(.*)$")
LESSON_NAME = re.compile(r"^0\d-[a-z0-9-]+$")
BLOCK_SECONDS = 60

# git reads none of the reader's settings and leaves no background job
# behind in a practice folder that is about to be deleted
GIT_ENV = {
    "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_DATE": "2026-10-20T09:00:00Z", "GIT_COMMITTER_DATE": "2026-10-20T09:00:00Z",
    "GIT_CONFIG_COUNT": "4",
    "GIT_CONFIG_KEY_0": "gc.auto", "GIT_CONFIG_VALUE_0": "0",
    "GIT_CONFIG_KEY_1": "gc.autoDetach", "GIT_CONFIG_VALUE_1": "false",
    "GIT_CONFIG_KEY_2": "maintenance.auto", "GIT_CONFIG_VALUE_2": "false",
    "GIT_CONFIG_KEY_3": "maintenance.autoDetach", "GIT_CONFIG_VALUE_3": "false",
}


# Reading a lesson

def parse(text):
    """The lesson as segments in order, each (kind, body, info): kind is
    "md", "setup", "run", "output", or "code" for any other fenced block."""
    segments, prose, lines = [], [], text.splitlines()
    i = 0
    while i < len(lines):
        opened = FENCE.match(lines[i])
        if not opened:
            prose.append(lines[i])
            i += 1
            continue
        info, body, i = opened.group(1).strip(), [], i + 1
        while i < len(lines) and not lines[i].startswith("```"):
            body.append(lines[i])
            i += 1
        i += 1
        if "".join(prose).strip():
            segments.append(("md", "\n".join(prose), ""))
        prose = []
        segments.append((kind_of(info), "\n".join(body), info))
    if "".join(prose).strip():
        segments.append(("md", "\n".join(prose), ""))
    return segments


def kind_of(info):
    return {"bash run": "run", "bash setup": "setup", "output": "output"}.get(info, "code")


def lessons():
    return sorted(LESSONS.glob("[0-9]*.md"))


def steps(path):
    """Each command of a lesson with the output it promises, or None."""
    segments = parse(path.read_text(encoding="utf-8"))
    found = []
    for k, (kind, body, _) in enumerate(segments):
        if kind != "run":
            continue
        after = segments[k + 1] if k + 1 < len(segments) else None
        found.append((body, after[1] if after and after[0] == "output" else None))
    return found


def shown(path):
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


# Running a lesson

def run_block(code, lab, library):
    # a caller's GIT_DIR or GIT_INDEX_FILE, as a hook has, would point the
    # lesson's git at the real repository
    inherited = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env = dict(inherited, **GIT_ENV, LAB=str(lab), PYTHONPATH=str(library))
    try:
        done = subprocess.run(["bash", "-c", code], env=env, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=BLOCK_SECONDS)
    except subprocess.TimeoutExpired as stopped:
        return f"{stopped.output or ''}\n(stopped after {BLOCK_SECONDS} seconds)"
    return done.stdout


def missing_lines(expected, actual):
    """The first expected line not found, in order, within the actual lines;
    a line may match the same actual line as the one before it."""
    got = [line.strip() for line in actual.splitlines()]
    at = 0
    for want in (line.strip() for line in expected.splitlines()):
        if not want:
            continue
        while at < len(got) and want not in got[at]:
            at += 1
        if at == len(got):
            return want
    return None


def test_lesson(path, library):
    problems = []
    with tempfile.TemporaryDirectory(prefix="symphony-lesson-") as lab:
        for n, (code, expected) in enumerate(steps(path), 1):
            actual = run_block(code, Path(lab), library)
            if expected is None:
                continue
            lost = missing_lines(expected, actual)
            if lost:
                printed = "\n    ".join(actual.splitlines()[-12:])
                problems.append(f"{shown(path)}: block {n} never printed {lost!r}; it printed:\n    {printed}")
    return problems


def test(_args):
    problems, count = [], 0
    for path in lessons():
        problems += test_lesson(path, ROOT)
        count += len(steps(path))
    for line in problems:
        print(line)
    if problems:
        return 1
    print(f"lessons ok ({len(lessons())} lessons, {count} blocks)")
    return 0


# Notebooks made from the lessons

def setup_cell():
    return f'''# The practice folder, and the newest release of the public claim-protocol library.
import os, re, subprocess, tempfile
tags = subprocess.run(["git", "ls-remote", "--tags", "{LIBRARY_URL}"], capture_output=True, text=True, check=True).stdout
releases = sorted({{tuple(map(int, m)) for m in re.findall(r"refs/tags/v(\\d+)\\.(\\d+)\\.(\\d+)$", tags, re.M)}})
TAG = "v%d.%d.%d" % releases[-1]
LAB = tempfile.mkdtemp(prefix="symphony-lesson-")
LIBRARY = os.path.join(tempfile.mkdtemp(), "symphony-protocol")
subprocess.run(["git", "-c", "advice.detachedHead=false", "clone", "--quiet", "--depth", "1",
                "--branch", TAG, "{LIBRARY_URL}", LIBRARY], check=True)
os.environ.update({json.dumps(GIT_ENV)})
os.environ.update(LAB=LAB, PYTHONPATH=LIBRARY)
print("symphony-protocol", TAG, "; practice folder:", LAB)'''


def cell(kind, text):
    made = {"cell_type": kind, "metadata": {}, "source": text.splitlines(True)}
    if kind == "code":
        made.update(execution_count=None, outputs=[])
    return made


def notebook_of(path):
    cells = []
    for kind, body, info in parse(path.read_text(encoding="utf-8")):
        if kind == "md" and body.strip():
            cells.append(cell("markdown", links_for_colab(for_a_notebook(body.strip("\n")))))
        elif kind == "setup":
            cells.append(cell("code", setup_cell()))
        elif kind == "run":
            cells.append(cell("code", f"%%bash\n{body}"))
        elif kind == "output":
            cells.append(cell("markdown", "You should see lines like these:\n\n```\n" + body + "\n```"))
        else:
            cells.append(cell("markdown", f"```{info}\n{body}\n```"))
    for n, made in enumerate(cells):
        made["id"] = f"cell-{n}"
    return {"cells": cells, "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                                         "language_info": {"name": "python"}},
            "nbformat": 4, "nbformat_minor": 5}


def for_a_notebook(text):
    """Step 0 tells a reader with a clone what the setup block does; in a
    notebook the setup cell clones the library itself, so it says that."""
    text = text.replace("From the top of a clone of this repository, in a terminal, run this once.", "Run this cell first.")
    text = text.replace("tells Python where the claim-protocol library is", "fetches the claim-protocol library")
    return text.replace(" (In the Colab notebook the first cell does this for you.)", "")


def links_for_colab(text):
    """Colab shows a notebook away from this repository, where a relative
    link leads nowhere: a neighbouring lesson becomes its own notebook in
    Colab, any other file its page on GitHub."""
    def moved(match):
        label, target = match.groups()
        if re.match(r"^([a-z]+:|#)", target):
            return match.group(0)
        stem = target[:-3] if target.endswith(".md") else ""
        if LESSON_NAME.match(stem):
            return f"[{label}]({COLAB}{stem}.ipynb)"
        page, _, anchor = target.partition("#")
        resolved = posixpath.normpath(posixpath.join("lessons", page))
        return f"[{label}]({LIBRARY_URL}/blob/main/{resolved}{'#' + anchor if anchor else ''})"
    return re.sub(r"(?<!!)\[([^\]]+)\]\(([^)\s]+)\)", moved, text)


def notebook_text(path):
    return json.dumps(notebook_of(path), indent=1, ensure_ascii=True) + "\n"


def notebooks(args):
    stale = []
    NOTEBOOKS.mkdir(exist_ok=True)
    for path in lessons():
        target = NOTEBOOKS / (path.stem + ".ipynb")
        text = notebook_text(path)
        if target.exists() and target.read_text(encoding="utf-8") == text:
            continue
        if args.check:
            stale.append(target)
        else:
            target.write_text(text, encoding="utf-8")
            print(f"wrote {shown(target)}")
    for target in stale:
        print(f"{shown(target)}: out of date with its lesson; run python3 scripts/lessons.py notebooks")
    names = {p.stem for p in lessons()}
    # the demo is written by hand; only a lesson's notebook needs its lesson
    orphans = [p for p in NOTEBOOKS.glob("[0-9]*.ipynb") if p.stem not in names]
    for target in orphans:
        print(f"{shown(target)}: no lesson of that name; delete it with its lesson")
    return 1 if stale or orphans else 0


# Holding the lessons to their shape

def lesson_shape(path):
    """A lesson has one setup block, before its first command, and every
    command opens in the practice folder, as a notebook cell does."""
    segments = parse(path.read_text(encoding="utf-8"))
    kinds = [kind for kind, _, _ in segments]
    problems = []
    if kinds.count("setup") != 1 or ("run" in kinds and kinds.index("setup") > kinds.index("run")):
        problems.append(f"{shown(path)}: one block marked bash setup, before the first bash run block")
    for n, (kind, body, _) in enumerate(s for s in segments if s[0] == "run"):
        if not body.startswith('cd "$LAB"\n'):
            problems.append(f'{shown(path)}: block {n + 1} does not open with cd "$LAB"')
    return problems


def check(_args):
    problems = []
    index = (LESSONS / "README.md").read_text(encoding="utf-8")
    for path in lessons():
        if not LESSON_NAME.match(path.stem):
            problems.append(f"{shown(path)}: a lesson is named 0N-words.md")
        if f"({path.name})" not in index:
            problems.append(f"lessons/README.md: lesson {path.name} is not in the table")
        if not steps(path):
            problems.append(f"{shown(path)}: no block marked bash run, so the check tests nothing")
        problems += lesson_shape(path)
    for line in problems:
        print(line)
    if problems:
        return 1
    stale = notebooks(argparse.Namespace(check=True))
    if not stale:
        print(f"lessons ok ({len(lessons())} lessons, notebooks up to date)")
    return stale


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("test", help="run every lesson's commands and compare their outputs")
    sub.add_parser("check", help="every lesson listed and well formed, the notebooks up to date")
    made = sub.add_parser("notebooks", help="write each lesson's notebook under notebooks/")
    made.add_argument("--check", action="store_true", help="fail, writing nothing, when one is out of date")
    args = parser.parse_args(argv)
    return {"test": test, "check": check, "notebooks": notebooks}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
