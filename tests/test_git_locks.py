"""The lock table's git side, against git itself: a bare repository in a
temporary directory with a clone per worker. The table starts with the
first lock; two claims on different functions of one file both hold
theirs, and a claim on what another holds or reads is refused; a claim
and its locks are pushed all or none; a push built on a tip that moved
meanwhile is refused and decided again on the new tip; a lock lives while
its claim's branch is on the remote and not yet in main, through a rebase
of the claim; verify holds a change to the locks as the switch says; and
overlap tells a change behind main whether what main did meets it."""

import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sdlc_protocol import claims, cli, locks  # noqa: E402
from sdlc_protocol.adapters import git_locks  # noqa: E402
from sdlc_protocol.locks import READ, WRITE, Entry  # noqa: E402

BASE = "def f(x):\n    return x + 1\n\n\ndef g(y):\n    return f(y) * 2\n\n\ndef h():\n    return 0\n"

# Automatic maintenance runs detached in git 2.55 and races a test's
# cleanup, so every scratch repository has it off, in the environment and
# in its own configuration (symphony-template#63).
QUIET = {"gc.auto": "0", "gc.autoDetach": "false", "maintenance.auto": "false",
         "maintenance.autoDetach": "false", "receive.autogc": "false"}
ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C", "GIT_CONFIG_COUNT": str(len(QUIET)),
       **{f"GIT_CONFIG_KEY_{i}": key for i, key in enumerate(QUIET)},
       **{f"GIT_CONFIG_VALUE_{i}": value for i, value in enumerate(QUIET.values())}}


def git(cwd, *args, check=True):
    done = subprocess.run(["git", "-c", "user.name=worker", "-c", "user.email=worker@test.local",
                           "-c", "commit.gpgsign=false", *args], cwd=cwd, capture_output=True, text=True,
                          timeout=60, env=ENV)
    if check and done.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {done.stderr}")
    return done.stdout.strip()


def quiet(repo):
    for key, value in QUIET.items():
        git(repo, "config", key, value)


class Remote(unittest.TestCase):
    """A bare remote seeded with m.py on main, and the clones a and b."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="sdlc-git-locks-test-")
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.bare = str(root / "remote.git")
        git(root, "init", "--quiet", "--bare", "--initial-branch=main", self.bare)
        quiet(self.bare)
        seed = root / "seed"
        git(root, "init", "--quiet", "--initial-branch=main", str(seed))
        quiet(seed)
        (seed / "m.py").write_text(BASE, encoding="utf-8")
        git(seed, "add", "m.py")
        git(seed, "commit", "--quiet", "-m", "base")
        git(seed, "remote", "add", "origin", self.bare)
        git(seed, "push", "--quiet", "origin", "main")
        self.seed = str(seed)
        self.a = self.clone(root / "a")
        self.b = self.clone(root / "b")

    def clone(self, path):
        git(path.parent, "clone", "--quiet", self.bare, str(path))
        quiet(path)
        return str(path)

    def claim(self, repo, number, edit=None):
        """A claim branch made from main with one commit, not pushed."""
        git(repo, "fetch", "--quiet", "origin")
        git(repo, "checkout", "--quiet", "-B", f"claude/{number}", "origin/main")
        target = Path(repo) / claims.claim_path(number)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"claim {number} in {repo}\n", encoding="utf-8")
        git(repo, "add", "docs")
        git(repo, "commit", "--quiet", "-m", f"claim #{number}")
        if edit:
            Path(repo, "m.py").write_text(edit, encoding="utf-8")
            git(repo, "commit", "--quiet", "-am", f"work on #{number}")

    def remote_ref(self, ref):
        return git(self.bare, "rev-parse", "--verify", "--quiet", ref, check=False)

    def table(self):
        return locks.read_table(git(self.bare, "show", f"{locks.LOCKS_BRANCH}:{locks.TABLE_FILE}"))


class Acquiring(Remote):
    def test_the_first_lock_starts_the_branch_and_claim_and_lock_go_together(self):
        self.claim(self.a, 1)
        git_locks.acquire(self.a, "origin", [Entry("m.py#f", 1, WRITE, "wa")], claim_branch="claude/1")
        self.assertTrue(self.remote_ref("refs/heads/claude/1"))
        self.assertEqual(self.table(), [Entry("m.py#f", 1, WRITE, "wa")])
        log = git(self.bare, "log", "--format=%s", locks.LOCKS_BRANCH)
        self.assertEqual(log, "Locks: #1")

    def test_two_claims_on_different_functions_both_hold_theirs(self):
        self.claim(self.a, 1)
        self.claim(self.b, 2)
        git_locks.acquire(self.a, "origin", [Entry("m.py#f", 1)], claim_branch="claude/1")
        git_locks.acquire(self.b, "origin", [Entry("m.py#h", 2)], claim_branch="claude/2")
        self.assertEqual(self.table(), [Entry("m.py#f", 1), Entry("m.py#h", 2)])

    def test_a_claim_on_what_another_reads_is_refused_with_its_branch(self):
        self.claim(self.a, 1)
        self.claim(self.b, 2)
        git_locks.acquire(self.a, "origin", [Entry("m.py#g", 1), Entry("m.py#f", 1, READ)],
                          claim_branch="claude/1")
        with self.assertRaises(locks.Held):
            git_locks.acquire(self.b, "origin", [Entry("m.py#f", 2)], claim_branch="claude/2")
        self.assertFalse(self.remote_ref("refs/heads/claude/2"))
        self.assertEqual(len(self.table()), 2)

    def test_a_claim_already_held_is_refused_and_takes_no_lock(self):
        self.claim(self.a, 1)
        git_locks.acquire(self.a, "origin", [Entry("m.py#f", 1)], claim_branch="claude/1")
        self.claim(self.b, 1)
        with self.assertRaises(git_locks.ClaimTaken):
            git_locks.acquire(self.b, "origin", [Entry("m.py#h", 1, WRITE, "wb")], claim_branch="claude/1")
        self.assertEqual(self.table(), [Entry("m.py#f", 1)])

    def test_a_table_that_moved_meanwhile_is_decided_again_on_its_new_tip(self):
        self.claim(self.a, 1)
        self.claim(self.b, 2)
        seen = []

        def decide(entries, live):
            if not seen:
                git_locks.acquire(self.a, "origin", [Entry("m.py#f", 1)], claim_branch="claude/1")
            seen.append(list(entries))
            return locks.acquire(entries, [Entry("m.py#f", 2)], live)

        with self.assertRaises(locks.Held):
            git_locks.change(self.b, "origin", decide, claim_branch="claude/2")
        self.assertEqual(seen[0], [])
        self.assertEqual(seen[1], [Entry("m.py#f", 1)])
        self.assertFalse(self.remote_ref("refs/heads/claude/2"))

    def test_a_push_on_a_stale_tip_is_refused_by_git(self):
        self.claim(self.a, 1)
        git_locks.acquire(self.a, "origin", [Entry("m.py#f", 1)], claim_branch="claude/1")
        tip, entries = git_locks.fetch_table(self.b, "origin")
        git_locks.release(self.a, "origin", 1)
        stale = git_locks.commit_table(self.b, tip, entries + [Entry("m.py#h", 2)], "stale\n")
        outcome = git_locks.push(self.b, "origin", [f"{stale}:refs/heads/{locks.LOCKS_BRANCH}"])
        self.assertTrue(outcome[f"refs/heads/{locks.LOCKS_BRANCH}"])
        self.assertEqual(self.table(), [])


class Living(Remote):
    def test_a_lock_ends_when_its_claim_lands_in_main(self):
        self.claim(self.a, 1)
        git_locks.acquire(self.a, "origin", [Entry("m.py#f", 1)], claim_branch="claude/1")
        git(self.a, "push", "--quiet", "origin", "claude/1:main")
        self.assertEqual(git_locks.sweep(self.b, "origin"), [])
        self.assertEqual(self.table(), [])

    def test_a_lock_lives_through_a_rebase_of_its_claim(self):
        self.claim(self.a, 1)
        git_locks.acquire(self.a, "origin", [Entry("m.py#f", 1)], claim_branch="claude/1")
        Path(self.seed, "other.txt").write_text("moved\n", encoding="utf-8")
        git(self.seed, "add", "other.txt")
        git(self.seed, "commit", "--quiet", "-m", "main moves")
        git(self.seed, "push", "--quiet", "origin", "main")
        git(self.a, "fetch", "--quiet", "origin")
        git(self.a, "rebase", "--quiet", "origin/main")
        tip = git(self.bare, "rev-parse", "claude/1")
        git(self.a, "push", "--quiet", f"--force-with-lease=claude/1:{tip}", "origin", "claude/1")
        self.assertEqual(git_locks.sweep(self.b, "origin"), [Entry("m.py#f", 1)])

    def test_the_caller_may_end_a_claim_git_cannot_see_has_ended(self):
        self.claim(self.a, 1)
        git_locks.acquire(self.a, "origin", [Entry("m.py#f", 1)], claim_branch="claude/1")
        self.assertEqual(git_locks.sweep(self.b, "origin", ended=[1]), [])

    def test_a_dead_lock_is_taken_over_in_the_same_commit(self):
        self.claim(self.a, 1)
        git_locks.acquire(self.a, "origin", [Entry("m.py#f", 1)], claim_branch="claude/1")
        git(self.a, "push", "--quiet", "origin", "claude/1:main")
        self.claim(self.b, 2)
        after = git_locks.acquire(self.b, "origin", [Entry("m.py#f", 2)], claim_branch="claude/2")
        self.assertEqual(after, [Entry("m.py#f", 2)])


class Verifying(Remote):
    def run_cli(self, *args, mode="enforce"):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(["locks", "--repo", self.a, *args]) if mode is None else \
                cli.run_locks(["--repo", self.a, *args], environ={"SYMPHONY_LOCKS": mode})
        return code, out.getvalue() + err.getvalue()

    def test_a_change_inside_its_grant_passes_and_one_outside_fails_when_enforced(self):
        self.claim(self.a, 1, edit=BASE.replace("x + 1", "x + 2"))
        git_locks.acquire(self.a, "origin", [Entry("m.py#f", 1)], claim_branch="claude/1")
        self.assertEqual(self.run_cli("verify", "--base", "origin/main", "--claim", "1")[0], 0)
        Path(self.a, "m.py").write_text(BASE.replace("x + 1", "x + 2").replace("return 0", "return 1"),
                                        encoding="utf-8")
        git(self.a, "commit", "--quiet", "-am", "outside the grant")
        code, said = self.run_cli("verify", "--base", "origin/main", "--claim", "1")
        self.assertEqual(code, 1)
        self.assertIn("m.py#h is changed but #1 holds no write lock on it", said)
        self.assertEqual(self.run_cli("verify", "--base", "origin/main", "--claim", "1", mode="advise")[0], 0)
        self.assertIn("locks are off", self.run_cli("verify", "--base", "origin/main", mode="off")[1])

    def test_a_pull_request_of_no_claim_fails_only_on_what_a_live_claim_holds(self):
        self.claim(self.b, 2)
        git_locks.acquire(self.b, "origin", [Entry("m.py#f", 2, WRITE, "wb")], claim_branch="claude/2")
        git(self.a, "checkout", "--quiet", "-B", "fix", "origin/main")
        Path(self.a, "m.py").write_text(BASE.replace("return 0", "return 1"), encoding="utf-8")
        git(self.a, "commit", "--quiet", "-am", "a fix to h")
        self.assertEqual(self.run_cli("verify", "--base", "origin/main")[0], 0)
        Path(self.a, "m.py").write_text(BASE.replace("x + 1", "x - 1"), encoding="utf-8")
        git(self.a, "commit", "--quiet", "-am", "a fix to f")
        code, said = self.run_cli("verify", "--base", "origin/main")
        self.assertEqual(code, 1)
        self.assertIn("m.py#f is held by #2 (wb, write)", said)

    def test_status_and_a_refusal_read_as_lines(self):
        self.claim(self.a, 1)
        self.assertIn("no locks", self.run_cli("status")[1])
        self.assertEqual(self.run_cli("acquire", "--claim", "1", "--worker", "wa", "--with-claim", "m.py#g")[0], 0)
        self.assertIn("m.py#f\tread\t#1\twa", self.run_cli("status")[1])
        self.claim(self.b, 2)
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.run_locks(["--repo", self.b, "acquire", "--claim", "2", "--with-claim", "m.py#f"], environ={})
        self.assertEqual(code, 1)
        self.assertIn("refused: m.py#f (write) is held by #1 (wa, read)", err.getvalue())


class Overlapping(Remote):
    """overlap: a change behind main brings it in only where what main did
    since the base meets what the change edits or builds on."""

    def run_cli(self, *args, mode="enforce"):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.run_locks(["--repo", self.a, *args], environ={"SYMPHONY_LOCKS": mode})
        return code, out.getvalue() + err.getvalue()

    def branch(self, edit):
        git(self.a, "checkout", "--quiet", "-B", "work", "origin/main")
        Path(self.a, "m.py").write_text(edit(BASE), encoding="utf-8")
        git(self.a, "commit", "--quiet", "-am", "the change")

    def main_moves(self, edit, path="m.py"):
        target = Path(self.seed, path)
        text = target.read_text(encoding="utf-8") if target.exists() else ""
        target.write_text(edit(text), encoding="utf-8")
        git(self.seed, "add", path)
        git(self.seed, "commit", "--quiet", "-m", "main moves")
        git(self.seed, "push", "--quiet", "origin", "main")
        git(self.a, "fetch", "--quiet", "origin")

    def test_a_change_main_has_not_moved_past_needs_nothing(self):
        self.branch(lambda text: text.replace("return 0", "return 1"))
        code, said = self.run_cli("overlap", "--base", "origin/main")
        self.assertEqual(code, 0)
        self.assertIn("need not bring it in", said)

    def test_main_moving_in_a_function_the_change_neither_edits_nor_calls_needs_nothing(self):
        self.branch(lambda text: text.replace("return 0", "return 1"))
        self.main_moves(lambda text: text.replace("x + 1", "x + 2"))
        self.assertEqual(self.run_cli("overlap", "--base", "origin/main")[0], 0)

    def test_main_moving_in_a_file_the_change_does_not_touch_needs_nothing(self):
        self.branch(lambda text: text.replace("return 0", "return 1"))
        self.main_moves(lambda text: "other\n", path="notes.txt")
        self.assertEqual(self.run_cli("overlap", "--base", "origin/main")[0], 0)

    def test_main_changing_what_the_change_calls_brings_main_in(self):
        self.branch(lambda text: text.replace("* 2", "* 3"))
        self.main_moves(lambda text: text.replace("x + 1", "x + 2"))
        code, said = self.run_cli("overlap", "--base", "origin/main")
        self.assertEqual(code, 1)
        self.assertIn("origin/main edited m.py#f since this change's base, which this change builds on", said)

    def test_main_calling_what_the_change_edits_brings_main_in(self):
        self.branch(lambda text: text.replace("x + 1", "x + 2"))
        self.main_moves(lambda text: text.replace("* 2", "* 3"))
        code, said = self.run_cli("overlap", "--base", "origin/main")
        self.assertEqual(code, 1)
        self.assertIn("origin/main built on m.py#f since this change's base, which this change edits", said)

    def test_two_sides_that_both_build_on_one_function_need_nothing(self):
        self.branch(lambda text: text.replace("* 2", "* 3"))  # g, which reads f
        self.main_moves(lambda text: text.replace("return 0", "return f(0)"))  # h, now reading f
        self.assertEqual(self.run_cli("overlap", "--base", "origin/main")[0], 0)

    def test_a_branch_that_merged_main_in_needs_nothing(self):
        self.branch(lambda text: text.replace("* 2", "* 3"))
        self.main_moves(lambda text: text.replace("x + 1", "x + 2"))
        self.assertEqual(self.run_cli("overlap", "--base", "origin/main")[0], 1)
        git(self.a, "merge", "--quiet", "--no-edit", "origin/main")
        self.assertEqual(self.run_cli("overlap", "--base", "origin/main")[0], 0)

    def test_the_test_merge_is_judged_by_the_branch_s_own_change(self):
        self.branch(lambda text: text.replace("* 2", "* 3"))
        self.main_moves(lambda text: text.replace("x + 1", "x + 2"))
        git(self.a, "checkout", "--quiet", "--detach", "origin/main")
        git(self.a, "merge", "--quiet", "--no-edit", "work")  # GitHub's refs/pull/N/merge
        code, said = self.run_cli("overlap", "--base", "origin/main")
        self.assertEqual(code, 1)
        self.assertIn("edited m.py#f", said)

    def test_a_file_the_branch_adds_reads_what_it_imports(self):
        git(self.a, "checkout", "--quiet", "-B", "work", "origin/main")
        Path(self.a, "n.py").write_text("from m import f\n\n\ndef k():\n    return f(1)\n", encoding="utf-8")
        git(self.a, "add", "n.py")
        git(self.a, "commit", "--quiet", "-m", "a new file")
        self.main_moves(lambda text: text.replace("x + 1", "x + 2"))
        code, said = self.run_cli("overlap", "--base", "origin/main")
        self.assertEqual(code, 1)
        self.assertIn("which this change builds on", said)

    def test_a_module_level_edit_reads_what_it_imports(self):
        git(self.a, "checkout", "--quiet", "-B", "work", "origin/main")
        Path(self.a, "m.py").write_text(BASE + "\nVALUE = f(3)\n", encoding="utf-8")
        git(self.a, "commit", "--quiet", "-am", "a value at the top")
        self.main_moves(lambda text: text.replace("x + 1", "x + 2"))
        self.assertEqual(self.run_cli("overlap", "--base", "origin/main")[0], 1)

    def test_a_file_main_deleted_meets_an_edit_to_it(self):
        self.branch(lambda text: text.replace("x + 1", "x + 2"))
        Path(self.seed, "m.py").unlink()
        git(self.seed, "commit", "--quiet", "-am", "main drops m.py")
        git(self.seed, "push", "--quiet", "origin", "main")
        git(self.a, "fetch", "--quiet", "origin")
        code, said = self.run_cli("overlap", "--base", "origin/main")
        self.assertEqual(code, 1)
        self.assertIn("edited m.py since", said)

    def test_a_shallow_clone_is_deepened_until_the_fork_is_found(self):
        for step in range(3):
            self.main_moves(lambda text, step=step: text + f"# {step}\n", path="notes.py")
        self.branch(lambda text: text.replace("return 0", "return 1"))
        git(self.a, "push", "--quiet", "origin", "work")
        shallow = str(Path(self.tmp.name) / "shallow")
        git(self.tmp.name, "clone", "--quiet", "--depth=1", "--branch", "work", self.bare, shallow)
        quiet(shallow)
        git(shallow, "fetch", "--quiet", "--depth=1", "origin", "+refs/heads/main:refs/remotes/origin/main")
        self.assertEqual(git(shallow, "rev-parse", "--is-shallow-repository"), "true")
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.run_locks(["--repo", shallow, "overlap", "--base", "origin/main"],
                                 environ={"SYMPHONY_LOCKS": "enforce"})
        self.assertEqual(code, 0, out.getvalue() + err.getvalue())
        self.assertIn("need not bring it in", out.getvalue())

    def checkout_as_actions_does(self, sha):
        """A clone as actions/checkout makes one on a pull_request event:
        the test merge alone, one commit deep, and no branch at all."""
        shallow = str(Path(self.tmp.name) / f"actions-{sha[:7]}")
        git(self.tmp.name, "init", "--quiet", shallow)
        quiet(shallow)
        git(shallow, "remote", "add", "origin", self.bare)
        git(shallow, "fetch", "--quiet", "--depth=1", "--no-tags", "origin", f"+{sha}:refs/remotes/pull/1/merge")
        git(shallow, "checkout", "--quiet", "--detach", sha)
        self.assertEqual(git(shallow, "rev-parse", "--is-shallow-repository"), "true")
        self.assertEqual(git(shallow, "rev-parse", "--verify", "--quiet", "origin/main", check=False), "")
        return shallow

    def pull_merge(self, branch="work"):
        """GitHub's refs/pull/N/merge for the branch, against main as the
        remote has it now, made and pushed from the seed."""
        git(self.seed, "fetch", "--quiet", "origin")
        git(self.seed, "checkout", "--quiet", "--detach", "origin/main")
        git(self.seed, "merge", "--quiet", "--no-edit", f"origin/{branch}")
        sha = git(self.seed, "rev-parse", "HEAD")
        git(self.seed, "push", "--quiet", "origin", f"{sha}:refs/pull/1/merge")
        git(self.seed, "checkout", "--quiet", "main")
        return sha

    def run_in(self, repo, *args, mode="enforce"):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.run_locks(["--repo", repo, *args], environ={"SYMPHONY_LOCKS": mode})
        return code, out.getvalue() + err.getvalue()

    def test_the_checkout_actions_makes_judges_the_branch_against_main_as_it_now_stands(self):
        self.branch(lambda text: text.replace("* 2", "* 3"))  # g, which reads f
        git(self.a, "push", "--quiet", "origin", "work")
        merge = self.pull_merge()
        self.main_moves(lambda text: text.replace("x + 1", "x + 2"))  # f, after the merge was made
        code, said = self.run_in(self.checkout_as_actions_does(merge), "overlap", "--base", "origin/main")
        self.assertEqual(code, 1, said)
        self.assertIn("edited m.py#f since this change's base, which this change builds on", said)

    def test_the_checkout_actions_makes_needs_nothing_while_main_stands_where_the_merge_was_made(self):
        self.branch(lambda text: text.replace("* 2", "* 3"))
        git(self.a, "push", "--quiet", "origin", "work")
        merge = self.pull_merge()
        code, said = self.run_in(self.checkout_as_actions_does(merge), "overlap", "--base", "origin/main")
        self.assertEqual(code, 0, said)
        self.assertIn("need not bring it in", said)

    def test_the_checkout_actions_makes_needs_nothing_where_main_moved_elsewhere(self):
        self.branch(lambda text: text.replace("return 0", "return 1"))  # h, which reads nothing
        git(self.a, "push", "--quiet", "origin", "work")
        merge = self.pull_merge()
        self.main_moves(lambda text: text.replace("x + 1", "x + 2"))  # f, which h neither edits nor calls
        code, said = self.run_in(self.checkout_as_actions_does(merge), "overlap", "--base", "origin/main")
        self.assertEqual(code, 0, said)

    def test_a_file_read_whole_meets_on_any_edit(self):
        self.main_moves(lambda text: "one\n", path="notes.txt")
        git(self.a, "checkout", "--quiet", "-B", "work", "origin/main")
        Path(self.a, "notes.txt").write_text("one\ntwo\n", encoding="utf-8")
        git(self.a, "commit", "--quiet", "-am", "the change")
        self.main_moves(lambda text: "zero\n" + text, path="notes.txt")
        self.assertEqual(self.run_cli("overlap", "--base", "origin/main")[0], 1)

    def test_the_switch_decides_whether_a_meeting_fails(self):
        self.branch(lambda text: text.replace("* 2", "* 3"))
        self.main_moves(lambda text: text.replace("x + 1", "x + 2"))
        self.assertEqual(self.run_cli("overlap", "--base", "origin/main", mode="advise")[0], 0)
        self.assertIn("locks are off", self.run_cli("overlap", "--base", "origin/main", mode="off")[1])


class Reviewed(Remote):
    """The cases an adversarial review of the first version found."""

    def test_a_refusal_of_the_table_by_the_server_is_not_read_as_a_held_claim(self):
        hook = Path(self.bare) / "hooks" / "update"
        hook.write_text("#!/bin/sh\n[ \"$1\" = refs/heads/locks ] && exit 1\nexit 0\n", encoding="utf-8")
        hook.chmod(0o755)
        self.claim(self.a, 1)
        with self.assertRaises(git_locks.LocksFailed):
            git_locks.acquire(self.a, "origin", [Entry("m.py#f", 1)], claim_branch="claude/1")
        self.assertFalse(self.remote_ref("refs/heads/claude/1"))

    def test_commits_built_on_another_s_claim_are_never_pushed_onto_it(self):
        self.claim(self.a, 1)
        git_locks.acquire(self.a, "origin", [Entry("m.py#f", 1)], claim_branch="claude/1")
        before = self.remote_ref("refs/heads/claude/1")
        git(self.b, "fetch", "--quiet", "origin")
        git(self.b, "checkout", "--quiet", "-B", "claude/1", "origin/claude/1")
        Path(self.b, "m.py").write_text(BASE.replace("return 0", "return 9"), encoding="utf-8")
        git(self.b, "commit", "--quiet", "-am", "on top of another's claim")
        with self.assertRaises(git_locks.ClaimTaken):
            git_locks.acquire(self.b, "origin", [Entry("m.py#h", 1)], claim_branch="claude/1")
        self.assertEqual(self.remote_ref("refs/heads/claude/1"), before)

    def test_locks_for_a_claim_not_on_the_remote_are_refused(self):
        with self.assertRaises(git_locks.LocksFailed):
            git_locks.acquire(self.a, "origin", [Entry("m.py#f", 3)])
        with self.assertRaises(git_locks.LocksFailed):
            git_locks.acquire(self.a, "origin", [Entry("m.py#f", 0)])
        self.assertFalse(self.remote_ref(f"refs/heads/{locks.LOCKS_BRANCH}"))

    def test_a_pattern_in_a_file_name_is_read_as_the_name(self):
        Path(self.seed, "a[1].py").write_text(BASE, encoding="utf-8")
        Path(self.seed, "a1.py").write_text(BASE, encoding="utf-8")
        git(self.seed, "add", ".")
        git(self.seed, "commit", "--quiet", "-m", "two files")
        git(self.seed, "push", "--quiet", "origin", "main")
        git(self.a, "fetch", "--quiet", "origin")
        git(self.a, "checkout", "--quiet", "-B", "work", "origin/main")
        Path(self.a, "a[1].py").write_text(BASE.replace("return 0", "return 1"), encoding="utf-8")
        Path(self.a, "a1.py").write_text(BASE.replace("x + 1", "x + 2"), encoding="utf-8")
        git(self.a, "commit", "--quiet", "-am", "both")
        self.assertEqual(git_locks.touched(self.a, "origin/main", "HEAD"), ["a1.py#f", "a[1].py#h"])

    def test_a_mode_change_touches_the_whole_file(self):
        git(self.a, "checkout", "--quiet", "-B", "work", "origin/main")
        os.chmod(Path(self.a, "m.py"), 0o755)
        git(self.a, "commit", "--quiet", "-am", "executable")
        self.assertEqual(git_locks.touched(self.a, "origin/main", "HEAD"), ["m.py"])

    def test_verify_at_advise_never_fails_on_what_it_cannot_read(self):
        args = ["--repo", self.a, "verify", "--base", "no-such-ref", "--claim", "1"]
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.run_locks(args, environ={"SYMPHONY_LOCKS": "advise"}), 0)
            self.assertEqual(cli.run_locks(args, environ={"SYMPHONY_LOCKS": "enforce"}), 1)


class ReviewedAgain(Remote):
    """The cases the second review round found."""

    def test_checking_out_another_s_claim_and_pushing_it_claims_nothing(self):
        self.claim(self.a, 5)
        git_locks.acquire(self.a, "origin", [Entry("m.py#f", 5)], claim_branch="claude/5")
        git(self.b, "fetch", "--quiet", "origin")
        git(self.b, "checkout", "--quiet", "-B", "claude/5", "origin/claude/5")
        with self.assertRaises(git_locks.ClaimTaken):
            git_locks.acquire(self.b, "origin", [Entry("m.py#h", 5, WRITE, "wb")], claim_branch="claude/5")
        self.assertEqual(self.table(), [Entry("m.py#f", 5)])

    def test_a_landed_claim_takes_no_more_locks(self):
        self.claim(self.a, 1)
        git_locks.acquire(self.a, "origin", [Entry("m.py#f", 1)], claim_branch="claude/1")
        git(self.a, "push", "--quiet", "origin", "claude/1:main")
        with self.assertRaises(git_locks.LocksFailed):
            git_locks.acquire(self.a, "origin", [Entry("m.py#h", 1)])

    def test_a_claim_branch_with_no_commit_of_its_own_is_refused(self):
        git(self.a, "checkout", "--quiet", "-B", "claude/2", "origin/main")
        with self.assertRaises(git_locks.LocksFailed):
            git_locks.acquire(self.a, "origin", [Entry("m.py#f", 2)], claim_branch="claude/2")
        self.assertFalse(self.remote_ref("refs/heads/claude/2"))

    def test_the_claim_branch_must_be_the_claim_s_own(self):
        self.claim(self.a, 3)
        with self.assertRaises(git_locks.LocksFailed):
            git_locks.acquire(self.a, "origin", [Entry("m.py#f", 4)], claim_branch="claude/3")

    def test_a_refusal_that_will_not_go_away_says_why_at_once(self):
        hook = Path(self.bare) / "hooks" / "update"
        hook.write_text("#!/bin/sh\n[ \"$1\" = refs/heads/locks ] && exit 1\nexit 0\n", encoding="utf-8")
        hook.chmod(0o755)
        self.claim(self.a, 1)
        with self.assertRaises(git_locks.LocksFailed) as failed:
            git_locks.acquire(self.a, "origin", [Entry("m.py#f", 1)], claim_branch="claude/1")
        self.assertIn("the remote refused the push", str(failed.exception))

    def test_a_coloured_diff_in_the_user_s_settings_changes_nothing(self):
        git(self.a, "config", "color.diff", "always")
        git(self.a, "checkout", "--quiet", "-B", "work", "origin/main")
        Path(self.a, "m.py").write_text(BASE.replace("* 2", "* 3"), encoding="utf-8")
        git(self.a, "commit", "--quiet", "-am", "g")
        self.assertEqual(git_locks.touched(self.a, "origin/main", "HEAD"), ["m.py#g"])


if __name__ == "__main__":
    unittest.main()
