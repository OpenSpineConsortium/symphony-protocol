# Lesson 4: Two students, one file

Maya is fixing the dosage table (#21). Lee is adding units to it (#22). Both change `chapters/dosage.md`. Neither did anything wrong, but whoever lands second will have to bring the other's change in first. Symphony cannot stop the overlap, so it does the next best thing: the board lists every file two pieces of work share, and says in what order they should land.

## Step 0: open a practice folder

From the top of a clone of this repository, in a terminal, run this once. It makes an empty practice folder, `$LAB`, and tells Python where the claim-protocol library is; every later block starts with `cd "$LAB"`, so nothing touches your real projects. (In the Colab notebook the first cell does this for you.)

```bash setup
export LAB="$(mktemp -d)" PYTHONPATH="$PWD"
echo "practice folder: $LAB"
```

## Step 1: describe two pull requests that share a file

Maya opened her draft pull request first. Lee opened his an hour later, but has already marked it ready for review, which deleted his claim file, so the board names him by his `worker:lee` label. Besides the open issues, the board reads each claimed issue's labels (`claim_issues`), which is where it learns that a claim's issue is a blocker.

```bash run
cd "$LAB"
cat > course.json <<'JSON'
{
  "sha": "0123abcdef0123abcdef0123abcdef0123abcdef",
  "default_branch": "main",
  "issues": [
    {"number": 21, "title": "Fix the dosage table", "labels": [{"name": "claimed"}, {"name": "worker:maya"}]},
    {"number": 22, "title": "Add units to the dosage table", "labels": [{"name": "claimed"}, {"name": "worker:lee"}]}
  ],
  "pulls": [
    {"number": 50, "title": "Fix the dosage table", "head": {"ref": "claude/21", "sha": "aaaa"}, "draft": true,
     "created_at": "2026-10-20T09:00:00Z", "mergeable_state": "clean", "updated_at": "2026-10-20T09:00:00Z",
     "files": ["chapters/dosage.md"]},
    {"number": 51, "title": "Add units", "head": {"ref": "claude/22", "sha": "bbbb"}, "draft": false,
     "created_at": "2026-10-20T10:00:00Z", "mergeable_state": "clean", "updated_at": "2026-10-20T10:00:00Z",
     "files": ["chapters/dosage.md", "chapters/units.md"]}
  ],
  "branches": ["main", "claude/21", "claude/22"],
  "claims": {"21": "- Worker: maya\n", "22": null},
  "claim_issues": {
    "21": {"state": "open", "labels": ["claimed", "worker:maya"]},
    "22": {"state": "open", "labels": ["claimed", "worker:lee"]}
  },
  "merged": []
}
JSON
echo "written"
```

```output
written
```

## Step 2: read the Overlaps section

```bash run
cd "$LAB"
python3 -m sdlc_protocol board --dry-run course.json > STATE.md
grep -A5 "^## Overlaps" STATE.md
```

```output
## Overlaps
land the work in this order: a blocker first, then work marked ready, then the oldest
| chapters/dosage.md | #51, #50 |
```

Lee's #51 lands first, even though Maya started earlier, because it is marked ready: it waits only for its merge, while Maya's draft is still changing. `chapters/units.md` is not listed, because only Lee touches it.

## Step 3: what if Maya's work were a blocker?

Say the dosage error makes the PDF build fail for everyone, so the teacher labels #21 a blocker. A blocker lands first, whatever else is ready.

```bash run
cd "$LAB"
python3 - <<'PY'
import json
course = json.load(open("course.json"))
course["issues"][0]["labels"].append({"name": "blocker"})
course["claim_issues"]["21"]["labels"].append("blocker")
json.dump(course, open("course.json", "w"))
PY
python3 -m sdlc_protocol board --dry-run course.json > STATE.md
grep "chapters/dosage.md |" STATE.md
```

```output
| chapters/dosage.md | #50, #51 |
```

## What happens next in a real repository

The coordinator, a step of the board's own workflow, comments once on each piece of work with the shared file and the order, so Maya and Lee hear about it without anyone watching the board. When #51 merges, the board tells Maya's pull request that `main` moved, and she brings it in ([PROTOCOL.md](../spec/PROTOCOL.md), Overlaps and Work in the open).

## What you learned

- Overlaps are allowed; surprises are not. The board names every shared file and the landing order: a blocker first, then work marked ready, then the oldest.
- You have now used claims, the push guard, the board's sections and Overlaps: the parts of Symphony every worker meets, person or Claude. [The README](../README.md) shows what else the library holds, and [PROTOCOL.md](../spec/PROTOCOL.md) is the whole protocol in prose.
