# Lesson 2: When Symphony says no

In lesson 1 GitHub refused Sam's push. But git has ways to force a push through, and a hurried person, or a hurried Claude session, might try one. In a Symphony repository Claude Code runs a small program, the push guard, before every command a session types, and stops the pushes that would break the rules. In this lesson you ask the guard about six pushes and read its answers.

## Step 0: open a practice folder

From the top of a clone of this repository, in a terminal, run this once. It makes an empty practice folder, `$LAB`, and tells Python where the claim-protocol library is; every later block starts with `cd "$LAB"`, so nothing touches your real projects. (In the Colab notebook the first cell does this for you.)

```bash setup
export LAB="$(mktemp -d)" PYTHONPATH="$PWD"
echo "practice folder: $LAB"
```

## Step 1: set up the same situation as lesson 1

You hold `claude/7`; Sam has a claim of the same name that origin refused. This block repeats lesson 1 in one go.

```bash run
cd "$LAB"
git init --quiet --bare --initial-branch=main origin.git
git init --quiet --initial-branch=main setup
echo "# Course notes" > setup/README.md
git -C setup add README.md
git -C setup -c user.name=teacher -c user.email=t@example.invalid commit --quiet -m "First commit"
git -C setup push --quiet "$LAB/origin.git" main
for person in you sam; do
  git clone --quiet origin.git "$person"
  git -C "$person" config user.name "$person"
  git -C "$person" config user.email "$person@example.invalid"
  git -C "$person" switch --quiet -c claude/7
  mkdir -p "$person/docs/agents/claims"
  printf -- '- Worker: %s\n' "$person" > "$person/docs/agents/claims/7.md"
  git -C "$person" add docs
  git -C "$person" commit --quiet -m "Claim #7"
done
git -C you push --quiet origin claude/7
git -C sam fetch --quiet origin
echo "you hold claude/7; Sam has fetched"
```

```output
you hold claude/7; Sam has fetched
```

## Step 2: a helper that asks the guard

Claude Code hands the guard each command as a small piece of JSON and stops the command when the guard exits with code 2. This helper does the same, from Sam's clone, and prints the answer. It is saved in `guard.sh` so later blocks can use it.

```bash run
cd "$LAB"
cat > guard.sh <<'HELPER'
ask_guard() {
  printf '{"cwd": "%s", "tool_input": {"command": "%s"}}' "$LAB/sam" "$1" \
    | python3 -m sdlc_protocol guard 2> answer.txt
  if [ $? -eq 2 ]; then echo "REFUSED: $1"; sed 's/^/  why: /' answer.txt
  else echo "allowed: $1"; fi
}
HELPER
echo "saved"
```

```output
saved
```

## Step 3: the pushes the rules forbid

Nobody pushes straight to `main`: work reaches it only through a pull request that passes the check.

```bash run
cd "$LAB"
source guard.sh
ask_guard "git push origin main"
```

```output
REFUSED: git push origin main
why: a push to main is refused: the default branch takes only pull requests
```

`--force` would replace your claim with Sam's, which is exactly what lesson 1's refusal protected.

```bash run
cd "$LAB"
source guard.sh
ask_guard "git push --force origin claude/7"
ask_guard "git push origin +claude/7"
```

```output
REFUSED: git push --force origin claude/7
why: --force overwrites history another account may hold
REFUSED: git push origin +claude/7
why: a + before a refspec forces that ref as --force does
```

A branch name that looks like a claim but is not one, such as `claude/07`, would confuse the board, so it is refused too, and the guard names the right branch.

```bash run
cd "$LAB"
source guard.sh
ask_guard "git push origin claude/07"
```

```output
REFUSED: git push origin claude/07
so the claim branch of #7 is claude/7
```

## Step 4: the clever one

`--force-with-lease` is git's "safe" force: it only overwrites if the branch is still where you last saw it. Written `--force-with-lease=claude/7:origin/claude/7`, it says "replace claude/7 if it is still at the commit I fetched". Sam just fetched, so Sam's copy matches origin, and git itself would let this push replace your claim. The guard reads both claim files first.

```bash run
cd "$LAB"
source guard.sh
ask_guard "git push --force-with-lease=claude/7:origin/claude/7 origin claude/7"
```

```output
REFUSED: git push --force-with-lease=claude/7:origin/claude/7 origin claude/7
claude/7 on origin is you's claim
```

(The guard says "you's" because your worker name in this lesson is literally `you`.)

## Step 5: what Sam should do

Sam picks a free task, say #8, and claims it the normal way. The guard allows that.

```bash run
cd "$LAB"
source guard.sh
ask_guard "git push origin claude/8"
```

```output
allowed: git push origin claude/8
```

## What you learned

- The guard refuses a push to `main`, every kind of force onto someone else's work, and branch names that only look like claims, each with the rule it breaks.
- A refusal is the rules working. The answer is always another task, a pull request or a rebase of your own branch, never a way around the guard ([PROTOCOL.md](../spec/PROTOCOL.md), Rules that hold everywhere).
- Next: [lesson 3](03-read-the-board.md), where to find that other task.
