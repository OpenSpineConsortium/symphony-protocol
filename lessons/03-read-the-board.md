# Lesson 3: Read the board

Every Symphony repository has a board: one page, STATE.md on the branch `board`, that says who holds what, what is free, and what must come first. A workflow rewrites it every time an issue, a branch or a pull request changes, so nobody edits it by hand and it is never stale. In this lesson you play a teaching assistant who keeps a course's repository, write down its state, and read the board the real code makes from it.

## Step 0: open a practice folder

From the top of a clone of this repository, in a terminal, run this once. It makes an empty practice folder, `$LAB`, and tells Python where the claim-protocol library is; every later block starts with `cd "$LAB"`, so nothing touches your real projects. (In the Colab notebook the first cell does this for you.)

```bash setup
export LAB="$(mktemp -d)" PYTHONPATH="$PWD"
echo "practice folder: $LAB"
```

## Step 1: describe the course's repository

The board workflow asks GitHub's API for the open issues, the claim branches, the claim files and the pull requests. Here you write the same facts by hand into `course.json`, the shape the board accepts for a dry run. The course has a claimed task, a task in the queue, and nothing else yet.

```bash run
cd "$LAB"
cat > course.json <<'JSON'
{
  "sha": "0123abcdef0123abcdef0123abcdef0123abcdef",
  "default_branch": "main",
  "issues": [
    {"number": 7, "title": "Fix the dosage table", "labels": [{"name": "claimed"}, {"name": "worker:you"}]},
    {"number": 8, "title": "Proofread chapter 2", "labels": [{"name": "todo"}]}
  ],
  "pulls": [],
  "branches": ["main", "claude/7"],
  "claims": {"7": "- Worker: you\n\n## Files to touch\n\n- chapters/dosage.md\n"},
  "merged": []
}
JSON
echo "written"
```

```output
written
```

## Step 2: render the board

This is the program the board workflow runs, told to read your file instead of GitHub.

```bash run
cd "$LAB"
python3 -m sdlc_protocol board --dry-run course.json > STATE.md
grep -A5 "^## Claims" STATE.md
grep -A5 "^## Queue" STATE.md
```

```output
## Claims
| #7 | claude/7 | you |
chapters/dosage.md
## Queue
| #8 | Proofread chapter 2 | todo |
```

Read it like a student looking for work: #7 is taken (you hold it, and the board shows the file you said you would touch), and #8 is free in the Queue. So Sam, from lessons 1 and 2, takes #8.

## Step 3: give a task to one person

The teacher wants Maya, not just anyone, to write the summary. A label `worker:maya` on the issue gives it to her: it leaves the Queue and appears under Given to workers until she claims it.

```bash run
cd "$LAB"
python3 - <<'PY'
import json
course = json.load(open("course.json"))
course["issues"].append({"number": 9, "title": "Write the chapter summary", "labels": [{"name": "todo"}, {"name": "worker:maya"}]})
json.dump(course, open("course.json", "w"))
PY
python3 -m sdlc_protocol board --dry-run course.json > STATE.md
grep -A5 "^## Given to workers" STATE.md
grep -c "Write the chapter summary" STATE.md
```

```output
## Given to workers
| #9 | Write the chapter summary | maya |
1
```

The summary appears once: under Given to workers, not in the Queue, so nobody else picks it up.

## Step 4: something breaks for everyone

The course's build stops working. An issue labelled `blocker` stops everyone: it is listed under Blockers, and a worker takes a blocker before anything in the Queue ([PROTOCOL.md](../spec/PROTOCOL.md), Blockers).

```bash run
cd "$LAB"
python3 - <<'PY'
import json
course = json.load(open("course.json"))
course["issues"].append({"number": 10, "title": "The PDF build is broken", "labels": [{"name": "blocker"}]})
json.dump(course, open("course.json", "w"))
PY
python3 -m sdlc_protocol board --dry-run course.json > STATE.md
grep -A5 "^## Blockers" STATE.md
```

```output
## Blockers
| #10 | The PDF build is broken | blocker |
```

## What you learned

- The board is made by code from what GitHub knows, so it is always current; you read it, you never edit it.
- Where to look for work, in order: Given to workers (yours first), then Blockers, then the Queue.
- In a real repository you read it with `/board` in Claude Code, or `git fetch origin +refs/heads/board:refs/remotes/origin/board && git show origin/board:STATE.md`.
- Next: [lesson 4](04-overlaps.md), when two people's work touches the same file.
