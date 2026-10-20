# Learn by doing

Four short lessons that teach Symphony's claim protocol by running it. Each one takes about ten minutes, needs no Claude account, no key and no GitHub sign-in, and works on your own machine or in Google Colab. They are written for students and new users who have never used git's branches or GitHub's pull requests in a team: every step says what to type, what you should see, and why it matters.

Every command on these pages is run by this repository's required check on every pull request (the test suite's tests/test_lessons.py, the same as `python3 scripts/lessons.py test`), and its output is compared with the output printed under it. A lesson that no longer matches the code fails the check, so what you read here is what the code on main does.

| Lesson | You learn | Features it uses | Colab |
| --- | --- | --- | --- |
| [1. Claim your first task](01-first-claim.md) | how two people can never take the same task | claim branches, claim files | [Open](https://colab.research.google.com/github/OpenSpineConsortium/symphony-protocol/blob/main/notebooks/01-first-claim.ipynb) |
| [2. When Symphony says no](02-push-guard.md) | which pushes are refused, and what to do instead | the push guard | [Open](https://colab.research.google.com/github/OpenSpineConsortium/symphony-protocol/blob/main/notebooks/02-push-guard.ipynb) |
| [3. Read the board](03-read-the-board.md) | where to find your next task, and what comes first | the board: Queue, Given to workers, Blockers | [Open](https://colab.research.google.com/github/OpenSpineConsortium/symphony-protocol/blob/main/notebooks/03-read-the-board.ipynb) |
| [4. Two students, one file](04-overlaps.md) | how work that touches the same file lands in order | Overlaps | [Open](https://colab.research.google.com/github/OpenSpineConsortium/symphony-protocol/blob/main/notebooks/04-overlaps.ipynb) |

## How to run a lesson

- **On your machine.** You need git and Python 3.12. From the top of a clone of this repository, copy each grey block into one terminal, in order. Step 0 of every lesson makes a practice folder, `$LAB`, and points Python at this checkout's package; every later block starts with `cd "$LAB"`, so nothing touches your real projects.
- **In Colab.** Each lesson is also a notebook under [notebooks/](../notebooks/), made from the lesson itself so the two never differ. Open one from the table above and choose Runtime, then Run all. Its first cell makes the practice folder and fetches the newest release of this library, so a notebook runs released code. A lesson is checked against main, so one that shows a change not yet released prints that change at a terminal but not in Colab until the next release; write a lesson for released behaviour, or land it with the release that carries the change.

## The rules of the practice folder

Every block starts with `cd "$LAB"`, so a block never depends on where the one before it left you; that is also how the notebooks' cells run, each in a shell of its own. A local "bare" repository in that folder stands in for GitHub: it refuses the same pushes GitHub refuses, for the same reason, so what you see is the real mechanism, not a simulation.

## How they stay true

All of it is enforced by the required check, `bash scripts/check.sh`, so a pull request that breaks a lesson cannot merge:

- **The lessons run.** tests/test_lessons.py, like `python3 scripts/lessons.py test`, runs every block marked `bash run` in a fresh practice folder and fails when an output block is no longer printed. Write a lesson with that in mind: quote the lines that matter, never a hash or a date.
- **The notebooks follow the lessons.** `python3 scripts/lessons.py notebooks` writes notebooks/ from the lessons, and `check` fails while one is out of date, so edit the lesson and regenerate, never the notebook.
- **The notebooks run as Colab runs them.** [scripts/run_notebook.py](../scripts/run_notebook.py) runs every code cell in order, as Colab's Run all does, and [.github/workflows/notebooks.yml](../.github/workflows/notebooks.yml) runs it on each change to a notebook, by hand and weekly, so a new release that would break one is found before a reader finds it.
