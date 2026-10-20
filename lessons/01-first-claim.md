# Lesson 1: Claim your first task

You and a classmate, Sam, share one repository. The course has a task, issue #7, "Fix the dosage table". You both want it. In this lesson you claim it, Sam tries a moment later, and you see why Symphony never lets two people work on one task by accident.

## Step 0: open a practice folder

From the top of a clone of this repository, in a terminal, run this once. It makes an empty practice folder, `$LAB`, and tells Python where the claim-protocol library is; every later block starts with `cd "$LAB"`, so nothing touches your real projects. (In the Colab notebook the first cell does this for you.)

```bash setup
export LAB="$(mktemp -d)" PYTHONPATH="$PWD"
echo "practice folder: $LAB"
```

## Step 1: make a practice repository

This makes a pretend GitHub, `origin.git`, with one commit on `main`, and two clones of it: yours (`you`) and Sam's (`sam`).

```bash run
cd "$LAB"
git init --quiet --bare --initial-branch=main origin.git
git init --quiet --initial-branch=main setup
cd setup
echo "# Course notes" > README.md
git add README.md
git -c user.name=teacher -c user.email=teacher@example.invalid commit --quiet -m "First commit"
git push --quiet "$LAB/origin.git" main
cd ..
for person in you sam; do
  git clone --quiet origin.git "$person"
  git -C "$person" config user.name "$person"
  git -C "$person" config user.email "$person@example.invalid"
done
ls
```

```output
origin.git
sam
setup
you
```

## Step 2: write your claim

A claim is a branch named `claude/` and the issue's number, whose first commit adds one small file, `docs/agents/claims/7.md`, saying who you are and what you plan. In a real project the claim skill writes it for you; here you write it by hand so you can see it.

```bash run
cd "$LAB"
cd you
git switch --quiet -c claude/7
mkdir -p docs/agents/claims
cat > docs/agents/claims/7.md <<'CLAIM'
# Claim: #7

- Worker: you
- Branch: claude/7

## Plan

Fix the units in the dosage table.

## Files to touch

- chapters/dosage.md
CLAIM
git add docs/agents/claims/7.md
git commit --quiet -m "Claim #7"
git log --oneline --format=%s
```

```output
Claim #7
First commit
```

## Step 3: Sam writes a claim too

Sam does exactly the same in Sam's own clone, at the same moment, naming Sam.

```bash run
cd "$LAB"
cd sam
git switch --quiet -c claude/7
mkdir -p docs/agents/claims
printf -- '- Worker: sam\n' > docs/agents/claims/7.md
git add docs/agents/claims/7.md
git commit --quiet -m "Claim #7"
echo "Sam's claim is ready to push"
```

```output
Sam's claim is ready to push
```

## Step 4: push, and see who gets it

The claim counts when it reaches origin. You push first.

```bash run
cd "$LAB"
git -C you push --quiet origin claude/7 && echo "accepted: #7 is yours"
```

```output
accepted: #7 is yours
```

Now Sam pushes the same branch name.

```bash run
cd "$LAB"
git -C sam push --quiet origin claude/7 || echo "refused: Sam's push did not go through"
```

```output
! [rejected]
claude/7 -> claude/7 (fetch first)
refused: Sam's push did not go through
```

GitHub, like the practice origin, refuses a push that would replace a branch with history it does not contain. Your branch is already there, so Sam's cannot replace it. Nobody overwrote anybody, and no person or server had to decide.

## Step 5: Sam finds out whose it is

Sam fetches and reads the claim file on origin.

```bash run
cd "$LAB"
git -C sam fetch --quiet origin
git -C sam show origin/claude/7:docs/agents/claims/7.md | grep Worker
```

```output
- Worker: you
```

So Sam takes another task from the board instead (lesson 3 shows where). In a real repository you would now open a draft pull request from `claude/7`, so everyone can watch the work, and finish by marking it ready ([PROTOCOL.md](../spec/PROTOCOL.md), Work in the open and Finish).

## What you learned

- A claim is the first push of `claude/<issue>`. The second push of the same name is refused, so two people never hold one task.
- The claim file says who holds it and what they plan; anyone can read it from origin.
- Next: [lesson 2](02-push-guard.md), what happens when someone tries to push anyway.
