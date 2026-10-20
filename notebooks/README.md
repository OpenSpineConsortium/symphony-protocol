# Notebooks

Symphony's claim protocol, taught by running it. Each notebook opens in Google Colab with one click, needs no GitHub sign-in, no Claude account and no key of any kind, and runs in a throwaway folder where a local bare repository stands in for GitHub. Open one, then choose Runtime, Run all.

| Notebook | What you do | Open |
| --- | --- | --- |
| The demo | Two workers race for one issue, the push guard judges six pushes, and the board is drawn from a snapshot, in about a minute. | [Open in Colab](https://colab.research.google.com/github/OpenSpineConsortium/symphony-protocol/blob/main/notebooks/demo.ipynb) |
| Lesson 1: Claim your first task | You and a classmate want the same task; GitHub lets only one of you claim it. | [Open in Colab](https://colab.research.google.com/github/OpenSpineConsortium/symphony-protocol/blob/main/notebooks/01-first-claim.ipynb) |
| Lesson 2: The push guard | Ask the guard about six pushes, including the one git itself would let replace someone's claim. | [Open in Colab](https://colab.research.google.com/github/OpenSpineConsortium/symphony-protocol/blob/main/notebooks/02-push-guard.ipynb) |
| Lesson 3: Read the board | Draw the board from a snapshot and read its sections: what is held, what is free, what blocks everyone. | [Open in Colab](https://colab.research.google.com/github/OpenSpineConsortium/symphony-protocol/blob/main/notebooks/03-read-the-board.ipynb) |
| Lesson 4: When two tasks touch one file | See which of two overlapping pieces of work lands first, and why a blocker jumps the line. | [Open in Colab](https://colab.research.google.com/github/OpenSpineConsortium/symphony-protocol/blob/main/notebooks/04-overlaps.ipynb) |

The first cell of each fetches the newest release of this library (the demo, its own pinned release), so the notebooks describe released code, never an unreleased change on main.

## Where they come from

They are generated in OpenSpineConsortium/symphony-template from its lessons, whose commands its required check runs, by `python3 tools/living_docs.py publish <this folder>`, and copied here by a pull request; edit the lesson there, not the notebook here. Links into that repository, which is not public, are turned into this library's own pages or into plain text. [scripts/run_notebook.py](../scripts/run_notebook.py) runs every cell as Colab's Run all does, and [.github/workflows/notebooks.yml](../.github/workflows/notebooks.yml) runs it on each change here and weekly, so a new release that would break a notebook is found before a reader finds it.
