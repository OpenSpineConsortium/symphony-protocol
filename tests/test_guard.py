"""The push guard refuses exactly what the board rules forbid and lets
everything else through, including a push it cannot read, as one inside
quoting it misreads: the hook is the first fence, branch protection the
second, so it fails open."""

import ast
import contextlib
import os
import random
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sdlc_protocol import claims, guard  # noqa: E402

FORCE = ("--force overwrites history another account may hold; the one forced push the protocol allows is "
         "--force-with-lease on your own claude/ branch after a rebase (.claude/rules/board.md)")
PLUS = ("a + before a refspec forces that ref as --force does, and git lets it override --force-with-lease; the "
        "one forced push the protocol allows is --force-with-lease on your own claude/ branch after a rebase, with "
        "no + (.claude/rules/board.md)")
MAIN = "a push to main is refused: the default branch takes only pull requests (.claude/rules/board.md)"
TOO_DEEP = ("a command whose here-documents nest in command substitutions more than 16 deep is refused: the "
            "guard cannot read it to tell which of its lines run; write the text to a file first "
            "(.claude/rules/board.md)")
TOO_LONG = ("a command of more than 262144 characters is refused unread: the guard would take longer to read it "
            "than a hook may run; write the text to a file first (.claude/rules/board.md)")
TOO_SLOW = ("a command the guard cannot read and judge in 10 seconds, or for which git did not answer in time, is "
            "refused: a hook that runs out of time lets the command run; write the text to a file first, or push in a "
            "command of its own (.claude/rules/board.md)")
BOARD = "a push to board is refused: only the board workflow writes that branch (.claude/rules/board.md)"


def refusal(args, current="claude/7", default="main", claim_file_at=None):
    return guard.refusal(args, current, default, claim_file_at)


def files_at(table):
    """A claim-file reader over a table of (ref, number) to text, as
    guard.claim_file_reader answers from a clone."""
    return lambda ref, number: table.get((ref, number))


CLAIM_A = "# Claim: #7\n\n- Worker: a\n- Branch: claude/7\n"
CLAIM_B = "# Claim: #7\n\n- Worker: b (a second session)\n"
ORIGIN_7 = "refs/remotes/origin/claude/7"


class RefusalTest(unittest.TestCase):
    def test_push_to_default_branch(self):
        self.assertIsNotNone(refusal(["origin", "main"]))

    def test_push_head_to_default_branch(self):
        self.assertIsNotNone(refusal(["origin", "HEAD:main"]))

    def test_delete_board_branch(self):
        self.assertIsNotNone(refusal(["origin", ":board"]))
        self.assertIsNotNone(refusal(["--delete", "origin", "board"]))

    def test_plain_push_on_default_branch(self):
        self.assertIsNotNone(refusal([], current="main"))

    def test_force_refused_even_on_own_claim(self):
        self.assertIsNotNone(refusal(["--force", "origin", "claude/7"]))
        self.assertIsNotNone(refusal(["-f", "origin", "claude/7"]))

    def test_a_refspec_written_with_a_plus_is_a_force(self):
        # A leading + forces that one ref as --force forces them all, and
        # git 2.43 lets it override a lease: a push of +claude/7 with
        # --force-with-lease overwrote a peer's newer commit that the lease
        # alone refused. The refusal names the +, which is what to drop.
        for args in (["origin", "+claude/7"], ["origin", "+HEAD:claude/7"], ["origin", "+claude/7:claude/8"],
                     ["--force-with-lease", "origin", "+claude/7"], ["-u", "origin", "claude/7", "+feature"],
                     ["origin", "+"]):
            self.assertEqual(refusal(args), PLUS, args)
        self.assertEqual(refusal(["--force", "origin", "+claude/7"]), FORCE, "--force is named where it is given")
        self.assertIsNone(refusal(["+origin", "claude/7"]), "the first word is the remote, not a refspec")
        # Under --delete git reads the + as part of the name to delete,
        # "unable to delete '+claude/7'", so that is no force.
        self.assertIsNone(refusal(["--delete", "origin", "+claude/7"]))

    def test_short_options_bundle_as_git_reads_them(self):
        # git 2.43 force-updated a branch on "git push -fu origin HEAD:x"
        # and on -uf; -o takes the rest of its word as its value.
        for args in (["-fu", "origin", "claude/7"], ["-uf", "origin", "claude/7"], ["-vqf", "origin", "x"],
                     ["-df", "origin", "x"]):
            self.assertEqual(refusal(args), FORCE, args)
        for args in (["-of", "origin", "claude/7"], ["-uo", "f", "origin", "claude/7"], ["-un", "origin", "claude/7"]):
            self.assertIsNone(refusal(args), args)
        self.assertIsNone(refusal(["-du", "origin", "+claude/7"]), "-d in a bundle deletes, so the + is a name")

    def test_a_long_option_is_read_by_any_start_that_names_it_alone(self):
        # git 2.43 took --force-w for --force-with-lease, and --mi for
        # --mirror; --forc and --d name more than one option, and git
        # refuses them and pushes nothing.
        lease = refusal(["--force-with-lease", "origin", "feature"], current="feature")
        self.assertEqual(refusal(["--force-w", "origin", "feature"], current="feature"), lease)
        self.assertEqual(refusal(["--force-with-l=feature", "origin", "feature"], current="feature"), lease)
        self.assertIsNone(refusal(["--force-w", "origin", "claude/7"]))
        self.assertEqual(refusal(["--mi", "origin"]), refusal(["--mirror", "origin"]))
        self.assertEqual(refusal(["--al", "origin"]), refusal(["--all", "origin"]))
        self.assertEqual(refusal(["--br", "origin"]), refusal(["--branches", "origin"]))
        self.assertIsNone(refusal(["--de", "origin", "+claude/7"]), "--de is --delete")
        # git 2.43 deleted claude/2 on "--delet origin claude/2", as it does
        # on --delete, which the guard lets through for one's own claim
        # branch after its merge, and refuses for main.
        self.assertIsNone(refusal(["--delet", "origin", "claude/2"]))
        self.assertEqual(refusal(["--delet", "origin", "main"]), MAIN)
        # git 2.43 answered "git push --forc origin claude/1" with "ambiguous
        # option: forc (could be --force-with-lease or --force-if-includes)",
        # exit 129, and pushed nothing.
        for ambiguous in ("--forc", "--d", "--a", "--force-"):
            self.assertIsNone(refusal([ambiguous, "origin", "claude/7"]), ambiguous)

    def test_an_option_taken_back_with_no_is_not_in_force(self):
        self.assertIsNone(refusal(["--force", "--no-force", "origin", "claude/7"]))
        self.assertIsNone(refusal(["--force-with-lease", "--no-force-with", "origin", "feature"], current="feature"))
        self.assertIsNone(refusal(["--all", "--no-all", "origin", "claude/7"]))
        self.assertEqual(refusal(["--no-force", "-f", "origin", "claude/7"]), FORCE)

    def test_a_value_is_no_refspec_and_the_words_after_two_dashes_are_refspecs(self):
        self.assertEqual(refusal(["--recurse-submodules", "check", "origin", "main"]), MAIN)
        self.assertIsNone(refusal(["--exec", "git-receive-pack", "origin", "claude/7"]))
        self.assertIsNone(refusal(["--receive-pack=git-receive-pack", "-o", "ci.skip", "origin", "claude/7"]))
        self.assertEqual(refusal(["--", "origin", "main"]), MAIN)

    def test_a_refspec_that_moves_many_branches_is_wholesale(self):
        # The matching refspec : updates every branch both sides have, the
        # default one among them, and a pattern with a * pushes every
        # branch it matches.
        for spec in (":", "+:", "refs/heads/*:refs/heads/*", "claude/*"):
            self.assertEqual(refusal(["origin", spec]),
                             f"a push with the refspec {spec} moves branches wholesale; push your own claim "
                             "branch alone (.claude/rules/board.md)", spec)

    def test_a_name_that_reads_as_a_claim_and_claims_nothing_is_refused(self):
        # GitHub's lock is per name, so claude/03 beside claude/3 would be a
        # second branch on #3 that claims nothing; the guard names the
        # issue's own claim branch.
        self.assertEqual(refusal(["origin", "claude/03"]), (
            "a push to claude/03 is refused: it reads as a claim branch and claims nothing, since a claim branch "
            "is claude/ and the issue's number in one to nine ASCII digits with no leading zero, so the claim "
            "branch of #3 is claude/3 (docs/agents/PROTOCOL.md, Claim)"))
        self.assertIn("so the claim branch of #3 is claude/3", refusal(["-u", "origin", "HEAD"], current="claude/\u0663"))
        self.assertIn("so the claim branch of #0 is claude/0", refusal([], current="claude/00"))
        self.assertIn("with no leading zero (docs/agents/PROTOCOL.md", refusal(["origin", "HEAD:claude/1234567890"]))
        for args in (["origin", "claude/3"], ["origin", "claude/0"], ["origin", "claude/x"],
                     ["origin", "claude/upbeat-sagan-6th2hu"], ["origin", "claude/03-notes"],
                     ["origin", "claude/03:claude/3"], ["--delete", "origin", "claude/03"], ["origin", ":claude/03"],
                     ["-d", "origin", "claude/\u00b2"]):
            self.assertIsNone(refusal(args), args)

    def test_a_branch_written_as_git_resolves_it_is_that_branch(self):
        # git reads heads/main as refs/heads/main on both sides of a
        # refspec, as it reads any name with refs/ left off, and @ alone as
        # HEAD. Against a bare remote, git 2.43 updated main on "git push
        # origin heads/main", "HEAD:heads/main", "heads/claude/7:heads/main"
        # and, from main, "git push origin @"; it deleted board on "git push
        # origin :heads/board" and "git push --delete origin heads/board";
        # and the guard let each of them through.
        for args, current in ((["origin", "heads/main"], "claude/7"), (["origin", "HEAD:heads/main"], "claude/7"),
                              (["origin", "heads/claude/7:heads/main"], "claude/7"),
                              (["origin", ":heads/main"], "claude/7"),
                              (["--delete", "origin", "heads/main"], "claude/7"),
                              (["origin", "@"], "main"), (["-u", "origin", "@"], "main")):
            self.assertEqual(refusal(args, current=current), MAIN, args)
        for args in (["origin", "heads/board"], ["origin", "HEAD:heads/board"], ["origin", ":heads/board"],
                     ["--delete", "origin", "heads/board"], ["--delet", "origin", "heads/board"]):
            self.assertEqual(refusal(args), BOARD, args)
        # refs/heads/ is taken off once: git 2.43 made a branch named
        # heads/main on "git push origin HEAD:refs/heads/heads/main".
        self.assertIsNone(refusal(["origin", "HEAD:refs/heads/heads/main"]))
        self.assertIsNone(refusal(["origin", "refs/tags/main"]), "a tag is no branch")
        self.assertIsNone(refusal(["origin", "@"]), "@ on a claim branch pushes that branch")
        # git pushed claude/7 on "--force-with-lease origin heads/claude/7",
        # one's own claim branch, which the guard refused as another one.
        self.assertIsNone(refusal(["--force-with-lease", "origin", "heads/claude/7"]))

    def test_the_claim_number_is_the_rule_claims_states(self):
        # The guard keeps its own copy, since the marketplace takes guard.py
        # alone; it must say what claims.NUMBER says.
        self.assertEqual(guard.CLAIM_NUMBER.pattern, claims.NUMBER.pattern)

    def test_lease_allowed_on_claim_branch(self):
        self.assertIsNone(refusal(["--force-with-lease", "origin", "claude/7"]))
        self.assertIsNone(refusal(["-u", "--force-with-lease=claude/7", "origin", "claude/7"]))

    def test_the_worker_line_is_read_as_claims_reads_it(self):
        # The guard keeps its own copies, as it does of the claim number.
        self.assertEqual(guard.WORKER_LINE.pattern, claims.WORKER_LINE.pattern)
        self.assertEqual(guard.TRAILING_NOTE.pattern, claims.TRAILING_NOTE.pattern)
        self.assertEqual(guard.worker_named(CLAIM_A), "a")
        self.assertEqual(guard.worker_named(CLAIM_B), "b")
        self.assertEqual(guard.worker_named("- Account: **old** (note)\n"), "old")
        self.assertIsNone(guard.worker_named("# Claim: #7\n\n## Plan\n"))
        self.assertIsNone(guard.worker_named(None))

    def test_a_lease_s_values_are_kept_as_git_reads_them(self):
        options, _ = guard.push_words(["--force-with-lease", "origin", "claude/7"])
        self.assertEqual(options["force-with-lease"], [""])
        options, _ = guard.push_words(["--force-with-lease=claude/7:abc", "--force-with-lease=claude/8", "origin"])
        self.assertEqual(options["force-with-lease"], ["claude/7:abc", "claude/8"])
        options, _ = guard.push_words(["--force-with-lease=claude/7", "--no-force-with-lease", "origin"])
        self.assertNotIn("force-with-lease", options)
        self.assertIsNone(guard.lease_holds([], "claude/7"))
        self.assertEqual(guard.lease_holds([""], "claude/7"), "")
        self.assertEqual(guard.lease_holds(["claude/7:abc"], "claude/7"), "abc")
        self.assertEqual(guard.lease_holds(["refs/heads/claude/7"], "claude/7"), "")
        self.assertIsNone(guard.lease_holds(["claude/8:abc"], "claude/7"), "a lease on another ref holds nothing here")
        self.assertEqual(guard.lease_holds(["claude/7:abc", ""], "claude/7"), "abc", "a ref named is held as named")
        self.assertEqual(guard.lease_holds(["", "claude/7:abc"], "claude/7"), "abc")
        self.assertEqual(guard.lease_holds(["claude/7:abc", "claude/7:def"], "claude/7"), "abc", "the first naming")

    def test_a_lease_onto_another_worker_s_claim_is_refused_by_the_claim_file_on_origin(self):
        reader = files_at({(ORIGIN_7, "7"): CLAIM_A, ("claude/7", "7"): CLAIM_B, ("HEAD", "7"): CLAIM_B})
        reason = refusal(["--force-with-lease", "origin", "claude/7"], claim_file_at=reader)
        self.assertEqual(reason, "a push with --force-with-lease to claude/7 is refused: claude/7 on origin is a's "
                                 "claim (its claim file docs/agents/claims/7.md says so) and the branch you push "
                                 "claims #7 for b; never push to another worker's branch (.claude/rules/board.md)")
        self.assertEqual(refusal(["--force-with-lease", "origin"], claim_file_at=reader), reason, "HEAD is claude/7")
        self.assertEqual(refusal(["--force-with-lease=claude/7", "origin", "claude/7"], claim_file_at=reader), reason)
        self.assertEqual(refusal(["--force-with-lease", "origin", "HEAD:claude/7"], claim_file_at=reader), reason)
        self.assertIsNone(refusal(["origin", "claude/7"], claim_file_at=reader), "a plain push is git's to refuse")
        self.assertIsNone(refusal(["--force-with-lease", "origin", "claude/7"]), "no clone to read, no fence")
        self.assertIsNone(refusal(["--force-with-lease", "origin", ":claude/7"], claim_file_at=reader),
                          "a deletion carries no claim file")

    def test_a_lease_by_the_claim_s_own_worker_passes_and_an_unreadable_claim_is_not_judged(self):
        self.assertIsNone(refusal(["--force-with-lease", "origin", "claude/7"],
                                  claim_file_at=files_at({(ORIGIN_7, "7"): CLAIM_A, ("claude/7", "7"): CLAIM_A})))
        self.assertIsNone(refusal(["--force-with-lease", "origin", "claude/7"],
                                  claim_file_at=files_at({("claude/7", "7"): CLAIM_B})),
                          "origin shows no claim file: a claim the fence cannot judge")
        self.assertIsNone(refusal(["--force-with-lease", "origin", "claude/7"],
                                  claim_file_at=files_at({(ORIGIN_7, "7"): "# no worker line\n",
                                                          ("claude/7", "7"): CLAIM_B})))
        reader = files_at({(ORIGIN_7, "7"): CLAIM_A})
        self.assertEqual(refusal(["--force-with-lease", "origin", "claude/7"], claim_file_at=reader),
                         "a push with --force-with-lease to claude/7 is refused: claude/7 on origin is a's claim "
                         "(its claim file docs/agents/claims/7.md says so) and the branch you push carries no claim "
                         "file for #7; never push to another worker's branch (.claude/rules/board.md)")

    def test_a_lease_that_names_a_commit_is_judged_at_that_commit(self):
        reader = files_at({("abc", "7"): CLAIM_A, (ORIGIN_7, "7"): CLAIM_B, ("claude/7", "7"): CLAIM_B})
        self.assertIsNotNone(refusal(["--force-with-lease=claude/7:abc", "origin", "claude/7"], claim_file_at=reader))
        self.assertIsNone(refusal(["--force-with-lease=claude/8:abc", "origin", "claude/7"], claim_file_at=reader),
                          "a lease that holds only claude/8 holds nothing on claude/7")

    def test_a_commit_git_cannot_show_is_judged_at_the_remote_tracking_ref(self):
        """The claim skill's lease names the tip last pushed, which a session
        writes as a shell variable the guard sees unexpanded: the push lands
        only when origin stands at that commit, so origin's ref as fetched
        judges it."""
        reader = files_at({(ORIGIN_7, "7"): CLAIM_A, ("claude/7", "7"): CLAIM_B})
        self.assertIsNotNone(refusal(["--force-with-lease=claude/7:$TIP", "origin", "claude/7"], claim_file_at=reader))
        self.assertIsNotNone(refusal(["--force-with-lease=claude/7:abc", "origin", "claude/7"], claim_file_at=reader))
        reader = files_at({(ORIGIN_7, "7"): CLAIM_B, ("claude/7", "7"): CLAIM_B})
        self.assertIsNone(refusal(["--force-with-lease=claude/7:$TIP", "origin", "claude/7"], claim_file_at=reader))

    def test_the_remote_pushed_to_names_the_remote_tracking_ref(self):
        reader = files_at({("refs/remotes/upstream/claude/7", "7"): CLAIM_A, ("claude/7", "7"): CLAIM_B})
        self.assertIsNotNone(refusal(["--force-with-lease", "upstream", "claude/7"], claim_file_at=reader))
        self.assertIsNone(refusal(["--force-with-lease", "origin", "claude/7"], claim_file_at=reader),
                          "origin's ref is not there to read")
        self.assertEqual(guard.remote_ref("upstream", "claude/7"), "refs/remotes/upstream/claude/7")
        self.assertEqual(guard.remote_ref("git@github.com:o/r.git", "claude/7"), ORIGIN_7, "a URL has no tracking ref")
        self.assertEqual(guard.remote_ref("../other", "claude/7"), ORIGIN_7)
        self.assertEqual(guard.remote_ref("", "claude/7"), ORIGIN_7)

    def test_lease_refused_elsewhere(self):
        self.assertIsNotNone(refusal(["--force-with-lease", "origin", "feature"], current="feature"))

    def test_wholesale_pushes_refused(self):
        self.assertIsNotNone(refusal(["--mirror", "origin"]))
        self.assertIsNotNone(refusal(["--all", "origin"]))

    def test_ordinary_claim_pushes_allowed(self):
        self.assertIsNone(refusal(["origin", "claude/7"]))
        self.assertIsNone(refusal(["-u", "origin", "HEAD"], current="claude/7"))
        self.assertIsNone(refusal([], current="claude/7"))

    def test_full_ref_to_default_refused(self):
        self.assertIsNotNone(refusal(["origin", "refs/heads/main"]))

    def test_detached_head_plain_push_passes(self):
        self.assertIsNone(refusal([], current=None))


class ParsingTest(unittest.TestCase):
    def test_compound_command_finds_the_push(self):
        commands = guard.simple_commands("git fetch origin && git push origin main")
        pushes = [guard.push_arguments(argv) for argv in commands]
        self.assertIn(["origin", "main"], pushes)

    def test_quoted_text_is_not_a_push(self):
        commands = guard.simple_commands("echo 'git push origin main'")
        self.assertTrue(all(guard.push_arguments(argv) is None for argv in commands))

    def test_redirection_target_is_not_a_refspec(self):
        commands = guard.simple_commands("git push origin claude/7 2>&1")
        self.assertEqual(guard.push_arguments(commands[0]), ["origin", "claude/7"])

    def test_git_global_options_are_stepped_over(self):
        self.assertEqual(guard.push_arguments(["git", "-C", "clone", "push", "origin", "x"]),
                         ["origin", "x"])
        # F21: --config-env and --attr-source take their value as the next
        # word, as -C and -c do, so the verb is the word after it.
        for options in (["--config-env", "user.name=HOME"], ["--attr-source", "HEAD"], ["--namespace", "n"],
                        ["-c", "push.default=current"], ["--git-dir=.git"], ["--work-tree", "."], ["--no-pager"]):
            with self.subTest(options=options):
                self.assertEqual(guard.push_arguments(["git", *options, "push", "origin", "main"]),
                                 ["origin", "main"])

    def test_a_query_of_git_s_own_runs_no_push(self):
        """git prints its exec path, or one of its documentation paths, or a
        list of its commands, and exits: the words after it run nothing.
        --exec-path with a value sets the path and runs the command."""
        for query in ("--exec-path", "--html-path", "--man-path", "--info-path", "--list-cmds=main"):
            with self.subTest(query=query):
                self.assertIsNone(guard.push_arguments(["git", query, "push", "origin", "main"]))
        self.assertEqual(guard.push_arguments(["git", "--exec-path=/usr/lib/git-core", "push", "origin", "main"]),
                         ["origin", "main"])

    def test_a_nul_byte_in_a_directory_or_a_ref_is_a_place_git_cannot_answer_in(self):
        """subprocess refuses a NUL byte with ValueError, which git_line
        takes as no answer, so the hook judges the push by its words and
        never raises (F21's second review); and expanduser refuses a ~
        before a NUL byte, or before a lone surrogate, which JSON's \\ud800
        carries and no file name can hold, which joined takes as a place it
        cannot tell (F21's third review: until then the hook raised)."""
        for command in ("git -C a\x00b push origin main", "cd a\x00b && git push origin main"):
            with self.subTest(command=command):
                self.assertEqual(guard.run({"tool_input": {"command": command}, "cwd": str(ROOT)}),
                                 (guard.REFUSE, MAIN))
        self.assertEqual(guard.git_line(["status"], "a\x00b"), None)
        with mock.patch.object(guard, "branches", return_value=("claude/7", "main")):
            for place in ("~a\x00b", "~\ud800", "~/\ud800"):
                for shape in ("cd {}; git push origin HEAD", "git -C {} push origin HEAD", "env -C {} git push",
                              "pushd {}; git push", "cd {} && git -C {} push"):
                    command = shape.format(place, place)
                    with self.subTest(command=command):
                        self.assertEqual(guard.run({"tool_input": {"command": command}, "cwd": str(ROOT)}),
                                         (guard.PASS, ""))
                        self.assertEqual(guard.run({"tool_input": {"command": command + " origin main"},
                                                    "cwd": str(ROOT)})[0], guard.REFUSE)
            self.assertIsNone(guard.joined("/w", "~a\x00b"))
            self.assertIsNone(guard.joined("/w", "~\ud800"))
        lease = {"tool_input": {"command": "git push --force-with-lease=claude/7:a\x00b origin claude/7"},
                 "cwd": str(ROOT)}
        with mock.patch.object(guard, "branches", return_value=("claude/7", "main")):
            self.assertEqual(guard.run(lease)[0], guard.PASS)

    def test_an_empty_word_is_a_word(self):
        """'' and "" are words to the shell, and git -C takes the empty one
        as no change of directory, so the push is read whole (F21: an
        empty word was read as an operator and ended the command)."""
        for command in ("git -C '' push origin main", 'git -C "" push origin main'):
            with self.subTest(command=command):
                self.assertEqual(guard.simple_commands(command), [["git", "-C", "", "push", "origin", "main"]])

    def test_git_is_found_behind_assignments_and_the_four_wrappers(self):
        # A person may put the environment, env, command, nice or time
        # before git, each with its own options; the push behind them is
        # still a push.
        for command in ("FOO=1 git push origin main", "GIT_TRACE=1 A='b c' git push origin main",
                        "env git push origin main", "/usr/bin/env -i FOO=1 git push origin main",
                        "env -u HOME --chdir=. -C .. git push origin main", "env -- git push origin main",
                        "command git push origin main", "command -p git push origin main",
                        "nice git push origin main", "nice -n 5 git push origin main", "nice -10 git push origin main",
                        "nice --adjustment=3 git push origin main", "time git push origin main",
                        "time -p git push origin main", "time -o out.txt -f %e -a git push origin main",
                        "FOO=1 env BAR=2 nice -n 2 time -p command /usr/bin/git -C . push origin main"):
            pushes = [guard.push_arguments(argv) for argv in guard.simple_commands(command)]
            self.assertEqual(pushes, [["origin", "main"]], command)

    def test_a_wrapper_that_runs_no_git_push_is_no_push(self):
        # command -v and -V only say what would run; the rest run something
        # that is not git, or nothing at all.
        for command in ("command -v git", "command -V git push origin main", "command -pv git push origin main",
                        "env", "nice", "time", "FOO=1", "FOO=1 echo git push origin main", "env cat git push",
                        "nice -n 5", "time -o out.txt"):
            pushes = [guard.push_arguments(argv) for argv in guard.simple_commands(command)]
            self.assertEqual(pushes, [None] * len(pushes), command)

    def test_other_git_verbs_are_not_pushes(self):
        self.assertIsNone(guard.push_arguments(["git", "pull", "origin", "main"]))

    def test_a_newline_ends_a_command(self):
        commands = guard.simple_commands("git add -A\ngit commit -m x\ngit push origin main")
        self.assertEqual(commands, [["git", "add", "-A"], ["git", "commit", "-m", "x"],
                                    ["git", "push", "origin", "main"]])

    def test_a_comment_ends_at_its_newline(self):
        for command in ("git status # look first\ngit push origin main",
                        "# look first\ngit push origin main",
                        "true; # a note ending in a backslash \\\ngit push origin main"):
            self.assertEqual(guard.simple_commands(command)[-1],
                             ["git", "push", "origin", "main"], command)

    def test_a_hash_inside_a_word_or_quotes_is_not_a_comment(self):
        for command in ("git commit -m 'Claim #7' && git push origin main",
                        "echo a#b; git push origin main"):
            self.assertEqual(guard.simple_commands(command)[-1],
                             ["git", "push", "origin", "main"], command)

    def test_a_backslash_newline_joins_two_lines(self):
        self.assertEqual(guard.simple_commands("git push \\\n  origin main"),
                         [["git", "push", "origin", "main"]])

    def test_a_newline_inside_quotes_stays_inside_the_word(self):
        for command in ("git commit -m 'one\ngit push origin main' && git push -u origin claude/7",
                        'git commit -m "one\ngit push origin main" && git push -u origin claude/7'):
            commands = guard.simple_commands(command)
            self.assertEqual(commands[0], ["git", "commit", "-m", "one\ngit push origin main"], command)
            self.assertEqual(commands[1], ["git", "push", "-u", "origin", "claude/7"], command)

    def test_unparseable_command_yields_nothing(self):
        """simple_commands reads a command whole or not at all, as the
        template's shim, which the template's own tests pin, reads it; the
        hook reads it leniently and more than one way (ReadingTest)."""
        self.assertEqual(guard.simple_commands("git push 'unclosed"), [])
        self.assertEqual(guard.simple_commands("echo 'unclosed\ngit push origin main"), [])
        self.assertEqual(guard.simple_commands("git push --force origin main\necho \"unclosed"), [])


def plain_shell_before_f25(command):
    """guard.plain_shell as it was until F25's fix, word for word, which the
    pass must still give: the template's shim and its profile read it; but
    for \\$ and \\` inside double quotes, handed to shlex since F28's second
    review as $ and `, as bash hands them on (as_quoted), and since F29's
    fix bash's own quotings outside quotes, a $'...' that closes as the
    text it decodes to, single-quoted, a $"..." as "...", and $$ as one
    parameter, and a line continuation, which leaves whether a word starts
    as it was."""
    out, quote, word_start, i = [], None, True, 0
    while i < len(command):
        ch = command[i]
        if quote is None and command.startswith("$$", i):
            out.append("$$")
            i, word_start = i + 2, False
        elif quote is None and command.startswith("$'", i) and (end := guard.ansi_c_close(command, i + 2)):
            out.append(guard.single_quoted(guard.ansi_c_text(command[i + 2:end - 1])))
            i, word_start = end, False
        elif quote is None and command.startswith('$"', i):
            i, word_start = i + 1, False
        elif ch == "\\" and quote != "'":
            if quote == '"' and command[i + 1:i + 2] in ("$", "`"):
                out.append(command[i + 1])
            elif command[i + 1:i + 2] != "\n":
                out.append(command[i:i + 2])
            i, word_start = i + 2, word_start and quote is None and command[i + 1:i + 2] == "\n"
        elif quote:
            if ch == quote:
                quote = None
            out.append(ch)
            i, word_start = i + 1, False
        elif ch == "#" and word_start:
            end = command.find("\n", i)
            i = len(command) if end == -1 else end
        else:
            if ch in "'\"":
                quote = ch
            out.append(" ; " if ch == "\n" else ch)
            i, word_start = i + 1, ch in guard.WORD_BREAKS
    return "".join(out)


def lexed(text):
    lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def body_texts(command):
    """The text of each here-document body the guard tells in command."""
    return [command[body.start:body.end] for body in guard.here_document_bodies(command)]


def unsubstituted():
    """The guard with no substitution read apart (guard.read_apart), as it
    read a command until F24's fix, for a test that plays a guard built
    before it: neither what the shell runs of each substitution nor the
    command's own text with each standing as a hole (F29) is read."""
    return mock.patch.object(guard, "read_apart", lambda command: (command, ""))


@contextlib.contextmanager
def built_words_unread():
    """The guard with every word read as written, none built as bash builds
    it (guard.word_ways, guard.may_be, F29), for a test that plays a guard
    built before F29's fix."""
    with mock.patch.object(guard, "word_ways", lambda argv: ([list(argv)], False)), \
            mock.patch.object(guard, "may_be", lambda word, text: word == text):
        yield


# Pieces of shell to make commands of at random: quotes, backslashes,
# newlines, comments, substitutions, arithmetic and here-documents.
PIECES = ("'", '"', "\\", "\n", "#", " ", "$(", ")", "((", "))", "<<", "<<-", "<<<", "EOF", "\t", "x", ";", "|",
          "git push origin main", "It's", '"$(cat <<\'EOF\'', "\nEOF\n", "`", "$'")


class ReadingTest(unittest.TestCase):
    """How the hook reads a command (F25): bash runs each complete command
    before a line it cannot read and reads a here-document's body as text,
    so a quote that never closes is read as a character of its word and
    the command is read whole and with its bodies cut out, every push any
    reading finds judged; until the fix a quote that never closed hid
    every push in the command, and an apostrophe in a body opened a quote a
    later one could close around a push. bash 5.2 ran each push these
    tests say it runs."""

    def run_guard(self, command):
        payload = {"tool_input": {"command": command}, "cwd": str(ROOT)}
        with mock.patch.object(guard, "branches", return_value=("claude/7", "main")):
            return guard.run(payload, str(ROOT))

    def run_as_before_f25(self, command):
        """The hook as built until F25's fix: the command read whole or not
        at all, and no body told."""
        strict = guard.plain_text
        with mock.patch.object(guard, "plain_text", lambda command, **options: strict(command)), \
                mock.patch.object(guard, "here_document_bodies", lambda command: []), unsubstituted():
            return self.run_guard(command)

    def test_a_push_beside_a_quote_that_never_closes_is_read(self):
        """bash runs the push before the line it cannot read; it runs
        nothing of a line it cannot read whole, as the one-line form, which
        the hook refuses too, reading too much of such a line and never too
        little."""
        for command in ("git push origin main\necho \"unclosed", "git push origin main\necho 'unclosed",
                        "git push origin main\necho a \\", "git push origin main; echo \"unclosed",
                        "echo \"unclosed\ngit push origin main"):
            with self.subTest(command=command):
                self.assertEqual(self.run_guard(command), (2, MAIN))
        self.assertEqual(self.run_guard("git push -u origin claude/7\necho \"unclosed"), (0, ""))
        self.assertEqual(self.run_as_before_f25("git push origin main\necho \"unclosed"), (0, ""),
                         "as built until F25's fix: an unclosed quote hid every push in the command")

    def test_a_quote_that_never_closes_is_a_character_of_its_word_when_read_leniently(self):
        self.assertEqual(guard.plain_text("git push 'unclosed", lenient=True), "git push \\'unclosed")
        self.assertEqual(guard.plain_text('echo "a\ngit push origin main', lenient=True),
                         'echo \\"a ; git push origin main')
        self.assertEqual(guard.plain_text("echo a \\", lenient=True), "echo a \\\\")
        self.assertEqual(lexed(guard.plain_text("echo \"it's\" 'a\"b' \"c", lenient=True)),
                         ["echo", "it's", 'a"b', '"c'])
        self.assertEqual(guard.plain_text("git push 'unclosed"), "git push 'unclosed", "strict: left for shlex")

    def test_plain_shell_is_the_pass_it_was(self):
        """The strict pass gives what it gave before the fix, for every
        command, so the template's shim and profile read as they did; read
        leniently, every command shlex reads whole reads the same, but for
        a backquoted span, which it reads as one opaque part of a word
        (backquoted_word), and every other one reads too."""
        draw = random.Random(25)
        for _ in range(3000):
            command = "".join(draw.choice(PIECES) for _ in range(draw.randint(1, 12)))
            with self.subTest(command=command):
                self.assertEqual(guard.plain_shell(command), plain_shell_before_f25(command))
                lenient = guard.plain_text(command, lenient=True)
                lexed(lenient)
                if guard.BACKQUOTED.search(command):
                    continue
                try:
                    lexed(guard.plain_shell(command))
                except ValueError:
                    continue
                self.assertEqual(lenient, guard.plain_shell(command))

    def test_here_document_bodies_are_told_as_bash_reads_them(self):
        for command, bodies in (
                ("cat <<'EOF' > /dev/null\nIt's done\nEOF\ngit push origin main", ["It's done\nEOF\n"]),
                ("cat <<EOF\nx\nEOF", ["x\nEOF"]),
                ("cat << EOF | sort\nx\nEOF\nls", ["x\nEOF\n"]),
                ("cat <<-EOF\n\tx\n\tEOF\nls", ["\tx\n\tEOF\n"]),
                ("cat <<A <<'B'\na\nA\nb\nB\nls", ["a\nA\n", "b\nB\n"]),
                ("cat <<'EOF'\nIt's\ngit push origin main", ["It's\ngit push origin main"]),
                ("cat <<'EOF' \"multi\nline\"\nbody\nEOF\nls", ["body\nEOF\n"]),
                ("git commit -m \"$(cat <<'EOF'\nSay \"hi\nEOF\n)\"\nls", ["Say \"hi\nEOF\n"]),
                ("x=$(cat <<'EOF'\nhi\nEOF)\nls", ["hi\nEOF"]),
                ("x=\"$(cat <<-EOF\n\thi\n\tEOF ) \"\nls", ["\thi\n\tEOF"]),
                ("cat <<EOF; y=$(\necho inner)\nbody\nEOF\nls", ["body\nEOF\n"]),
                ("cat <<EOF; (\necho sub)\nbody\nEOF", ["echo sub)\nbody\nEOF"]),
                ("cat <<\"E\"OF\nx\nEOF", ["x\nEOF"]), ("cat <<\\EOF\nx\nEOF", ["x\nEOF"]),
                ("cat <<E'O'F\nx\nEOF", ["x\nEOF"]), ("cat <<''\nx\n\nls", ["x\n\n"]),
                ("echo a<<b\nx\nb", ["x\nb"]), ("cat <<EOF # it's\nx\nEOF\nls", ["x\nEOF\n"]),
                ("cat <<EOF \\\n> out\nx\nEOF", ["x\nEOF"]),
                ("cat <<'EOF'\nEOFX\nEOF)\nEOF\nls", ["EOFX\nEOF)\nEOF\n"])):
            with self.subTest(command=command):
                self.assertEqual(body_texts(command), bodies)
        for command in ("cat <<<'EOF'\nIt's", "echo $((1<<2))\nIt's", "(( x <<= 2 ))\nIt's", "# cat <<EOF\nIt's",
                        "echo '<<EOF'\nIt's", "echo \"<<EOF\"\nIt's", "cat <<\nIt's", "cat << ;\nIt's",
                        "cat \\<<EOF\nIt's", "echo \"$((1<<2))\"\nIt's", "ls"):
            with self.subTest(command=command):
                self.assertEqual(guard.here_document_bodies(command), [])

    def test_an_expanded_body_runs_its_substitutions_and_nothing_else(self):
        """A body whose word nothing quotes is expanded, so the shell runs
        its command substitutions, and those alone are read where the body
        is cut out, apart, after the reading (substituted; since F24's first
        review not in the body's place too, where they were read again); a
        quoted word's body runs nothing."""
        runs = [body.runs for body in guard.here_document_bodies(
            "cat <<EOF\nIt's $(git push origin main) done, isn't it, $(echo \"a\" ')') \\$(no) $((1+2))\nEOF")]
        self.assertEqual(runs, [("$(git push origin main)", "$(echo \"a\" ')')")])
        self.assertEqual([body.runs for body in guard.here_document_bodies("cat <<'EOF'\n$(git push)\nEOF")], [()])
        self.assertEqual(guard.readings("cat <<EOF\nIt's $(git push origin main) done\nEOF\nls")[1],
                         "cat <<EOF ; ls ; ( git push origin main ) ")

    def test_an_expanded_body_joins_a_line_that_ends_in_a_backslash(self):
        """bash takes a backslash-newline out of a body it expands before it
        compares a line with the delimiter, an odd run of backslashes
        continuing the line and an even one not, and takes a <<-'s tabs
        off the joined line's start alone; a quoted body joins nothing."""
        for command, bodies in (
                ("cat <<EOF\nE\\\nOF\nls", ["E\\\nOF\n"]),
                ("cat <<EOF\nEOF\\\n\nls", ["EOF\\\n\n"]),
                ("cat <<EOF\nE\\\nO\\\nF\nls", ["E\\\nO\\\nF\n"]),
                ("cat <<EOF\na\\\nEOF\nEOF\nls", ["a\\\nEOF\nEOF\n"]),
                ("cat <<EOF\na\\\\\nEOF\nls", ["a\\\\\nEOF\n"]),
                ("cat <<EOF\na\\\\\\\nEOF\nEOF\nls", ["a\\\\\\\nEOF\nEOF\n"]),
                ("cat <<-EOF\n\tE\\\nOF\nls", ["\tE\\\nOF\n"]),
                ("cat <<-EOF\nE\\\n\tOF\nEOF\nls", ["E\\\n\tOF\nEOF\n"]),
                ("cat <<'EOF'\nE\\\nOF\nEOF\nls", ["E\\\nOF\nEOF\n"]),
                ("x=\"$(cat <<EOF\nE\\\nOF)\"\nls", ["E\\\nOF"])):
            with self.subTest(command=command):
                self.assertEqual(body_texts(command), bodies)
        self.assertTrue(guard.continues("a\\") and guard.continues("a\\\\\\"))
        self.assertFalse(guard.continues("a") or guard.continues("a\\\\"))

    def test_a_double_parenthesis_is_arithmetic_only_where_bash_reads_it_so(self):
        """bash reads (( as arithmetic where the ) that closes its second (
        is followed at once by another, and else as a subshell in a
        subshell, whose here-documents are read as any other; so is $((."""
        for command in ("((1 << 2))\nIt's", "(( (1+2) << 3 ))\nIt's", "echo $(( (1) << 2 ))\nIt's",
                        "echo \"$((1<<2))\"\nIt's"):
            with self.subTest(command=command):
                self.assertEqual(guard.here_document_bodies(command), [])
        for command, bodies in (("((cd /tmp); cat <<'EOF'\nIt's\nEOF\n)", ["It's\nEOF\n"]),
                                ("((cd /tmp) && cat <<'EOF'\nIt's\nEOF\n)", ["It's\nEOF\n"]),
                                ("x=$((cd /tmp); cat <<'EOF'\nIt's\nEOF\n)", ["It's\nEOF\n"]),
                                ("(( 1 ) ); cat <<'EOF'\nIt's\nEOF", ["It's\nEOF"]),
                                ("((cd /tmp; cat <<'EOF'\nIt's\nEOF", ["It's\nEOF"])):
            with self.subTest(command=command):
                self.assertEqual(body_texts(command), bodies)
        self.assertEqual([body.runs for body in guard.here_document_bodies(
            "cat <<EOF\n$((git push origin main); true) $((1+2))\nEOF")], [("$((git push origin main); true)",)])
        self.assertEqual(guard.arithmetic_end("((1))", 2), 5)
        self.assertIsNone(guard.arithmetic_end("((a) )", 2))
        self.assertIsNone(guard.arithmetic_end("((a", 2))

    def test_a_body_whose_substitution_closes_on_its_line_starts_after_it(self):
        """bash reads the body of a here-document whose substitution, or the
        double quotes around it, closes on the operator's own line from the
        next newline it reads outside them, with a warning; until the fix of
        F25's second review the guard waited for a newline inside the
        substitution, told no body, and passed the push between two such
        bodies."""
        for command, bodies in (("x=$(cat <<'EOF')\nDon't\nEOF\nls", ["Don't\nEOF\n"]),
                                ("x=\"$(cat <<'EOF')\"\nDon't\nEOF\nls", ["Don't\nEOF\n"]),
                                ("x=$(cat <<'EOF'; echo a)\nDon't\nEOF\nls", ["Don't\nEOF\n"]),
                                ("x=$( (cat <<'EOF') )\nDon't\nEOF\nls", ["Don't\nEOF\n"]),
                                ("cat <<A $(cat <<B)\na\nA\nb\nB\nls", ["a\nA\n", "b\nB\n"]),
                                ("x=\"$(cat <<'A')\nbody\nA\n\"\nls", ["body\nA\n"])):
            with self.subTest(command=command):
                self.assertEqual(body_texts(command), bodies)
        for command in ("x=$(cat <<'EOF')\nDon't\nEOF\ngit push origin main\ny=$(cat <<'EOF')\nIt's\nEOF",
                        "x=\"$(cat <<'EOF')\"\nDon't\nEOF\ngit push origin main\ny=\"$(cat <<'EOF')\"\nIt's\nEOF",
                        "x=$(cat <<'EOF'; echo a)\nDon't\nEOF\ngit push origin main\ny=$(cat <<'EOF')\nIt's\nEOF"):
            with self.subTest(command=command):
                self.assertEqual(self.run_guard(command), (2, MAIN))
                with mock.patch.object(guard, "leave", lambda pending, before, after: None):
                    self.assertEqual(self.run_guard(command), (0, ""), "as built until the fix")

    def test_a_substitution_in_an_expanded_body_loses_its_own_bodies(self):
        """What the shell runs of a body it expands is read with the bodies
        of its own here-documents cut out in turn, since their quotes are
        text too; until the fix of F25's second review their apostrophes
        were kept, and one paired with an apostrophe after the push."""
        self.assertEqual([body.runs for body in guard.here_document_bodies(
            "cat <<EOF\n$(cat <<'X'\nDon't\nX\n) and $(cat <<X\n$(git push origin main) it's\nX\n)\nEOF")],
            [("$(cat <<'X'\n)", "$(cat <<X\n$(git push origin main)\n)")])
        command = "cat <<EOF\n$(cat <<'X'\nDon't\nX\n)\nEOF\ngit push origin main\ncat <<'EOF'\nIt's\nEOF"
        self.assertEqual(guard.readings(command)[1],
                         "cat <<EOF ; git push origin main ; cat <<'EOF' ;  ; ( cat <<'X' ;  ) ")
        self.assertEqual(self.run_guard(command), (2, MAIN))

    def test_bodies_nested_deeper_than_the_guard_reads_are_refused_unread(self):
        """Each here-document in a substitution of a body the shell expands
        is read again inside the one around it, so the depth is bounded: a
        command nested deeper is refused, never passed, and one at the
        bound is read."""
        def nested(depth):
            return "cat <<EOF\n" + "$(cat <<EOF\n" * depth + "x\n"

        guard.here_document_bodies(nested(guard.MAX_NESTING))
        with self.assertRaises(guard.TooDeep):
            guard.here_document_bodies(nested(guard.MAX_NESTING + 1))
        self.assertEqual(self.run_guard(nested(guard.MAX_NESTING + 1) + "git push -u origin claude/7"),
                         (2, TOO_DEEP))
        self.assertEqual(self.run_guard(nested(guard.MAX_NESTING) + "git push -u origin claude/7"), (0, ""))
        self.assertEqual(self.run_guard(nested(guard.MAX_NESTING + 1).replace("$(", "")), (0, ""),
                         "no push, no reading")
        self.assertEqual(self.run_guard(nested(guard.MAX_NESTING + 1)), (2, TOO_DEEP),
                         "F29: a substitution may build a push, so the command is read, and refused unread")

    def test_a_case_patterns_parenthesis_closes_no_substitution(self):
        """bash reads a case command inside a substitution so that a
        pattern's ) closes nothing; until the fix of F25's second review
        the guard closed the substitution there, read the << after it as
        text inside double quotes and told no body."""
        for command, bodies in (
                ("x=\"$(case a in a) cat <<'EOF'\nSay \"hi\nEOF\n;; esac)\"\nls", ["Say \"hi\nEOF\n"]),
                ("x=\"$(case a in (a|b) cat <<'EOF'\nhi\nEOF\n;& c) echo;; esac)\"\nls", ["hi\nEOF\n"]),
                ("x=\"$(case a in b) ;; a) cat <<'EOF'\nhi\nEOF\n;;& *) ;; esac)\"\nls", ["hi\nEOF\n"]),
                ("x=\"$(case $(echo a) in \"a\") cat <<'EOF'\nhi\nEOF\nesac)\"\nls", ["hi\nEOF\n"]),
                ("x=\"$(if true; then case a in a) cat <<'EOF'\nhi\nEOF\n;; esac; fi)\"\nls", ["hi\nEOF\n"]),
                ("x=\"$(case a in\na) (cat <<'EOF'\nhi\nEOF\n) ;;\nesac)\"\nls", ["hi\nEOF\n"]),
                ("x=\"$(echo case a; cat <<'EOF'\nhi\nEOF\n)\"\nls", ["hi\nEOF\n"])):
            with self.subTest(command=command):
                self.assertEqual(body_texts(command), bodies)
        command = ("x=\"$(case a in a) cat <<'EOF'\nSay \"hi\nEOF\n;; esac)\"\ngit push origin main\n"
                   "y=\"$(case a in a) cat <<'EOF'\nSay \"bye\nEOF\n;; esac)\"")
        self.assertEqual(self.run_guard(command), (2, MAIN))
        with mock.patch.object(guard, "case_step", lambda *step: None):
            self.assertEqual(self.run_guard(command), (0, ""), "as built until the fix")

    def test_arithmetic_counts_its_parentheses_past_quotes(self):
        """bash counts the parentheses of (( past quotes and backslash
        pairs, so ((echo "))"); ...) is a subshell in a subshell whose
        bodies it reads; until the fix of F25's second review the guard
        counted the quoted ones and read it as arithmetic."""
        self.assertIsNone(guard.arithmetic_end("((echo \"))\"); x", 2))
        self.assertIsNone(guard.arithmetic_end("((echo ')'); x", 2))
        self.assertIsNone(guard.arithmetic_end("((echo \\)); x", 2))
        self.assertEqual(guard.arithmetic_end("(( a == ')' ))", 2), 14)
        self.assertIsNone(guard.arithmetic_end("((a \"b))", 2), "a quote that never closes closes nothing")
        command = "((echo \"))\"); cat <<'EOF'\nDon't\nEOF\n)\ngit push origin main\ncat <<'EOF'\nIt's\nEOF"
        self.assertEqual(body_texts(command), ["Don't\nEOF\n", "It's\nEOF"])
        self.assertEqual(self.run_guard(command), (2, MAIN))

    def test_a_parameter_expansion_and_a_backquoted_span_close_no_substitution(self):
        """bash reads ${...} and `...` whole, as parse_matched_pair does, so
        a ) inside one closes no substitution around it; until the fix of
        F25's third review the guard closed the substitution there, read
        the << after it as text inside double quotes and told no body, as
        on main before F25's fix."""
        for inner in ("${y:-)}", "${y#)}", "${y//)/b}", "`case a in a) :;; esac`", '${y:-"}"}', "${y:-')'}",
                      "${y:-$(echo ))}", '"`echo "a"`"', "${y:-`echo )`}"):
            command = f'x="$(echo {inner} ; cat <<EOF\nsay "hi\nEOF\n)"\ngit push origin main # "'
            with self.subTest(inner=inner):
                self.assertEqual(body_texts(command), ['say "hi\nEOF\n'])
                self.assertEqual(self.run_guard(command), (2, MAIN))
        self.assertEqual(body_texts("echo ${x:-<<EOF}\nls"), [], "a << inside ${ } is text")
        self.assertEqual(body_texts("cat <<EOF ${x:-\n}\nIt's\nEOF\nls"), ["It's\nEOF\n"],
                         "a newline inside ${ } starts no body")
        self.assertEqual(body_texts("cat <<EOF `echo\n`\nIt's\nEOF\nls"), ["It's\nEOF\n"],
                         "nor one inside backquotes")
        self.assertIsNone(guard.arithmetic_end("((echo ${x:-)}); x", 2))
        self.assertIsNone(guard.arithmetic_end("((echo `echo )`); x", 2))
        self.assertEqual(guard.arithmetic_end("(( ${x:-)} + $(echo 1) ))", 2), 25)
        command = 'x="$(echo ${y:-)} ; cat <<EOF\nsay "hi\nEOF\n)"\ngit push origin main # "'
        step = guard.expansion_step

        def braces_as_text(command, i, *rest):
            return None if command.startswith("${", i) else step(command, i, *rest)

        with mock.patch.object(guard, "expansion_step", braces_as_text), unsubstituted():
            self.assertEqual(self.run_guard(command), (0, ""), "as built until the fix")
        with mock.patch.object(guard, "backquoted", lambda command, i, depth: None), unsubstituted():
            self.assertEqual(self.run_guard(command.replace("${y:-)}", "`case a in a) :;; esac`")), (0, ""),
                             "as built until the fix")

    def test_a_backquoted_span_holds_its_own_here_documents(self):
        """bash reads a backquoted span to its closing ` and then its text
        as a command, so a here-document opened inside one has its body
        inside it, told as any other; reading the span as text alone, as
        the fix of F25's third review first did, told none, and the body's
        apostrophe paired with one after the push."""
        command = "x=`cat <<EOF\nit's\nEOF\n`\ngit push origin main # '"
        self.assertEqual(body_texts(command), ["it's\nEOF\n"])
        self.assertEqual(self.run_guard(command), (2, MAIN))
        self.assertEqual(body_texts('echo "`cat <<\'X\'\nDon\'t\nX\n`" `echo`'), ["Don't\nX\n"])

    def test_pid_and_old_arithmetic_are_read_as_bash_reads_them(self):
        """$$, the shell's process id, is a parameter whole, so the { after
        it opens nothing, and old-style arithmetic, $[ ], is read to its ],
        a ) inside it closing nothing and a ${ inside it read as text, as
        bash's parse_matched_pair reads them; until the fix of F25's fourth
        review $${ opened a parameter expansion and $[ ) ] closed the
        substitution around it, and the push after each passed."""
        for command in ("echo $${ ; cat <<EOF\nsay 'hi\nEOF\ngit push origin main # '",
                        "echo \"$${\" ; cat <<EOF\nsay 'hi\nEOF\ngit push origin main # '",
                        "echo $$$${ ; cat <<EOF\nsay 'hi\nEOF\ngit push origin main # '",
                        "echo $(($${)) ; cat <<EOF\nsay 'hi\nEOF\ngit push origin main # '",
                        'x="$(echo $[ ) ] ; cat <<EOF\nsay "hi\nEOF\n)"\ngit push origin main # "',
                        'x="$(echo $[ [ ) ] ] ; cat <<EOF\nsay "hi\nEOF\n)"\ngit push origin main # "',
                        'x="$(echo $[ \']\' ) ] ; cat <<EOF\nsay "hi\nEOF\n)"\ngit push origin main # "'):
            with self.subTest(command=command):
                self.assertEqual(len(body_texts(command)), 1)
                self.assertEqual(self.run_guard(command), (2, MAIN))
        self.assertEqual(body_texts("echo $[ 1 ${x:-]} ]; cat <<EOF\nIt's\nEOF\nls"), ["It's\nEOF\n"],
                         "bash reads no ${ inside $[ ], so its ] closes")
        self.assertEqual(guard.arithmetic_end("(( $${ ))", 2), 9)
        self.assertIsNone(guard.arithmetic_end("((echo $[ ) ]); x", 2))
        step = guard.expansion_step
        for kind, command in (("$$", "echo $${ ; cat <<EOF\nsay 'hi\nEOF\ngit push origin main # '"),
                              ("$[", 'x="$(echo $[ ) ] ; cat <<EOF\nsay "hi\nEOF\n)"\ngit push origin main # "')):
            def as_text(text, i, *rest, kind=kind):
                return None if text.startswith(kind, i) else step(text, i, *rest)

            with self.subTest(kind=kind), mock.patch.object(guard, "expansion_step", as_text):
                self.assertEqual(self.run_guard(command), (0, ""), "as built until the fix")

    def test_a_backquoted_span_is_read_whole_and_as_commands(self):
        """bash reads a backquoted span whole, so a quote inside it pairs
        with nothing outside, and runs its text: a lenient reading hands
        shlex the span as one part of its word and reads its text after the
        rest as the commands of a subshell, in the command, in double
        quotes and in a body the shell expands; until the fix of F25's
        fourth review a quote inside one paired across the push after it,
        and a push inside one passed."""
        for command in ('x=`echo "`; git push origin main # "', "echo `echo '`\ngit push origin main\necho '",
                        "echo `git push origin main`", 'echo "`git push origin main`"',
                        "cat <<EOF\nit's `git push origin main`\nEOF\necho '",
                        "x=`cat <<EOF\nit's $(git push origin main)\nEOF\n` # '"):
            with self.subTest(command=command):
                self.assertEqual(self.run_guard(command), (2, MAIN))
        self.assertEqual(guard.plain_text("git -C `pwd` push", lenient=True), "git -C '`pwd`' push ; ( pwd ) ")
        self.assertEqual(guard.plain_text("git -C `pwd` push"), "git -C `pwd` push", "strict: as before")
        with mock.patch.object(guard, "backquoted_span", lambda command, i: None), unsubstituted():
            self.assertEqual(self.run_guard('x=`echo "`; git push origin main # "'), (0, ""), "as built until the fix")

    def test_a_backquote_in_a_substitution_in_double_quotes_is_left_to_it(self):
        """A backquoted span in double quotes runs, but one in a $( ) in
        double quotes is that substitution's text, in single quotes or in a
        quoted here-document's body there, which bash never runs: until the
        fix of F25's fifth review a commit message or a pull request's body
        that names a command in Markdown was refused. Single quotes in
        double quotes are text, so a span between them still runs."""
        tick = "`"
        named = "$(cat <<'EOF'\nSee the " + tick + "git push --force" + tick + " refusal.\nEOF\n)"
        for command in ('git commit -m "' + named + '" && git push origin claude/7',
                        'gh pr create --title T --body "' + named + '" && git push origin claude/7',
                        'git commit -m "$(echo \'see ' + tick + 'git push --force' + tick + '\')" && git push origin claude/7'):
            with self.subTest(command=command):
                self.assertEqual(self.run_guard(command), (0, ""))
        self.assertEqual(self.run_guard('echo "\'' + tick + 'git push origin main' + tick + '\'"'), (2, MAIN))

    def test_the_repository_s_own_texts_as_messages_are_not_refused(self):
        """Every paragraph and every file the guard reads whole of this
        repository's own prose and code, written as a commit message in a quoted here-document in a
        substitution, the shape a session commits in, holds no push bash
        would run, so the guard refuses none of them (F25's fifth review
        found such messages refused that 0.5.0 passes)."""
        texts = []
        for pattern in ("*.md", "spec/**/*.md", "validation/**/*.md", "scripts/*.py", "sdlc_protocol/*.py"):
            for path in sorted(ROOT.glob(pattern)):
                text = path.read_text(encoding="utf-8")
                texts += [text, *text.split("\n\n")]
        def message(text):
            return "git commit -m \"$(cat <<'EOF'\n" + text + "\nEOF\n)\" && git push origin claude/7"

        def body(text):
            return ("gh pr create --title T --body \"$(cat <<'EOF'\n" + text + "\nEOF\n)\" && "
                    "git push origin claude/7")

        def printed(text):
            return "git commit -m \"$(printf '%s\\n' '" + text.replace("'", "'\\''") + "')\" && git push origin claude/7"

        commands = [form(text) for text in texts for form in (message, body, printed)
                    if "\nEOF\n" not in "\n" + text + "\n" and text.strip() and len(form(text)) <= guard.MAX_COMMAND]
        self.assertGreater(len(commands), 1500)
        refused = [command[:80] for command in commands if guard.refused_push(
            command, "/w", lambda place: ("claude/7", "main"), lambda place: None, lambda place: True)]
        self.assertEqual(refused, [])

    def test_a_comment_in_arithmetic_counts_its_parentheses_as_bash_does(self):
        """bash's parse_matched_pair counts the parentheses after a # as it
        tells arithmetic from a subshell: it reads ((echo a #(, a newline
        and ))) as arithmetic, and (( 1 #(, a newline and )) as a subshell
        in a subshell, so the guard counts them too, where the scan, once
        it reads a subshell, skips the comment as bash's parser does."""
        self.assertEqual(guard.arithmetic_end("((echo a #(\n)))", 2), 15)
        self.assertIsNone(guard.arithmetic_end("(( 1 #(\n))", 2))

    def test_the_reading_takes_time_in_proportion_to_the_command(self):
        """A hook that runs out of time passes the command, so no long
        command may take the reading long: until the fix of F25's second
        review an unmatched (( or $(( was counted to the end of the text
        once for each, 55 seconds for the first of these; each now takes
        well under the bound, generous for a slow runner: two seconds, and
        three for a command at the longest the guard reads, which since
        F24's fix it reads once more for its substitutions."""
        push = "\ngit push origin main"
        for command in ("cat <<A\nA\n" + "(( " * 16000, "cat <<EOF\n" + "$((" * 8000,
                        "cat <<A\nA\necho \"" + "$((" * 16000, "cat <<A\nA\n" + "\"$( " * 16000,
                        "cat <<EOF\n" + "a\\\n" * 20000, "x=$(" + "case a in a) " * 4000,
                        "cat <<EOF\n" + "$(cat <<EOF\n" * guard.MAX_NESTING + "x'y\n" * 16000,
                        "cat " + "<<A " * 8000 + "\n" + "A\n" * 8000, "((\"((" * 20000,
                        self.at_full_size("cat <<EOF\n", "$( (( #((((\n)))\n", "EOF"),
                        self.at_full_size("x=\"$(", "${y:-)} `)` ", ""), self.at_full_size("", "${" * 2 + "$(", ""),
                        "((<<X${<<'X';" * 8000, "cat <<A\nA\n" + "`" * 100000, "cat <<A\nA\n" + "$[ [" * 25000,
                        "`x` " * 25000):
            with self.subTest(command=command[:40]):
                started = time.monotonic()
                self.assertEqual(self.run_guard(command + push)[0], 2)
                bound = 3.0 if len(command + push) > guard.MAX_COMMAND - 64 else 2.0
                self.assertLess(time.monotonic() - started, bound)

    def test_a_count_in_a_text_of_open_substitutions_takes_time_in_proportion(self):
        """The count from each (( of }<<'X'${y:-(( units, whose (( stand in
        a ${ for the count from any of them, ran to the end of the text
        (F25's fifth review: 32 KB took 4.1 seconds and 64 KB ran out of
        time); a count now stops at the first ${ or $[ from which an earlier
        count fell no lower than its own parentheses reach."""
        for unit in ("}<<'X'${y:-((", "}<<'X'$[y(((", "${y:-(( } ((", "$[ (( ] (("):
            with self.subTest(unit=unit):
                command = self.at_full_size("", unit, "")
                started = time.monotonic()
                self.assertEqual(self.run_guard(command + "\ngit push origin main")[0], 2)
                self.assertLess(time.monotonic() - started, 3.0)

    @staticmethod
    def at_full_size(head, unit, tail):
        """head, as many units as fit and tail: a command as long as the
        guard reads once the timing test adds its push line."""
        room = guard.MAX_COMMAND - len(head) - len(tail) - len("\ngit push origin main")
        return head + unit * (room // len(unit)) + tail

    def test_a_long_run_of_moves_takes_time_in_proportion_to_it(self):
        """cd and pushd joined ever longer paths, and pushd stacked onto
        ever longer tuples, a time in the square of the run (F25's third
        review: 29,000 of "pushd a;" took 68 seconds and 43,000 of "cd a;"
        16), where a hook that runs out of time passes the command: a path
        too long for the system is one the guard cannot tell, and a stack
        is one object per entry."""
        self.assertIsNone(guard.joined("/w", "a/" * 2048), "longer than the system takes")
        self.assertIsNone(guard.joined("/w", "\u00e9" * 2047), "counted in bytes")
        self.assertEqual(guard.joined("/w", "a/" * 2045), "/w/" + "a/" * 2044 + "a")
        self.assertIs(guard.stacked(guard.stacked((), "/a"), "/b"), guard.stacked(guard.stacked((), "/a"), "/b"))
        self.assertEqual(push_places("pushd /a; pushd /b; popd; git push origin main; popd; git push origin main"),
                         ["/a", "/w/s"])
        push = "git push origin main"
        for unit in ("pushd a;", "cd a;", "pushd a; popd;", "pushd -n a;", "pushd a;cd ..;"):
            command = unit * ((guard.MAX_COMMAND - len(push)) // len(unit)) + push
            with self.subTest(unit=unit):
                started = time.monotonic()
                self.assertEqual(guard.refused_push(command, "/w", lambda place: ("claude/7", "main"),
                                                    lambda place: None, lambda place: True), MAIN)
                self.assertLess(time.monotonic() - started, 3.0)

    def test_a_reading_past_its_deadline_is_refused_unread(self):
        """Claude Code reads a hook that runs out of time as no objection,
        so a reading that runs past DEADLINE_SECONDS refuses the command,
        never passes it; the deadline holds only while a command is read."""
        ticks = iter(range(0, 10 ** 6, 4))
        with mock.patch.object(guard, "clock", lambda: next(ticks)):
            self.assertEqual(self.run_guard("cd a; cd b; git push -u origin claude/7"), (2, TOO_SLOW))
        self.assertIsNone(guard.DEADLINE.get())
        ticks = iter(range(0, 10 ** 6))
        asked = []

        def branches_of(place):
            asked.append(place)
            return "claude/7", "main"

        command = "".join(f"git -C /c/{n} push origin x;" for n in range(40)) + "git push origin main"
        with mock.patch.object(guard, "clock", lambda: next(ticks)):
            self.assertEqual(guard.refused_push(command, "/w", branches_of, lambda place: None, lambda place: True),
                             TOO_SLOW, "the deadline holds the judging too, before each clone is asked")
        self.assertLess(len(asked), 40)
        with mock.patch.object(guard, "seconds_left", lambda: 0.5), \
                mock.patch.object(guard.subprocess, "run", side_effect=guard.subprocess.TimeoutExpired("git", 0.5)):
            with self.assertRaises(guard.TooSlow, msg="a git call the deadline cuts short is no answer"):
                guard.git_line(["status"], "/w")
        with mock.patch.object(guard.subprocess, "run", side_effect=guard.subprocess.TimeoutExpired("git", 10)):
            self.assertIsNone(guard.git_line(["status"], "/w"), "outside a run, git's own timeout is no answer")
        with mock.patch.object(guard, "clock", lambda: 0):
            self.assertEqual(self.run_guard("cd a; cd b; git push -u origin claude/7"), (0, ""))
        self.assertEqual(self.run_guard("echo push"), (0, ""), "no push read past the deadline")

    def test_a_command_too_long_to_read_in_time_is_refused_unread(self):
        """shlex builds a word a character at a time, in a time that grows
        with the square of its length, so a command longer than the bound
        is refused at once, never passed, and one at the bound is read."""
        at_bound = "git push -u origin claude/7 " + "a" * (guard.MAX_COMMAND - 28)
        self.assertEqual(len(at_bound), guard.MAX_COMMAND)
        self.assertEqual(self.run_guard(at_bound), (0, ""))
        self.assertEqual(self.run_guard(at_bound + "a"), (2, TOO_LONG))
        self.assertEqual(self.run_guard("echo " + "a" * guard.MAX_COMMAND), (0, ""), "no push, no reading")

    def test_the_command_is_read_whole_and_with_its_bodies_cut_out(self):
        self.assertEqual(guard.readings("git push origin main"), ["git push origin main"])
        self.assertEqual(guard.readings("cat <<'EOF'\nIt's\nEOF\ngit push origin main"),
                         ["cat <<'EOF' ; It\\'s ; EOF ; git push origin main", "cat <<'EOF' ; git push origin main"])

    def test_a_push_beside_here_documents_is_read_whatever_their_bodies_hold(self):
        """Each of these is a shape bash ran the push of, the third the one a
        session writes most: a commit message by here-document, the push,
        then text by another."""
        for command in (
                "cat <<'EOF' > /dev/null\nIt's done\nEOF\ngit push origin main",
                "git commit -F - <<'EOF'\nDon't stop\nEOF\ngit push origin main\ncat <<'EOF'\nIt's done\nEOF",
                "git commit -q -m \"$(cat <<'EOF'\nSay \"hi\nEOF\n)\"\ngit push origin main\n"
                "gh pr create --body \"$(cat <<'EOF'\nQuote\" here\nEOF\n)\"",
                "msg=$(cat <<'EOF'\nIt's\nEOF\n)\ngit push origin main\necho 'x'",
                "cat <<-'EOF'\n\tIt's\n\tEOF\ngit push origin main\necho 'x'",
                "cat <<A <<'B'\nIt's\nA\nfine\nB\ngit push origin main\necho 'x'",
                "x=\"$(cat <<'EOF'\nSay \"hi\nEOF)\"\ngit push origin main\ngh pr create --body \"x\"",
                "cat <<EOF\nIt's $(git push origin main) done, isn't it\nEOF",
                "echo $((1<<2)); cat <<'EOF'\nIt's\nEOF\ngit push origin main\necho 'done'",
                "cat <<EOF\nDon't\nE\\\nOF\ngit push origin main\ncat <<'EOF'\nIt's\nEOF",
                "cat <<EOF\nDon't\nEOF\\\n\ngit push origin main\nEOF\ncat <<'EOF'\nIt's\nEOF",
                "((cd /tmp); cat <<'EOF'\nDon't\nEOF\n)\ngit push origin main\n((cd /tmp); cat <<'EOF'\nIt's\nEOF\n)"):
            with self.subTest(command=command):
                self.assertEqual(self.run_guard(command), (2, MAIN))
                self.assertEqual(self.run_as_before_f25(command), (0, ""), "as built until F25's fix")
        self.assertEqual(self.run_guard("git commit -F - <<'EOF'\nDon't stop\nEOF\ngit push -u origin claude/7\n"
                                        "cat <<'EOF'\nIt's done\nEOF"), (0, ""))

    def test_a_body_misread_hides_nothing_the_whole_reading_shows(self):
        """The second reading only adds pushes: were a body told where there
        is none, every push of the whole command would still be judged."""
        def everything_a_body(command):
            return [guard.Body(0, len(command))]

        with mock.patch.object(guard, "here_document_bodies", everything_a_body):
            self.assertEqual(guard.readings("git push origin main")[1], "")
            self.assertEqual(self.run_guard("git push origin main"), (2, MAIN))

    def test_every_command_reads_and_its_bodies_lie_inside_it_in_order(self):
        draw = random.Random(2025)
        for _ in range(3000):
            command = "".join(draw.choice(PIECES) for _ in range(draw.randint(1, 14)))
            with self.subTest(command=command):
                at = 0
                for body in guard.here_document_bodies(command):
                    self.assertTrue(at <= body.start <= body.end <= len(command))
                    at = body.end
                texts = guard.readings(command)
                self.assertIn(len(texts), (1, 2, 3), "whole, with the bodies cut out, and its own text (F29)")
                for text in texts:
                    lexed(text)


# A push in each place bash runs a substitution's text from, which the
# guard read as part of a word or as a redirection's target until F24's
# fix: in double quotes, in a parameter expansion, in arithmetic, nested in
# another, and in a process substitution.
SUBSTITUTED_PUSHES = (
    'out="$(git push --force origin main 2>&1)"', "cat <(git push --force origin main)",
    "tee >(git push --force origin main) </dev/null", 'echo "$(git push origin main)"',
    'echo "$(echo `git push origin main`)"', 'x="${y:-$(git push origin main)}"',
    'echo "$(( $(git push origin main) ))"', '(( "$(git push origin main)" ))', 'echo "$[ $(git push origin main) ]"',
    '`echo "$(git push origin main)"`', 'echo "$(case a in a) git push origin main;; esac)"',
    "diff <(echo a) <(git push origin main)", 'echo "$(echo ")"; git push origin main)"',
    'echo "$(echo "$(echo "$(git push origin main)")")"', 'echo "${y:-$(echo `git push origin main`)}"',
    'echo "`git push origin \\"main\\"`"', 'echo "$(echo $\'it\\\'s\') $(git push origin main)" # it\'s',
)
# Commands that name a push in a substitution's place where bash runs none:
# in single quotes, after a backslash, in a comment, in a quoted
# here-document's body, as the text of a commit message or a pull
# request's body, and a <( ) in double quotes, which is text there.
SUBSTITUTED_TEXTS = (
    "echo '$(git push origin main)'", 'echo "\\$(git push origin main)"', "echo a # $(git push origin main)",
    'echo "<(git push origin main)"', 'echo "$(echo \\`git push origin main\\`)"',
    "git commit -m \"$(cat <<'EOF'\nRun $(git push --force origin main) and `git push origin main`.\nEOF\n)\"",
    "gh pr create --title T --body \"$(cat <<'EOF'\nSee <(git push origin main) and $(git push origin main)\nEOF\n)\"",
    "git commit -m \"$(printf '%s\\n' 'Run git push --force origin main' '$(git push origin main)')\"",
    "gh pr create --body \"$(printf '%s' \"$(echo '$(git push origin main)')\")\"",
    'x="$(cat <<\'EOF\'\n$(git push origin main)\nEOF\n)"',
)


# F24's first review, each finding's pushes, which bash 5.2 runs, by the
# finding's number: a single quote in a double-quoted ${ } after an operator
# such as :-, which pairs but quotes nothing (1); a $'...' in a ${ } outside
# double quotes (2); a single quote in arithmetic (3); arithmetic on a line
# of an expanded body (4); a $'...' before a here-document, which the scan
# of here-documents read as a quote closed early (5); and what the review's
# fuzz found besides: a here-document a backquoted span's backslashes hid,
# and two substitutions whose own texts read alike.
REVIEWED_PUSHES = {
    1: ("echo \"${v:-'`git push origin main`'}\"", "echo \"${v:-'$(git push origin main)'}\"",
        "echo \"${v:-${w:-'$(git push origin main)'}}\"", "echo \"${v:-'}'$(git push origin main)}\"",
        "x=\"${v:='$(git push origin main)'}\""),
    2: (": ${v:-$'a\\'b'} `git push origin main`", "echo ${v:-$'\\''} \"$(git push origin main)\""),
    3: ("echo $(( '$(git push origin main)' ))", "echo $[ '$(git push origin main)' ]",
        "echo \"$(( '$(git push origin main)' ))\"", "echo \"$[ '$(git push origin main)' ]\"",
        "(( '$(git push origin main)' ))", "echo $(( 1 + '`git push origin main`' ))"),
    4: ("cat <<EOF\necho \"$(( $(git push origin main) ))\"\nEOF",
        "cat <<-EOF\n\techo \"$(( $(git push origin main) ))\"\n\tEOF"),
    5: ("echo $'\\'' \"$(cat <<'E'\n\"\nE\ngit push origin main)\"",
        "echo $'it\\'s' \"$(cat <<'E'\n\"\nE\ngit push origin main)\""),
    6: ("echo `echo \"\\$(cat <<'E'\n\"\nE\ngit push origin main)\"`",
        "echo \"$(echo $(true))\" \"$(echo $(git push origin main))\"",
        "while false; do :; done; echo `echo $(cat <<E\nhi\nE\ngit push origin main)`",
        "x=`\\$(cat <<'E'\n)'\nE\ngit push origin main)`"),
}
# Where bash runs none of those pushes: a single quote quotes inside a
# double-quoted ${ } after an operator that removes or replaces a pattern,
# and anywhere in a ${ } outside double quotes; a quoted body's arithmetic
# is text; and a $'...' in double quotes is no ANSI-C quoting.
REVIEWED_TEXTS = (
    "echo \"${v#'$(git push origin main)'}\"", "echo \"${v%'$(git push origin main)'}\"",
    "echo \"${v/'$(git push origin main)'/x}\"", "echo \"${v/a/'$(git push origin main)'}\"",
    "echo ${v:-'$(git push origin main)'}", "echo ${v:-'`git push origin main`'}",
    "cat <<'EOF'\necho \"$(( $(git push origin main) ))\"\nEOF",
    "echo \"$'\" '$(git push origin main)'", "echo \"${v:-'it'}\" \"${v:-it}\"",
)


class SubstitutionTest(unittest.TestCase):
    """What the shell runs of a command's substitutions (F24): bash runs
    the text of a $( ), a backquoted span, a <( ) and a >( ) as commands
    wherever it expands one, in double quotes too, so the guard reads each
    apart as the commands of a subshell (guard.substituted), where until
    the fix a substitution in double quotes was one word and a <( ) a
    redirection. bash 5.2 ran each push these tests say it runs."""

    def run_guard(self, command):
        payload = {"tool_input": {"command": command}, "cwd": str(ROOT)}
        with mock.patch.object(guard, "branches", return_value=("claude/7", "main")):
            return guard.run(payload, str(ROOT))

    def test_a_push_in_a_substitution_is_refused_wherever_bash_runs_it(self):
        for command in SUBSTITUTED_PUSHES:
            with self.subTest(command=command):
                self.assertEqual(self.run_guard(command)[0], 2)
                with unsubstituted():
                    self.assertEqual(self.run_guard(command), (0, ""), "with no substitution read apart")
        self.assertEqual(self.run_guard('out="$(git push -u origin claude/7 2>&1)"'), (0, ""))

    def test_a_push_named_where_bash_runs_no_substitution_passes(self):
        """The quoted bodies of a commit message or a pull request's body
        stay text, as F25's fix made them, however their pushes are
        written; so do single quotes, a backslash and a comment."""
        for command in SUBSTITUTED_TEXTS:
            with self.subTest(command=command):
                self.assertEqual(self.run_guard(command + " && git push origin claude/7"), (0, ""))

    def test_what_f24_s_first_review_found_is_refused(self):
        """Each push F24's first review found passing while bash ran it is
        refused, and what bash runs no push of beside it passes."""
        for finding, commands in REVIEWED_PUSHES.items():
            for command in commands:
                with self.subTest(finding=finding, command=command):
                    self.assertEqual(self.run_guard(command), (2, MAIN))
        for command in REVIEWED_TEXTS:
            with self.subTest(command=command):
                self.assertEqual(self.run_guard(command + " && git push origin claude/7"), (0, ""))

    def test_a_substitution_in_env_s_string_runs_where_the_shell_expands_it(self):
        """F24's reading meets F28's: bash expands a substitution in a
        double-quoted -S string before env runs, so its push runs, while in
        single quotes env is handed the text and runs no substitution."""
        for command in ('env -S "echo $(git push origin main)"', 'env -S "echo `git push origin main`"',
                        'env -S "${NOPE} echo $(git push origin main)"'):
            with self.subTest(command=command):
                self.assertEqual(self.run_guard(command), (2, MAIN))
        for command in ("env -S 'echo $(git push origin main)'", "x=\"$(env -S 'echo $(git push origin main)')\""):
            with self.subTest(command=command):
                self.assertEqual(self.run_guard(command), (0, ""))

    def test_a_single_quote_in_a_double_quoted_brace_quotes_by_its_operator(self):
        """bash's parse_matched_pair keeps a state through a ${ }: after a
        pattern's operator a single quote quotes, after any other it pairs
        with the next and quotes nothing inside double quotes."""
        for text, quotes in (("${v:-'", False), ("${v#'", True), ("${v%%'", True), ("${v/'", True),
                             ("${v^'", True), ("${#v'", False), ("${v-'", False), ("${v:+'", False),
                             ("${v:-a#'", False)):
            with self.subTest(text=text):
                contexts = guard.Context("${", guard.Context('"'), 2)
                self.assertTrue(contexts.quoted)
                self.assertEqual(guard.brace_state(text, len(text) - 1, contexts) == "quote", quotes)
        self.assertFalse(guard.Context("${", None, 2).quoted, "outside double quotes a single quote quotes")
        self.assertTrue(guard.Context("${", guard.Context("'", guard.Context("${", guard.Context('"'))), 2).quoted)

    def test_arithmetic_is_read_apart_to_its_closing_parentheses(self):
        self.assertEqual(guard.substituted("echo $(( '$(git push)' + 1 ))"),
                         " ; (  'HOLE' + 1  ; ( git push )  ) ".replace("HOLE", guard.SUBSTITUTED))
        self.assertEqual(guard.substituted("(( x = $(a) ))"), " ; (  x = HOLE  ; ( a )  ) ".replace("HOLE", guard.SUBSTITUTED))
        self.assertEqual([body.runs for body in guard.here_document_bodies("cat <<E\n$(( $(a) )) $((1))\nE")],
                         [("$(( $(a) ))",)], "a body's arithmetic is kept where a substitution stands in it")

    def test_substitutions_that_read_alike_are_read_once(self):
        """Each substitution is read in a subshell of its own where the
        shell stands after the text around it, so two that read alike, with
        those nested in them alike too, are judged alike and read once."""
        self.assertEqual(guard.substituted("$(a) $(a) `a` $(b) $(a)"), " ; ( a )  ; ( b ) ")
        self.assertEqual(guard.substituted("$(c $(a)) $(c $(b))"),
                         " ; ( c HOLE ; ( a )  )  ; ( c HOLE ; ( b )  ) ".replace("HOLE", guard.SUBSTITUTED))
        self.assertEqual(guard.substituted('"$("$(a)")"'), " ; ( a ) ", "a text with no word reads its nested")

    def test_each_substitution_is_read_apart_after_the_command(self):
        self.assertEqual(guard.substituted('a "$(b "$(c)" `d`)" <(e) x'),
                         " ; ( b \"HOLE\" HOLE ; ( c )  ; ( d )  )  ; ( e ) ".replace("HOLE", guard.SUBSTITUTED))
        self.assertEqual(guard.substituted("echo a 'b' \"c\""), "")
        self.assertEqual(guard.substituted('"$($(git push))"'), " ; ( git push ) ", "nothing of its own")
        self.assertEqual(guard.substituted("`echo \\`git push\\``"),
                         " ; ( echo HOLE ; ( git push )  ) ".replace("HOLE", guard.SUBSTITUTED),
                         "a backslash nests a backquoted span in another")
        self.assertEqual(guard.readings('echo "$(git push origin main)"'),
                         ['echo "$(git push origin main)" ; ( git push origin main ) ', f'echo "{guard.SUBSTITUTED}"'],
                         "and its own text, the substitution a hole in its word (F29)")

    def test_a_push_in_a_substitution_is_judged_where_its_shell_stands(self):
        """A substitution runs in a subshell of the shell around it, so a cd
        before it holds for it and a cd inside it holds for what follows
        inside it alone."""
        self.assertEqual(push_places('cd /a && x="$(cd /b; git push origin HEAD)" && echo "$(git push origin HEAD)"'),
                         ["/b", "/a"])
        self.assertEqual(push_places('x="$(git -C /c push origin HEAD)"'), ["/c"])

    def test_the_reading_of_substitutions_takes_time_in_proportion_to_the_command(self):
        """Substitutions nested deep or many in a row, each in double
        quotes, a parameter expansion, arithmetic or a backquoted span, at
        the longest command the guard reads: each well under the bound,
        here-documents full of substitutions and single quotes where they
        quote nothing among them (F24's first review: a body of 52,000 $(a)
        in a substitution took 3.4 to 4 seconds, and echo "$(( repeated 2.4)."""
        full = ReadingTest.at_full_size
        for command in (full("", '"$(', ""), full("", "$(", ""), full("", "<(", ""), full("", ">( ", ""),
                        full("", '"$(x)" ', ""), full('echo "', "`x`", '"'), full('echo "', "$((", ""),
                        full("", "(( ", ""), full("", "$(echo ", ""), full("", "`\\`", ""), full("", '"$(a; ', ""),
                        full("", "$(()", ""), full("", 'x="$(echo `a` <(b) ${c:-$(d)}) " ; ', ""),
                        full("git commit -m \"$(cat <<'EOF'\n", "it's $(x) `y` \"z\n", "EOF\n)\""),
                        full("cat <<EOF\n", "it's $(x \"$(y)\") `z`\n", "EOF"),
                        full("", "$(echo $'\\'' ", ""), full('echo "$(', "$'a\\'b' ", ""),
                        full('x="$(cat <<E\n', "$(a)\n", 'E\n)"'), full('x="$(cat <<E\n', "$(a) ", '\nE\n)"'),
                        full("cat <<E\n", "$(a)$(b) ", "\nE"), full('echo "', "${v:-'", ""), full("", "$[ '", ""),
                        full("", "$(( '$(a)' )) ", ""), full("", "\"${v:-'$(a)'}\" ", ""),
                        full("", "${v:-$'\\''} `a` ", ""), full("cat <<E\n", "$(( $(a) )) ", "\nE")):
            with self.subTest(command=command[:40]):
                started = time.monotonic()
                self.assertEqual(self.run_guard(command + "\ngit push origin main")[0], 2)
                self.assertLess(time.monotonic() - started, 3.0)


# F29: the words bash builds, each with a push bash 5.2 runs, through a git
# that records its arguments and runs nothing: ANSI-C and locale quoting, a
# substitution inside a word or whole as git or its verb, an expansion bash
# makes nothing of as a command word, braces, an option or a branch name a
# substitution builds, a # that a line continuation leaves at a word's
# start, a here-document's substitution inside arithmetic, and a
# here-document whose delimiter word holds a substitution or a $'...',
# bodies with apostrophes around the push.
BUILT_PUSHES = (
    "git push origin $'main'", "git push origin $'ma\\x69n'", "env -S $'git push origin main'",
    "git $'push' origin main", "git push -$'f' origin claude/7", "git $'pu\\x73h' origin main",
    "git push origin $'\\u006dain'", "git push origin $'m\\141in'", "git push origin $'main\\x00x'",
    'git $"push" origin main', 'git push origin $"main"', 'git pu$(true)sh origin main', 'git pu``sh origin main',
    'git $(echo push) origin main', 'env -S "git $(echo push) origin main"', 'git push origin ma$(true)in',
    '$(which git) push origin main', '$NOPE git push origin main', '${NOPE:-} git push origin main',
    '$(true) git push origin main', '`true` git push origin main', 'git $NOPE push origin main',
    'env $NOPE git push origin main', 'git ${NOPE:-push} origin main', 'git pu${NOPE}sh origin main',
    'git {push,} origin main', 'git push origin {main,}', 'git push -$(echo f) origin claude/7',
    'git push origin ma$(echo i)n', 'git push origin bo$(echo a)rd:board', 'echo a \\\n# x\ngit push origin main',
    "echo \\\n#'\ngit push origin main\n'", "cat <<E \\\n#'\nhi\nE\ngit push origin main\n'",
    'echo "$(( \'$(echo "$(cat <<\'E\'\n"\nE\ngit push origin main)")\' ))"',
    'echo $(( \'$(echo "$(cat <<\'E\'\n"\nE\ngit push origin main)")\' ))',
    "cat <<E$(echo x)F\nDon't\nE$(echo x)F\ngit push origin main\ncat <<'EOF'\nIt's\nEOF",
    "cat <<E`echo x`F\nDon't\nE`echo x`F\ngit push origin main\ncat <<'EOF'\nIt's\nEOF",
    "cat <<$'E\\x4fF'\nDon't\nEOF\ngit push origin main\ncat <<'EOF'\nIt's\nEOF",
    # F29's first review: a continuation inside a word, coproc, a default
    # with blanks that bash splits, an array's default, a $'...' in a
    # default, and extended patterns.
    "git p\\\nush origin main", "git pu\\\nsh origin main", "coproc git push origin main",
    "coproc X { git push origin main; }", "coproc { git push origin main; }", "${NOPE:-git push origin main}",
    "${NOPE:-git push} origin main", "git ${NOPE:-push origin main}", 'git push origin "${NOPE[@]:-main}"',
    "git push origin ${NOPE[0]:-main}", "git push origin \"${NOPE:-$'\\x6dain'}\"",
    "shopt -s extglob\ntouch main; git push origin @(main)", "shopt -s extglob\ngit push origin @(main|x)",
    "shopt -s extglob\ngit push origin ma?(x)in", "shopt -s extglob\ngit pu@(s)h origin main",
    # F29's second review: a default's own text beside a hole, a word that
    # may open with a - it builds, a pattern a file named +main or : fills,
    # and a colon beside one hole.
    "git push origin ${A:-ma}$(echo in)", "git push origin ${A:-b}$(echo oard)", "git push origin $(echo ma)${A:-in}",
    "git push origin HEAD:${A:-ma}$(echo in)", "git push origin ${A:-:}$(echo main)",
    "git push ${A:--}$(echo f) origin claude/7", "git push ${A:---for}$(echo ce) origin claude/7",
    "B=main; git push origin ${A:-+}$B", 'B=main; git push origin "${A:-+}$B"', "B=main; git push origin ${A:-:}$B",
    "git push origin ${A=ma}$(echo in)", "git push origin ${A:=ma}$(echo in)", "git push origin ${A-ma}$(echo in)",
    "A=x; git push origin ${A:+ma}$(echo in)", "A=x; git push origin ${A+ma}$(echo in)",
    "git push origin ${A:-$'\\x6d'a}$(echo in)", "git push $(echo -)f origin claude/7",
    "touch -- -f; git push * origin claude/7", "touch +main; git push origin ?main",
    "touch +main; git push origin [+]main", "touch : ; git push origin ?", "touch : ; git push origin [:]",
    "git push origin :$X", "git push origin $D:", 'git push origin ":$X"',
)
# What sessions write most that bash runs no forbidden push of: a branch
# or a lease's value by a substitution whole, a commit message in ANSI-C
# quotes or a here-document, a pull request's body, a # after a
# continuation that follows no blank, braces and arithmetic beside an
# allowed push, and push named in a $'...' that echo prints.
BUILT_TEXTS = (
    'git push -u origin "$(git branch --show-current)"', 'git push -u origin $(git branch --show-current)',
    'git push --force-with-lease=claude/7:$(git rev-parse origin/claude/7) origin claude/7',
    'git push --force-with-lease=claude/7:"$(git rev-parse origin/claude/7)" origin HEAD:claude/7',
    "git commit -m $'line1\\nline2' && git push origin claude/7", "echo $'a\\tb'; git push origin claude/7",
    'printf \'%s\\n\' "$(git log -1 --format=%H)"; git push origin claude/7',
    'git commit -m "$(cat <<\'EOF\'\nFix it\n\nCo-Authored-By: x\nEOF\n)" && git push -u origin claude/7',
    'gh pr create --title t --body "$(cat <<\'EOF\'\n## Summary\n- git push origin main is refused\nEOF\n)"',
    'git push origin "$(git rev-parse --abbrev-ref HEAD)"', 'echo a \\\n#x; git push origin main',
    "echo $'git push origin main'", 'echo {push,pull} && git push origin claude/7',
    'echo $(( 1 << 2 )) && git push origin claude/7',
    # F29's first review: a refspec that is one name read twice, a name
    # made of expansions alone, and a whole option with nothing after it.
    'git push origin "$(git branch --show-current):$(git branch --show-current)"', "git push origin $B:$B",
    'git push origin "${PREFIX}${N}"', 'git push origin HEAD:"$PREFIX$N"', "git push origin $A$B:$C$D",
    "git push -u origin claude/7 --no-verify${NOPE}", "git push --no-verify$(true) origin claude/7",
    'echo "${X:-git push origin main}"; git push origin claude/7',
    # F29's second review: a default that names the session's own claim, a
    # refspec with a hole on each side of its colon, and a pattern whose
    # class gives neither a +, a colon nor a dash.
    "git push origin $S:$D", "git push origin ${A:-claude/7}", "git push origin ${A:-claude/}$(echo 7)",
    "git push origin HEAD:${B:-claude/7}", "git push origin claude/[7]", "git push origin [c]laude/7", 'git push origin "${BRANCH:-$(git branch '
    '--show-current)}"', "git push -u origin ${1:-claude/7}",
)


class BuiltWordsTest(unittest.TestCase):
    """The words bash builds (F29): the guard reads a word as bash may build
    it, its quotings decoded, each substitution a hole in its word, every
    variable unset and every substitution empty, its braces expanded, and
    the scan of here-documents reads a continuation, arithmetic and a
    delimiter word as bash does. bash 5.2 ran each push these tests say it
    runs, and none of the texts' forbidden pushes."""

    def test_each_push_bash_builds_is_refused(self):
        for command in BUILT_PUSHES:
            with self.subTest(command=command):
                self.assertIsNotNone(refused(command))

    def test_what_sessions_write_most_passes(self):
        for command in BUILT_TEXTS:
            with self.subTest(command=command):
                self.assertIsNone(refused(command))

    def test_what_the_fix_leaves(self):
        """A branch by a substitution whole is a value the guard cannot
        know, read as a variable is, so a push to $(echo main) passes, as
        one to $BRANCH does; and a push named in a here-document's delimiter
        word, which bash reads as text, is still read by the whole reading,
        as one in a body is, and refused, too much."""
        self.assertIsNone(refused("git push origin $(echo main)"))
        self.assertIsNotNone(refused("cat <<E$(git push origin main)F\nhi\nE$(git push origin main)F\n"
                                     "git push origin claude/7"))
        self.assertIsNone(refused("cat <<E$(echo x)F\nhi\nE$(echo x)F\ngit push origin claude/7"))

    def test_a_built_git_word_runs_nothing_after_an_option_git_does_not_know(self):
        """A first word that may be git, with an option git refuses before
        its verb, runs no push (GIT_FLAGS): env reads each ${NAME} of its
        -S string as set in one reading, and git -u then runs nothing; one
        of git's own options is read past."""
        self.assertIsNone(refused("env -S '${NOPE} -u ${HOME} git push --force-with-lease origin HEAD'"))
        self.assertIsNone(refused("$G -u x push origin main"))
        self.assertIsNotNone(refused("$G --no-pager push origin main"))
        self.assertIsNotNone(refused("$G -C /w push origin main"))

    def test_a_built_option_passes_only_after_a_whole_flag_no_other_extends(self):
        """A built option is refused unless the text before its first hole
        is a whole option of git push that takes no value and that no other
        option's name extends (guard.whole_flag), so --no-verify${NOPE} is
        --no-verify or a word git refuses; --"$opt" may be --force,
        --force$X --force-with-lease, -u$X -uf and --no-v$X a start."""
        for command in ('git push --"$opt" origin claude/7', "git push --force$X origin claude/7",
                        "git push -u$X origin claude/7", "git push --no-v$X origin claude/7",
                        "git push --repo$X origin claude/7", "git push --no-force$X origin claude/7",
                        "git push --all$NOPE origin"):
            with self.subTest(command=command):
                self.assertIsNotNone(refused(command))
        for command in ("git push --thin$X origin claude/7", "git push --no-thin$X origin claude/7",
                        "git push --verify${X} origin claude/7", "git push --atomic$(true)x origin claude/7"):
            with self.subTest(command=command):
                self.assertIsNone(refused(command))

    def test_a_refspec_that_collapses_to_a_colon_or_a_plus_is_kept_as_written(self):
        """In the world where every variable is unset, $B:$B is the
        refspec :, which pushes every branch both sides have; the guard
        reads it as written, a name it cannot know read twice, as it reads
        $B, while a + in it still forces, and a written name beside it is
        still judged. Since F29's second review only a word that opens and
        ends with a hole is kept so, and +$B is read as the + it is where B
        is nothing."""
        self.assertEqual(guard.unset_words(["git", "push", "origin", "$B:$B", "+$B", "$B:main"]),
                         ["git", "push", "origin", "$B:$B", "+", ":main"])
        self.assertIsNotNone(refused("git push origin +$B"))
        self.assertIsNotNone(refused("git push origin $B:main"))

    def test_a_default_s_own_text_is_read_where_its_operator_gives_it(self):
        """F29's second review: a ${NAME<op>word} whose operator gives its
        word, -, :-, = and := where the name is unset and + and :+ where it
        is set, gives the command's own text, so ${A:-ma}$(echo in) reads as
        ma$(echo in), which bash makes main, while the name's own value
        stays one the guard cannot know (guard.defaults_given)."""
        for op in (":-", "-", ":=", "=", ":+", "+"):
            with self.subTest(op=op):
                self.assertEqual(guard.defaults_given("${A" + op + "ma}" + guard.SUBSTITUTED), "ma" + guard.SUBSTITUTED)
                self.assertIsNotNone(refused("git push origin ${A" + op + "ma}$(echo in)"))
        self.assertEqual(guard.defaults_given("${A:?ma}x${#B}${C}"), "${A:?ma}x${#B}${C}")
        self.assertEqual(guard.defaults_way(["${A:-git", "push}", "origin"]), ["git", "push", "origin"])
        self.assertIsNone(refused("git push origin ${A:-claude/7}"))
        self.assertIsNone(refused("git push origin ${A:?unset}"))

    def test_a_word_that_may_open_with_a_dash_is_read_as_a_built_option(self):
        """F29's second review: $(echo -)f gives -f, and so does a * where a
        file is named -f, so a built word that does not open with - as
        written but may be --force or a short bundle holding f is a built
        option (guard.may_force); one made of expansions alone, as
        "$BRANCH", is a value the guard cannot know, as before."""
        sub = guard.SUBSTITUTED
        for word in (sub + "f", "*", "?f", sub + "uf", sub + "orce", "[-]f", "[-]" + sub):
            with self.subTest(word=word):
                self.assertTrue(guard.may_force(word))
        for word in ("$B", sub, sub + sub, "claude/" + sub, sub + "x:y", "[!-]f", sub + "/u", "?", "origin"):
            with self.subTest(word=word):
                self.assertFalse(guard.may_force(word))

    def test_a_pattern_may_give_a_plus_or_a_colon_where_its_class_holds_one(self):
        """F29's second review: a file's name may hold a + or a colon, so ?main
        and [+]main may be the forcing refspec +main, and ? and [:] the
        refspec :, while a class that holds neither gives neither, and an
        expansion's hole is read where it is nothing by the unset world
        (guard.hole_allows, may_open_with_plus, colon_given); and [:]main
        may be :main where a file is so named, which deletes main."""
        for spec in ("?main", "[+]main", "*main", "[^a]main"):
            with self.subTest(spec=spec):
                self.assertTrue(guard.may_open_with_plus(spec))
        for spec in ("[!+]main", "[ab]main", "m?in", "$B", "main"):
            with self.subTest(spec=spec):
                self.assertFalse(guard.may_open_with_plus(spec))
        for spec, given in (("?", ":"), ("[:]", ":"), ("*", ":"), (":*", ":"), ("[:]main", "main"),
                            ("*main", "main"), ("?refs/heads/main", "main"), ("*ard", "board"), ("[:]boa?d", "board")):
            with self.subTest(spec=spec):
                self.assertEqual(guard.colon_given(spec, ("main", "board")), given)
        for spec in ("[a]", "??", "$B", "$B?", ":", "[:]feature", "[a]main", "x:?main", "$X[:]main"):
            with self.subTest(spec=spec):
                self.assertIsNone(guard.colon_given(spec, ("main", "board")))
        self.assertIsNotNone(refused("touch :main; git push origin [:]main"))
        self.assertFalse(guard.may_be("[xy]ain", "main"))
        self.assertTrue(guard.may_be("[lm]ain", "main"))
        self.assertIsNone(refused("git push --delete origin ?"))

    def test_a_colon_beside_one_hole_is_read_as_the_colon_bash_makes(self):
        """F29's second review: only a refspec that opens and ends with a
        hole, as $S:$D, is kept as written; :$X, $D: and ${A:-:}$B are the
        refspec : where the hole is nothing, which bash then pushes."""
        self.assertEqual(guard.unset_words(["git", "push", "origin", ":$X", "$D:", "${A:-:}$B", "$S:$D"]),
                         ["git", "push", "origin", ":", ":", ":", "$S:$D"])
        for command in ("git push origin :$X", "git push origin $D:", 'git push origin ":$X"'):
            with self.subTest(command=command):
                self.assertIsNotNone(refused(command))
        self.assertIsNone(refused("git push origin $S:$D"))

    def test_an_unquoted_default_with_blanks_goes_on_into_the_words_after_it(self):
        """shlex splits a ${ } at a blank inside it, as bash splits what it
        gives where it is unquoted, so the words after it go on with it
        until it closes; quoted it stays one word, which runs no git."""
        self.assertEqual(guard.unset_words(["${NOPE:-git", "push}", "origin", "main"]), ["git", "push", "origin", "main"])
        self.assertEqual(guard.unset_words(["${NOPE:+git", "push}", "origin"]), ["origin"])
        self.assertIsNone(refused('"${NOPE:-git push origin main}"'))

    def test_the_hook_reads_a_push_a_line_continuation_splits(self):
        """run asks of the text with each line continuation out, as bash
        takes it out, so a push it splits is read and refused; one that
        spells no push still passes unread."""
        for command in ("git p\\\nush origin main", "git pu\\\nsh origin main", "git push\\\n origin main"):
            with self.subTest(command=command):
                self.assertEqual(guard.run({"tool_input": {"command": command + "\ngit push origin main"},
                                            "cwd": "/"})[0], guard.REFUSE)
        self.assertEqual(guard.run({"tool_input": {"command": "git p\\\null origin main"}, "cwd": "/"}),
                         (guard.PASS, ""))
        self.assertEqual(guard.lines_joined("a \\\nb"), "a b")

    def test_coproc_names_its_coprocess_only_before_a_compound_command(self):
        self.assertEqual(guard.launch(["coproc", "X", "{", "git", "push"]).argv[guard.launch(
            ["coproc", "X", "{", "git", "push"]).start:], ["git", "push"])
        self.assertEqual(guard.launch(["coproc", "git", "push"]).argv[guard.launch(["coproc", "git", "push"]).start:],
                         ["git", "push"])

    def test_a_lone_assignment_may_name_the_repository(self):
        """GIT_DIR=x alone sets the shell's variable, which git sees only
        where it was exported before, so a push by -C after it is judged
        where -C names and in the session's own clone."""
        self.assertEqual(push_places("GIT_DIR=/w/s/.git; git -C /x push"), ["/x"])

    def test_the_template_s_hook_raises_on_none_of_them(self):
        for command in BUILT_PUSHES + BUILT_TEXTS:
            with self.subTest(command=command):
                template_hook(command)
                guard.simple_commands(command)

    def test_words_bash_builds_are_read_in_time(self):
        """Each at the longest command the guard reads, under the bound."""
        full = ReadingTest.at_full_size
        for command in (full("echo ", "$'a\\x41\\'b' ", ""), full("echo $'", "\\x41", "'"),
                        full("echo ", "{a,b} ", ""), full("git ", "{a,b}", " origin"),
                        full("git p", "{u,", "}sh origin"), full("git ", "${x:-", "push} origin"), full("", "git pu$(true)sh x; ", ""),
                        full("", "$NOPE ", "git push origin main;"), full("git push origin ", "ma?n ", ""),
                        full("echo ", "a \\\n", ""), full("echo $(( ", "1+", "1 ))"), full("echo ", "$(( ", "1"),
                        full("git push origin ", "$a$b$c", ""), full("git push origin ma", "$(x)", "in"),
                        full("", "cat <<E$(x)F\nE$(x)F\n", ""), full("git push origin ", "@(", ""),
                        full("echo ", "?(", ")"), full("", "${NOPE:-a ", ""), full("${NOPE:-", "git push x ", "}"),
                        full("git push origin ", "$B:$B ", ""), full("git push ", "--no-verify$X ", "origin"),
                        full("git push origin ", "${A[@]:-b} ", ""),
                        # F29's second review: a subscript that never
                        # closes, a run of parentheses after @, defaults
                        # beside holes, and patterns a file may fill.
                        full("git push origin ", "${A[", ""), full("git push origin ", "${#A[x", ""),
                        full("git push origin @", "(", ""), full("git push origin ", "${A:-ma}$(x)", ""),
                        full("git push origin ", "${A:-", ""), full("git push ", "$(echo -)f ", ""),
                        full("git push origin ", "*", ""), full("git push origin ", "[+]", ""),
                        full("git push origin ", "? ", ""), full("git push origin ", ":$X ", "")):
            with self.subTest(command=command[:40]):
                started = time.monotonic()
                self.assertIsNotNone(refused(command + "\ngit push origin main"))
                self.assertLess(time.monotonic() - started, 3.0)
                started = time.monotonic()
                self.assertEqual(guard.run({"tool_input": {"command": command + "\ngit push origin main"},
                                            "cwd": "/"})[0], guard.REFUSE)
                self.assertLess(time.monotonic() - started, 3.0)


# Each GNU coreutils wrapper's words before a command, as a person may
# write them: a long option by a start of its name, its value attached or
# the next word, a value it may take attached or left off, a flag, nice's
# --5, which nice reads as an adjustment before its options, and a start
# of more than one option's name or of none, which the wrapper refuses
# (F26). env's --split-string is left out: what it splits is one word to
# the guard (RunTest).
WRAPPER_WORDS = (
    ["env", "--uns", "HOME"], ["env", "--u", "HOME"], ["env", "--unset=HOME"], ["env", "--ch", "/"], ["env", "--c=/"],
    ["env", "--chdir", "/", "--uns", "HOME"], ["env", "--def"], ["env", "--def=TERM"],
    ["env", "--default-signal", "TERM"], ["env", "--ignore-e"], ["env", "--deb"], ["env", "--l"], ["env", "--b=PIPE"],
    ["env", "--d"], ["env", "--i"], ["env", "--x"], ["nice", "--adj", "5"], ["nice", "--a", "5"],
    ["nice", "--adjustment=5"], ["nice", "-n", "5"], ["nice", "-5"], ["nice", "--5"], ["nice", "--x"],
    ["timeout", "--sig", "KILL", "60"], ["timeout", "--s", "TERM", "--k", "5", "60"], ["timeout", "--kill=5", "60"],
    ["timeout", "--f", "60"], ["timeout", "--p", "60"], ["timeout", "--verb", "60"], ["timeout", "--v", "60"],
    ["nohup", "--"], ["nohup", "--x"], ["env", "-P", "/usr/bin"], ["env", "-L", "root"], ["env", "-U", "root"],
)
# What a GNU coreutils program exits with when it refuses its own words
# and runs nothing.
CANCELED = 125
# An option line of a GNU program's --help: "-u, --unset=NAME", "--block-
# signal[=SIG]" or "--null", the short letter, the long name and what the
# long one takes.
HELP_OPTION = re.compile(r"^\s+(?:-(\S), )?--([a-z][a-z0-9-]*)(\[=|=)?", re.M)
TAKES = {"=": guard.VALUE, "[=": guard.OPTIONAL, None: guard.FLAG}


def named_in_full(word, wrapper):
    """guard.long_option_of as the guard read a wrapper's long option until
    F26's fix: by its whole name alone."""
    name = word[2:].partition("=")[0]
    return name if name in wrapper.long_options else None


def gnu_coreutils(name):
    """Whether name runs GNU coreutils' program of that name here."""
    try:
        shown = subprocess.run([name, "--version"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return "GNU coreutils" in shown.stdout


class WrapperTest(unittest.TestCase):
    """F26: a wrapper's long option is read as GNU's getopt_long reads it,
    by its full name or a start of it that names no other option, with a
    value as the option takes one: the guard compared it with the names
    that take a value, in full, so the value after "env --uns" or "nice
    --adj" or "timeout --sig" was read as the command, and the push
    behind it passed."""

    def test_a_long_option_is_read_by_any_start_of_its_name_that_names_it_alone(self):
        for command in ("env --uns HOME git push origin main", "env --u HOME git push origin main",
                        "env --unset=HOME git push origin main", "env --ch .. git push origin main",
                        "env --sp -i --uns HOME git push origin main", "env --a pusher git push origin main",
                        "env -a pusher git push origin main", "env --env0 file git push origin main",
                        "env --q literal git push origin main", "nice --adj 5 git push origin main",
                        "nice --a 5 git push origin main", "timeout --sig KILL 60 git push origin main",
                        "timeout --s TERM --k 5 60 git push origin main",
                        "timeout --kill=5 --si=TERM 60 git push origin main",
                        "time --output-file x git push origin main", "time --output x git push origin main",
                        "time --o x --fo %e --a git push origin main", "time --f %e --verb git push origin main"):
            with self.subTest(command=command):
                self.assertEqual([guard.push_arguments(argv) for argv in guard.simple_commands(command)],
                                 [["origin", "main"]])

    def test_bsd_env_s_short_options_that_take_a_value_are_read_with_it(self):
        """The env of FreeBSD and macOS takes -P altpath, and FreeBSD's
        -L and -U a login class and a user, each with a value, attached or
        the next word, and runs the command after it, so the push behind
        each is judged; GNU's env refuses all three and runs nothing."""
        for command in ("env -P /usr/bin git push origin main", "env -P/usr/bin git push origin main",
                        "env -L root git push origin main", "env -U root git push origin main",
                        "env -i -P /usr/bin -u HOME git push origin main", "env -Lroot/ git push origin main"):
            with self.subTest(command=command):
                self.assertEqual([guard.push_arguments(argv) for argv in guard.simple_commands(command)],
                                 [["origin", "main"]])

    def test_an_exact_name_wins_and_a_start_of_more_than_one_or_of_none_names_nothing(self):
        env, timeout = guard.WRAPPERS["env"], guard.WRAPPERS["timeout"]
        for word, wrapper, option in (("--unset", env, "unset"), ("--uns", env, "unset"), ("--ch=..", env, "chdir"),
                                      ("--def", env, "default-signal"), ("--deb", env, "debug"),
                                      ("--d", env, None), ("--i", env, None), ("--ignore-", env, None),
                                      ("--x", env, None), ("--=x", env, None), ("--verb", timeout, "verbose"),
                                      ("--vers", timeout, "version"), ("--ver", timeout, None),
                                      ("--5", guard.WRAPPERS["nice"], None),
                                      ("--help", guard.WRAPPERS["command"], None)):
            with self.subTest(word=word):
                self.assertEqual(guard.long_option_of(word, wrapper), option)
        shared = guard.Wrapper("", {"out": guard.VALUE, "output": guard.FLAG})
        self.assertEqual(guard.long_option_of("--out", shared), "out", "an exact name wins over a longer one")
        self.assertEqual(guard.long_option_of("--outp", shared), "output")
        self.assertEqual(guard.long_option_of("--ou", shared), None)

    def test_a_value_is_the_next_word_only_where_the_option_needs_one(self):
        """A value the option may take is taken only attached, so env runs
        the word after --default-signal, here TERM, and no push; a flag
        takes none; and a word the wrapper refuses, which runs nothing, is
        read as taking none, so the push after it is judged as though the
        wrapper ran it."""
        for command, pushes in (("env --default-signal TERM git push origin main", [None]),
                                ("env --default-signal git push origin main", [["origin", "main"]]),
                                ("env --def=TERM git push origin main", [["origin", "main"]]),
                                ("env --ignore-e git push origin main", [["origin", "main"]]),
                                ("timeout --f 60 git push origin main", [["origin", "main"]]),
                                ("timeout --p --verb 60 git push origin main", [["origin", "main"]]),
                                ("env --d git push origin main", [["origin", "main"]]),
                                ("env --i git push origin main", [["origin", "main"]]),
                                ("timeout --v 60 git push origin main", [["origin", "main"]]),
                                ("nohup --x git push origin main", [["origin", "main"]]),
                                ("command --help git push origin main", [["origin", "main"]])):
            with self.subTest(command=command):
                self.assertEqual([guard.push_arguments(argv) for argv in guard.simple_commands(command)], pushes)

    def test_each_installed_gnu_wrapper_s_options_are_in_its_table_as_its_help_lists_them(self):
        """The table holds each option coreutils' env, nice, nohup and
        timeout list in their --help where they are installed, each long
        one resolving to an option that takes what the help says, and each
        short one that takes a value among the short values. GNU time,
        seldom installed, is read as its src/time.c reads its options
        (WRAPPERS), which the first test holds."""
        for name in ("env", "nice", "nohup", "timeout"):
            if not gnu_coreutils(name):
                continue
            wrapper = guard.WRAPPERS[name]
            listed = HELP_OPTION.findall(subprocess.run([name, "--help"], capture_output=True, text=True).stdout)
            self.assertIn("help", [long for _, long, _ in listed], name)
            for short, long, takes in listed:
                with self.subTest(wrapper=name, option=long):
                    self.assertEqual(wrapper.long_options.get(guard.long_option_of(f"--{long}", wrapper)),
                                     TAKES[takes or None])
                    if short:
                        self.assertEqual(short in wrapper.short_values, TAKES[takes or None] == guard.VALUE)

    def test_the_guard_reads_the_command_each_installed_gnu_wrapper_runs(self):
        """Run with printf after its words, each wrapper runs printf where
        the guard reads printf as the command, and something else where the
        guard reads something else; where the wrapper refuses its own words
        and runs nothing, the guard reads on to printf."""
        for words in WRAPPER_WORDS:
            if not gnu_coreutils(words[0]):
                continue
            argv = words + ["printf", "%s", "ran"]
            with self.subTest(argv=argv):
                done = subprocess.run(argv, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=30)
                start = guard.command_start(argv)
                read = start is not None and argv[start] == "printf"
                if done.returncode == CANCELED:
                    self.assertTrue(read, "a word the wrapper refuses is read as taking no value")
                else:
                    self.assertEqual(read, done.stdout == "ran", done.stderr)


# env's words before a command as F28 reads them, each run by the GNU env
# installed here with printf after it (EnvAssignmentTest): a word that
# holds a = but no name the shell takes, a lone - after the options, and
# a string -S splits.
ENV_WORDS = (
    ["env", "1x=2"], ["env", "A-B=1"], ["env", "=x"], ["env", "-i", "--", "A.B=1"], ["env", "--", "-"],
    ["env", "-", "1x=2"], ["env", "--uns", "FOO", "1x=2"], ["env", "-S", "1x=2"], ["env", "-S", "-i 1x=2 -"],
    ["env", "-iS", "A.B=1"], ["env", "-S1x=2"], ["env", "--sp=-u X 1x=2"], ["env", "--split-string", "-C / x-y=1"],
    ["env", "-S", "-S 1x=2"], ["env", "FOO=1", "-"], ["env", "-S", "'unclosed"], ["env", "-S", "$HOME"],
    ["env", "-S", "a\\qb"], ["env", "-S", "\"\\c\""], ["env", "-S", "#"], ["env", "-S", "\\c 1x=2"],
    ["env", "-S"], ["env", "-u"],
)
# Strings for -S, each split by split_string as GNU env splits it.
SPLIT_STRINGS = (
    "a b", "  a\t\tb  ", "'a b' c", '"a b" c', "a'b c'd", "'' x", '"" x', "a\\_b", '"a\\_b"', "'a\\_b'",
    "a\\nb", "'a\\nb'", '"a\\tb"', "a\\\\b", "'a\\\\b'", "'a\\'b'", '"a\\"b"', "a\\$b", "a\\#b", "#a b", "a #b",
    "a#b c", "a \\c b", "'x' \\c", "x\\ y",
)


def env_split(text):
    """The words the env installed here splits text into with -S, run
    with python after them, or None where it refuses the string."""
    shown = f"{sys.executable} -c 'import sys;print(repr(sys.argv[1:]))' "
    done = subprocess.run(["env", "-S", shown + text], capture_output=True, text=True, timeout=30,
                          stdin=subprocess.DEVNULL)
    return None if done.returncode == CANCELED else ast.literal_eval(done.stdout.strip())


class EnvAssignmentTest(unittest.TestCase):
    """F28: GNU env reads every word after its options that holds a = as an
    assignment, not only one the shell would (env.c's loop on strchr), a
    lone - after its options as -i, and the string -S gives it as the
    words it splits it into, so the guard, which read 1x=2, the - and the
    string as the command env runs, let the push behind each pass."""

    def test_each_word_env_reads_before_its_command_is_read_so(self):
        for command in ("env 1x=2 git push origin main", "env A-B=1 git push origin main",
                        "env =x git push origin main", "env -i -- A.B=1 git push origin main",
                        "nice env x-y=1 git push origin main", "env --uns FOO 1x=2 git push origin main",
                        "env 1x=2 A=1 a.b=c git push origin main", "env -- - git push origin main",
                        "env - 1x=2 git push origin main", "env -C / 1x=2 git push origin main",
                        "env 1x=2 nice git push origin main", "env 1x=2 env A-B=1 git push origin main",
                        "env -S 'git push origin main'", "env -S'git push origin main'",
                        "env '-S git push origin main'", "env --split-string='git push origin main'",
                        "env --sp 'git push origin main'", "env -iS 'git push origin main'",
                        "env -S '-i 1x=2 git push origin main'", "env -S 'env -S \"git push origin main\"'",
                        "env -S 'git push\\_origin main'", "env -S 'git push origin main #comment'",
                        "env -S 'git push origin main \\c rest'", "env -S \"git 'push' origin main\"",
                        "env -S 'git' push origin main", "env -S '-u HOME' git push origin main"):
            with self.subTest(command=command):
                self.assertEqual([guard.push_arguments(argv) for argv in guard.simple_commands(command)],
                                 [["origin", "main"]])

    def test_harmless_forms_pass(self):
        """A command env runs that is no push, an assignment only after env
        (bash runs 1x=2 as a command, which fails), a - that follows an
        assignment, which env runs as the command, and a string env refuses
        and runs nothing, left one word as before the fix."""
        for command in ("env FOO=bar make", "env -u X ls", "env 1x=2 printf ran", "1x=2 git push origin main",
                        "env FOO=1 - git push origin main", "env -S 'printf git push origin main'",
                        "env -S 'echo push' main"):
            with self.subTest(command=command):
                self.assertEqual([guard.push_arguments(argv) for argv in guard.simple_commands(command)
                                  if guard.push_arguments(argv) is not None], [])
        self.assertEqual(guard.launch(["env", "-S", "'x", "git", "push"]).argv, ["env", "-S", "'x", "git", "push"])

    def test_an_assignment_after_env_names_the_repository_as_one_before_it_does(self):
        """GIT_DIR set by env, after any word env takes as an assignment,
        sends the push where the guard does not look, as one set by the
        shell before the command does, so its clone is not told."""
        for command in ("env 1x=2 GIT_DIR=/r git -C /x push", "env -S 'GIT_DIR=/r' git push",
                        "GIT_DIR=/r env git -C /x push", "env --uns A 1x=2 GIT_REFERENCE_BACKEND=files:///r git push"):
            with self.subTest(command=command):
                self.assertEqual(push_places(command), [None])
        self.assertEqual(push_places("env 1x=2 git -C /x push"), ["/x"])
        self.assertEqual(push_places("env -S '-C /x' 1x=2 git push"), ["/x"])

    def test_env_alone_sets_no_variable_of_the_shell(self):
        """env GIT_DIR=x with no command prints its environment and sets
        nothing in the shell, so the push after it is judged where its -C
        names; a lone assignment sets the shell's own (F28: until the fix
        the push after env GIT_DIR=x was judged by its words and in the
        session's own clone alone); one after time is read both ways
        (EnvReviewTest)."""
        self.assertEqual(push_places("env GIT_DIR=/r; git -C /x push"), ["/x"])
        self.assertEqual(push_places("env 1x=2 GIT_DIR=/r; git -C /x push"), ["/x"])
        self.assertEqual(push_places("nice env GIT_DIR=/r; git -C /x push"), ["/x"])
        self.assertEqual(push_places("GIT_DIR=/r; git -C /x push"), ["/x"],
                         "F29: a lone assignment sets a variable git sees only where it was exported, so the push "
                         "is judged where its -C names as well as by its words and in the session's own clone")
        self.assertEqual([reading.place for reading in guard.push_places(
            ["git", "-C", "/x", "push"], guard.moved_to(["GIT_DIR=/r"], guard.Shell("/w/s"), lambda place: True),
            "/w/s")], ["/x", "/w/s", None])
        with self.subTest(shell="bash"):
            shown = subprocess.run(["bash", "-c", "env GIT_DIR=/r > /dev/null; echo \"[$GIT_DIR]\""],
                                   capture_output=True, text=True, env={"PATH": os.environ.get("PATH", "")})
            self.assertEqual(shown.stdout, "[]\n")

    def test_split_string_splits_as_gnu_env_does(self):
        cases = {"a b": ["a", "b"], "'a b' c": ["a b", "c"], "a\\_b": ["a", "b"], '"a\\_b"': ["a b"],
                 "'a\\_b'": ["a\\_b"], "#a b": [], "a#b c": ["a#b", "c"], "a \\c b": ["a"], "'' x": ["", "x"],
                 "${HOME} x": ["${HOME}", "x"], "'${HOME}'": ["${HOME}"], "": []}
        for text, words in cases.items():
            with self.subTest(text=text):
                self.assertEqual(guard.split_string(text), words)
        for text in ("'a", '"a', "$HOME", "${1x}", "a\\", "a\\q", '"\\c"'):
            with self.subTest(refused=text):
                self.assertIsNone(guard.split_string(text))

    def test_split_string_agrees_with_the_installed_gnu_env(self):
        if not gnu_coreutils("env") or subprocess.run(["env", "-S", "true"]).returncode != 0:
            self.skipTest("no GNU env that takes -S")
        for text in SPLIT_STRINGS + ("'a", "$HOME", "a\\q", '"\\c"', "a\\"):
            with self.subTest(text=text):
                self.assertEqual(guard.split_string(text), env_split(text))

    def test_the_guard_reads_the_command_the_installed_gnu_env_runs(self):
        """Run with printf after its words, env runs printf where the guard
        reads printf as the command, and something else where the guard
        reads something else; where env refuses its words and runs
        nothing, the guard reads on to printf."""
        if not gnu_coreutils("env"):
            self.skipTest("no GNU env")
        for words in ENV_WORDS:
            argv = words + ["printf", "%s", "ran"]
            with self.subTest(argv=argv):
                done = subprocess.run(argv, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=30)
                found = guard.launch(argv)
                read = found.start is not None and found.argv[found.start] == "printf"
                if done.returncode == CANCELED:
                    self.assertTrue(read, "words env refuses are read as running what follows")
                else:
                    self.assertEqual(read, done.stdout == "ran", done.stderr)

    def test_a_mutant_for_each_rule_lets_its_shape_through(self):
        """Each part of the fix undone lets the push of its shape pass, as
        before it."""
        for name, replacement, command in (
                ("env_assigns", lambda word: bool(guard.ASSIGNMENT.match(word)), "env 1x=2 git push origin main"),
                ("past_lone_dash", lambda rest, read: None, "env -- - git push origin main"),
                ("split_string", lambda text, unset=False: None, "env -S 'git push origin main'")):
            with self.subTest(name=name), mock.patch.object(guard, name, replacement):
                self.assertEqual([guard.push_arguments(argv) for argv in guard.simple_commands(command)], [None])
        with mock.patch.object(guard, "sets_the_shells_own", lambda found: True):
            self.assertEqual(push_places("env GIT_DIR=/r; git -C /x push"), [None])



class EnvReviewTest(unittest.TestCase):
    """F28's review: a lone - ends env's options, as getopt ends them, the
    words after it read as env reads them; many -S strings are read in a
    time in proportion to the command; only the word time is bash's
    keyword; and a ${NAME} env may drop is read both ways."""

    def test_a_lone_dash_ends_env_s_options(self):
        """GNU env takes the lone - as -i, and every later word that holds a
        = as an assignment, so --split-string=x is no -S and --chdir=/tmp no
        move, as fcbe822 read them."""
        for command in ("env - --split-string=x git push origin main", "env - --sp=x git push origin main",
                        "env -i - --sp=x git push origin main"):
            with self.subTest(command=command):
                self.assertEqual([guard.push_arguments(argv) for argv in guard.simple_commands(command)],
                                 [["origin", "main"]])
        self.assertEqual(push_places("env - --chdir=/tmp git push --force-with-lease origin claude/7", "/w/d"),
                         ["/w/d"])
        self.assertEqual(push_places("env - '--split-string=-C a' git push", "/w/d"), ["/w/d"])
        self.assertEqual(push_places("env -C a - git push", "/w/d"), ["/w/d/a"], "options before it still count")
        with mock.patch.object(guard, "ends_options", lambda word: False):
            self.assertEqual([guard.push_arguments(argv) for argv in
                              guard.simple_commands("env - --sp=x git push origin main")], [None],
                             "read past the -, --sp=x splits into x, read as the command")
        for words in (["env", "-", "--split-string=x"], ["env", "-", "--chdir=/"], ["env", "-", "-u", "X"]):
            if not gnu_coreutils("env"):
                break
            argv = words + ["printf", "%s", "ran"]
            with self.subTest(argv=argv):
                done = subprocess.run(argv, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=30)
                found = guard.launch(argv)
                read = found.start is not None and found.argv[found.start] == "printf"
                self.assertEqual(read, done.stdout == "ran", done.stderr)

    def test_many_split_strings_are_read_by_their_content_within_the_budget(self):
        """Each word is moved once, so a command near MAX_COMMAND of -S
        strings, side by side, one holding many words, or nested to the
        bound, is read and refused for its push, never TOO_SLOW; one nested
        deeper is refused unread, as here-documents nested too deep are."""
        push = "git push origin main"
        commands = {"side by side": "env " + "-S-i " * ((guard.MAX_COMMAND - 30) // 5) + push,
                    "with a value": "env " + "-S'-u X' " * ((guard.MAX_COMMAND - 30) // 9) + push,
                    "many words": "env -S '" + "-i " * ((guard.MAX_COMMAND - 40) // 3) + push + "'",
                    "nested to the bound": "env " + "-S" * guard.MAX_NESTING + "-i " * 80000 + push}
        for name, command in commands.items():
            self.assertLessEqual(len(command), guard.MAX_COMMAND)
            with self.subTest(shape=name):
                started = time.monotonic()
                self.assertEqual(guard.refused_push(command, "/w", lambda place: ("claude/7", "main"),
                                                    lambda place: None, lambda place: True), MAIN)
                self.assertLess(time.monotonic() - started, 3.0)
        deep = "env " + "-S" * 120000 + "x " + push
        started = time.monotonic()
        self.assertEqual(guard.refused_push(deep, "/w", lambda place: ("claude/7", "main"), lambda place: None,
                                            lambda place: True), guard.SPLIT_TOO_DEEP)
        self.assertLess(time.monotonic() - started, 3.0)
        word = "a" * 200000
        started = time.monotonic()
        self.assertEqual(guard.split_string(word + " b"), [word, "b"])
        self.assertLess(time.monotonic() - started, 1.0, "one long word is joined once")

    def test_only_the_word_time_is_bash_s_keyword(self):
        """/usr/bin/time GIT_DIR=/r runs the assignment as a command and
        sets nothing, so the push after it is judged where its -C names
        alone; "time" and \\time, which bash runs as the program too, read
        as time once the quotes are gone, so the push after them is judged
        both ways, there and as though GIT_DIR were set; a bare time sets it,
        and is judged both ways for the same reason."""
        self.assertEqual(push_places("/usr/bin/time GIT_DIR=/r; git -C /x push"), ["/x"])
        for command in ('"time" GIT_DIR=/r; git -C /x push', "\\time GIT_DIR=/r; git -C /x push",
                        "time GIT_DIR=/r; git -C /x push", "time -p GIT_DIR=/r; cd /y; git -C /x push"):
            with self.subTest(command=command):
                readings = [reading.place for argv, shell in guard.placed_commands(command, "/w/s", lambda p: True)
                            if guard.push_arguments(argv) is not None
                            for reading in guard.push_places(argv, shell, "/w/s")]
                self.assertEqual(sorted(readings, key=str), sorted(["/x", "/w/s", None], key=str))
        shown = subprocess.run(["bash", "-c", '"time" GIT_DIR=/r 2>/dev/null; echo "[$GIT_DIR]"'],
                               capture_output=True, text=True, env={"PATH": os.environ.get("PATH", "")})
        self.assertEqual(shown.stdout, "[]\n", "bash runs a quoted time as the program")
        with mock.patch.object(guard, "sets_the_shells_own",
                               lambda found: all(name == "time" for name, _ in found.wrappers)):
            self.assertEqual(push_places("/usr/bin/time GIT_DIR=/r; git -C /x push"), [None])

    def test_a_variable_env_may_drop_is_read_both_ways(self):
        """env expands a ${NAME} that is not set to nothing, dropping a word
        that is nothing else, so the push behind ${NOPE} or ${NOPE}git is
        judged; where the variable is set, the word as written is read
        too."""
        for command in ("env -S '${NOPE} git push origin main'", "env -S '${NOPE}git push origin main'",
                        "env -S 'git ${NOPE} push origin main'", "env -S '${A}${B} git push origin main'",
                        "env -S '-i ${NOPE} git push origin main'"):
            with self.subTest(command=command):
                self.assertEqual(guard.refused_push(command, "/w", lambda place: ("claude/7", "main"),
                                                    lambda place: None, lambda place: True), MAIN)
        self.assertEqual(guard.env_readings(["env", "-S", "${X} git push"]),
                         [["env", "${X}", "git", "push"], ["env", "git", "push"]])
        self.assertEqual(guard.env_readings(["env", "-S", "git push"]), [["env", "git", "push"]])
        self.assertEqual(guard.split_string("${X}a ${Y} b", unset=True), ["a", "b"])
        self.assertEqual(guard.split_string("'${X}'", unset=True), ["${X}"], "not expanded in single quotes")
        self.assertEqual(guard.split_string('"${X}"', unset=True), [""], "the quotes make a word")
        if gnu_coreutils("env"):
            self.assertEqual(subprocess.run(["env", "-u", "NOPE", "-S", "${NOPE} printf %s ran"],
                                            capture_output=True, text=True).stdout, "ran")
        with mock.patch.object(guard, "readings_of", lambda argv: [guard.launch(argv)]):
            self.assertIsNone(guard.refused_push("env -S '${NOPE} git push origin main'", "/w",
                                                 lambda place: ("claude/7", "main"), lambda place: None,
                                                 lambda place: True))


def template_hook(command, current="claude/7", default="main"):
    """The template's hook as it stands before it calls refused_push, its
    tools/guard_push.py's main copied: simple_commands, push_arguments and
    refusal, under no length or time limit; an exception out of it exits
    1, which Claude Code reads as no objection, so the command runs."""
    if "push" not in command:
        return None
    pushes = [args for argv in guard.simple_commands(command)
              if (args := guard.push_arguments(argv)) is not None]
    for args in pushes:
        reason = guard.refusal(args, current, default, files_at({}))
        if reason:
            return reason
    return None


def refused(command):
    return guard.refused_push(command, "/w", lambda place: ("claude/7", "main"), lambda place: None,
                              lambda place: True)


# Pushes a command hands to a shell to run (F32): bash 5.2.21 ran each, by
# -c with a git on PATH that records its arguments and runs nothing, and
# the guard of f6ac177 passed each.
HANDED_PUSHES = (
    "bash -c 'git push origin main'",
    "bash -lc 'git push origin main'",
    "bash -c -- 'git push origin main'",
    "bash -o pipefail -c 'git push origin main'",
    "bash --norc -c 'git push origin main'",
    "sh -ec 'git push origin main'",
    "nohup bash -c 'git push origin main'",
    "env bash -c 'git push origin main'",
    "/bin/bash -c 'git push origin main'",
    "eval 'git push origin main'",
    'eval -- git push origin main',
    'eval git push origin main',
    "sh -c 'git push origin main'",
    "bash <<<'git push origin main'",
    "bash -s <<<'git push origin main'",
    "bash /dev/stdin <<<'git push origin main'",
    'sh <<< "git push origin main"',
    "echo 'git push origin main' | bash",
    'echo git push origin main | sh',
    "echo -e 'git push origin ma\\x69n' | bash",
    "printf 'git push origin main\\n' | sh",
    "printf '%s %s\\n' 'git push' 'origin main' | bash",
    "echo 'git push origin main' | cat | bash",
    "cat <<<'git push origin main' | bash",
    "trap 'git push origin main' EXIT",
    "trap -- 'git push origin main' EXIT",
    "source /dev/stdin <<<'git push origin main'",
    ". /dev/stdin <<<'git push origin main'",
    "echo 'git push origin main' | source /dev/stdin",
    'bash -c \'eval "git push origin main"\'',
    'bash -c "bash -c \'git push origin main\'"',
    "bash -c 'cd /tmp && git push origin HEAD:main'",
    "bash -c 'git push --force origin claude/7'",
    "true && bash -c 'git push origin main'",
    "x=$(bash -c 'git push origin main')",
)
# Commands that hand a shell no forbidden push, or hand it nothing: bash
# ran none of their forbidden pushes, and the guard passes each.
HANDED_TEXTS = (
    "bash -c 'git push -u origin claude/7'",
    "bash script.sh <<<'git push origin main'",
    "echo 'git push origin main' > notes.md",
    "echo 'git push origin main' | grep push",
    'trap - EXIT',
    "trap 'git push origin main'",
    "printf -v x 'git push origin main' | bash",
    "bash -c 'echo git push origin main'",
    "echo 'git push origin main' | tee notes.md",
    'sh -c \'git push origin "$(git branch --show-current)"\'',
)

# F32's first review's pushes, each run by bash 5.2.21; the last four the
# hook's gate let pass unread.
FIRST_REVIEW_PUSHES = (
    "builtin eval 'git push origin main'", "builtin trap 'git push origin main' EXIT",
    "builtin source /dev/stdin <<<'git push origin main'", "builtin . /dev/stdin <<<'git push origin main'",
    "printf 'git push origin %s\\n' claude/7 main | bash", "printf '%s\\n' 'echo hi' 'git push origin main' | bash",
    "printf 'echo %s\\n' hi 'x; git push origin main' | bash", "printf 'git pu%ch origin main' s | bash",
    "printf 'git push origin %5s' main | bash", "printf 'git push origin %.4s' mainx | bash",
    "cat - <<<'git push origin main' | bash", "echo 'git push origin main' | cat - | bash",
    "echo -e 'git push origin \\0155ain' | bash", "sh -c \"echo 'git pu\\0163h origin main' | sh\"",
    "{ echo x; echo 'git push origin main'; } | bash", "(echo 'git push origin main'; echo x) | bash",
    "echo 'git push origin main' | (cd /tmp && bash)", "echo 'git push origin main' | if true; then bash; fi",
    "printf 'git pu\\163h origin main' | bash", "printf 'git pu\\x73h origin main' | bash",
    "printf 'git pu%sh origin main' s | bash", "echo -e 'git pu\\x73h origin main' | bash",
)

SECOND_REVIEW_PUSHES = (
    "printf 'gi\\0t push origin main' | bash",
    "echo -e 'git pu\\0sh origin main' | bash",
    "printf '%b' 'git pu\\0sh origin main' | bash",
    "printf '\\x00git push origin main' | bash",
    "printf '%b%s\\n' 'git push origin main\\c' x | bash",
    "printf '%bx\\n' 'git push origin main\\c' | bash",
    "printf 'git push origin %ls\\n' main | bash",
    "printf 'git push origin %jb\\n' main | bash",
    "{ { echo 'git push origin main'; }; } | bash",
    "if true; then if true; then echo 'git push origin main'; fi; fi | bash",
    "if true; then { echo 'git push origin main'; }; fi | bash",
    "for i in 1; do for j in 1; do echo 'git push origin main'; done; done | bash",
    "! { echo 'git push origin main'; } | bash",
    "time { echo 'git push origin main'; } | bash",
    "case a in a) echo 'git push origin main';; esac | bash",
    "{ printf 'git push '; echo origin main; } | bash",
    "{ echo -n 'git push origin '; echo main; } | bash",
    "( printf 'git pu'; echo 'sh origin main' ) | bash",
    "echo 'git push origin main' |\n bash",
    "printf 'git pu\\163h origin main' | ksh93",
)


class HandedTextTest(unittest.TestCase):
    """What a command hands to a shell to run (F32): a shell's -c string,
    eval's words, trap's action, and a here-string or what echo, printf or
    cat prints into a shell or source of standard input, each read as a
    command of its own from the shell that runs it."""

    def test_each_push_handed_to_a_shell_is_refused(self):
        for command in HANDED_PUSHES:
            with self.subTest(command=command):
                self.assertIsNotNone(refused(command))
                with mock.patch.object(guard, "handed_texts", lambda argv, fed=(): []):
                    self.assertIsNone(refused(command), "with no handed text read")

    def test_what_hands_no_forbidden_push_passes(self):
        for command in HANDED_TEXTS:
            with self.subTest(command=command):
                self.assertIsNone(refused(command))

    def test_the_hook_refuses_them_too(self):
        payload = {"tool_input": {"command": "bash -c 'git push origin main'"}, "cwd": str(ROOT)}
        with mock.patch.object(guard, "branches", return_value=("claude/7", "main")):
            self.assertEqual(guard.run(payload, str(ROOT)), (2, MAIN))

    def test_what_the_fix_leaves(self):
        """A text the command does not spell, a substitution's output, a
        file or a variable, is a value the guard does not know and passes,
        as a wrapper it does not name does."""
        for command in ('eval "$(echo git push origin main)"', "cat push.sh | bash", "bash push.sh",
                        'bash -c "$CMD"', "sudo bash -c 'git push origin main'"):
            with self.subTest(command=command):
                self.assertIsNone(refused(command))

    def test_a_handing_is_read_from_the_shell_that_runs_it(self):
        """A move inside the text is followed from where it starts and
        changes nothing after it, as the shell bash -c starts ends with it."""
        seen = []

        def branches_of(place):
            seen.append(place)
            return ("claude/7", "main")

        guard.refused_push("cd /w/a && bash -c 'cd b && git push origin HEAD'; git push origin HEAD", "/w",
                           branches_of, lambda place: None, lambda place: True)
        self.assertIn("/w/a/b", seen)
        self.assertIn("/w", seen)

    def test_texts_handed_on_too_deep_or_too_many_are_refused_unread(self):
        self.assertEqual(refused("eval " * guard.MAX_NESTING + "'git push origin main'"), MAIN)
        self.assertEqual(refused("eval " * (guard.MAX_NESTING + 1) + "'git push origin claude/7'"),
                         guard.HANDED_TOO_DEEP)
        many = "".join(f"bash -c 'git push origin claude/7 #{i}'; " for i in range(guard.MOST_HANDED))
        self.assertIsNone(refused(many + "git push origin claude/7"))
        self.assertEqual(refused(many + "bash -c 'git push origin claude/7 #last'"), guard.HANDED_TOO_DEEP)
        self.assertIsNone(refused("".join(f"bash -c 'echo {i}'; " for i in range(2 * guard.MOST_HANDED))),
                          "a text the hook's gate would not read is not read, nor counted")
        self.assertEqual(refused("eval " * 15 + "'git push origin claude/7 " + "`a` " * 55000 + "'"),
                         guard.HANDED_TOO_DEEP, "a long text handed on is counted by its characters")

    def test_the_reading_takes_time_in_proportion_to_the_command(self):
        """Each handed text is read once per shell, and the placed commands
        are kept in a set, so a command near MAX_COMMAND of handings is read
        and refused in a few seconds; until the set, it took ten. A text
        with no push is not read at all, as the hook's gate reads none."""
        for form in ("bash -c 'git push #{i}'; ", "echo 'git push #{i}' | sh; ", "bash <<<'git push #{i}'\n",
                     "trap 'git push #{i}' EXIT; ", "eval git push \\#{i}; ", "eval eval 'git push \\#{i}'; "):
            command, i = "", 0
            while len(command) < guard.MAX_COMMAND - 40:
                command += form.format(i=i)
                i += 1
            with self.subTest(form=form):
                began = time.monotonic()
                self.assertEqual(refused(command), guard.HANDED_TOO_DEEP)
                self.assertLess(time.monotonic() - began, 3)

    def test_the_first_review_s_pushes_are_refused(self):
        """F32's first review: builtin before eval, trap and source; printf's
        format read again while words remain, and its widths, precisions
        and %c; cat - reading standard input; echo's \\0nnn; a group's or a
        subshell's whole output into a pipe, and a pipe into a group; and
        the hook's gate reading a text whose escapes spell push. bash
        5.2.21 ran each push, and the guard of 4d86c07 passed each, through
        the hook where the last four say so."""
        for command in FIRST_REVIEW_PUSHES:
            with self.subTest(command=command):
                self.assertIsNotNone(refused(command))
        for command in FIRST_REVIEW_PUSHES[-4:]:
            with self.subTest(command=command):
                self.assertTrue(guard.may_push(command))

    def test_each_first_review_rule_bites(self):
        cases = {"BUILTIN": (frozenset(), "builtin eval 'git push origin main'"),
                 "MOST_PRINTF_PASSES": (1, "printf 'git push origin %s\\n' claude/7 main | bash"),
                 "ECHO_OCTAL": (re.compile("(?!)"), "echo -e 'git push origin \\0155ain' | bash"),
                 "COMPOUND_OPENS": (frozenset(), "{ echo x; echo 'git push origin main'; } | bash"),
                 "BUILDS_TEXT": (frozenset(), "printf 'git pu\\163h origin main' | bash")}
        for name, (value, command) in cases.items():
            with self.subTest(name=name), mock.patch.object(guard, name, value):
                self.assertFalse(refused(command) and guard.may_push(command))

    def test_a_subshell_after_a_pipe_keeps_its_moves_to_itself(self):
        """F32's first review: reading what a pipe feeds lost the subshell
        after it, so its cd was read as the shell's own and its ) closed
        the wrong one; each push here runs in /o, where main is checked
        out."""
        def branches_of(place):
            return ("main", "main") if place == "/o" else ("claude/7", "main")

        for command in ("true | ( cd /o; git push )", "true | ( cd /o && git push )", "true |& ( cd /o; git push )",
                        "( cd /o; true | ( true ); git push )"):
            with self.subTest(command=command):
                self.assertIsNotNone(guard.refused_push(command, "/w", branches_of, lambda place: None,
                                                        lambda place: True))

    def test_the_second_review_s_pushes_are_refused(self):
        """F32's second review: a NUL a pipe's shell drops, %b's \\c ending
        all of printf's output, printf's length modifiers, a compound
        command's second opener and the reserved words before it, a case
        pattern's ), a group's outputs joined as printed, and a newline
        after a pipe. bash 5.2.21 ran each push, and the guard of 0c224c3
        passed each."""
        for command in SECOND_REVIEW_PUSHES:
            with self.subTest(command=command):
                self.assertIsNotNone(refused(command))
                self.assertTrue(guard.may_push(command))

    def test_each_second_review_rule_bites(self):
        cases = {"COMPOUND_LEADS": (frozenset(), "if true; then { echo 'git push origin main'; }; fi | bash"),
                 "PRINTF_CONVERSION": (re.compile(r"%([-+ #0]*)(\*|[0-9]*)(?:\.(\*|[0-9]*))?([a-zA-Z%])"),
                                       "printf 'git push origin %ls\\n' main | bash"),
                 "ECHO_STOP": ("\\c\\c", "printf '%b%s\\n' 'git push origin main\\c' x | bash")}
        for name, (value, command) in cases.items():
            with self.subTest(name=name), mock.patch.object(guard, name, value):
                self.assertIsNone(refused(command))

    def test_a_width_too_wide_to_build_is_read_in_time(self):
        """F32's second review: printf '%999999999999999s' raised
        MemoryError out of the hook, which Claude Code reads as no
        objection, and 5,000 digits raised ValueError; each width is cut to
        what the guard reads, and anything the guard cannot build refuses."""
        for width in ("999999999999999", "9" * 30, "9" * 5000):
            command = "printf '%" + width + "s' x >/dev/null; git push origin main"
            with self.subTest(width=width[:20]):
                start = time.monotonic()
                self.assertEqual(guard.run({"tool_input": {"command": command}}, "/w")[0], guard.REFUSE)
                self.assertLess(time.monotonic() - start, 3)
        self.assertLessEqual(len(guard.printf_text("%999999s" * 20000, ["x"] * 20000)), 3 * guard.MAX_COMMAND)
        with mock.patch.object(guard, "printed_texts", side_effect=MemoryError):
            self.assertEqual(guard.refused_push("echo x | bash", "/w", lambda place: ("claude/7", "main"),
                                                lambda place: None, lambda place: True), guard.UNREADABLE)

    def test_the_template_s_helpers_still_give_lists(self):
        """parts_of keeps a here-string on the words it feeds (Words), a
        list the template's hook reads as before."""
        self.assertEqual(guard.simple_commands("bash <<<'git push origin main'"), [["bash"]])
        self.assertEqual(guard.parts_of("bash <<<'git push origin main'")[0].fed, "git push origin main")


class EnvSecondReviewTest(unittest.TestCase):
    """F28's second review: the template's hook, which calls the public
    helpers itself, meets every reading and every bound; a backslash in
    double quotes hands $ and ` on as bash does; set and unset names are
    read in every mix; nested strings and flat chains of -S are read in a
    time in proportion to the command."""

    def test_the_template_s_hook_refuses_what_the_guard_refuses(self):
        """17 attached -S raised TooDeep out of push_arguments, and the
        hook never saw the unset reading, so each of these ran there where
        fcbe822 refused them through the same hook."""
        commands = {"env " + "-S" * 17 + "git push origin main": guard.SPLIT_TOO_DEEP,
                    "env -S '${NOPE}' git push origin main": MAIN,
                    "env -S'-S${A}' git push origin main": MAIN,
                    "env -S '${NOPE} -' git push origin main": MAIN,
                    "env -S '${A}${B}' git push origin main": MAIN}
        for command, reason in commands.items():
            with self.subTest(command=command):
                self.assertEqual(template_hook(command), reason)
                self.assertEqual(refused(command), reason)
                for argv, shell in guard.placed_commands(command, "/w", lambda place: True):
                    guard.launch(argv), guard.command_start(argv), guard.chdir_paths(argv)
                    guard.env_readings(argv), guard.moved_to(argv, shell, lambda place: True)
        self.assertIsNone(template_hook("env -S '${NOPE}' git push origin claude/7"))
        with mock.patch.object(guard, "readings_of", lambda argv: [guard.launch(argv)]):
            self.assertIsNone(template_hook("env -S '${NOPE}' git push origin main"),
                              "the reading as written alone: ${NOPE} run as the command")

    def test_a_backslash_in_double_quotes_hands_on_the_dollar(self):
        """bash turns \\$ and \\` inside double quotes into $ and `, so env
        sees ${NOPE} and drops it where NOPE is not set."""
        for command in ('env -S "\\${NOPE}git push origin main"',
                        'env -S "-S\'\\${NOPE}git push origin main\'"',
                        'env "-S\\${NOPE}git push origin main"'):
            with self.subTest(command=command):
                self.assertEqual(refused(command), MAIN)
                self.assertEqual(template_hook(command), MAIN)
        self.assertEqual(guard.simple_commands('env -S "\\${X} \\`y\\` \\a"'), [["env", "-S", "${X} `y` \\a"]])
        shown = subprocess.run(["bash", "-c", 'printf %s "\\${X}\\`"'], capture_output=True, text=True)
        self.assertEqual(shown.stdout, "${X}`")
        with mock.patch.object(guard, "QUOTED_PAIRS", {"\n": ""}), built_words_unread():
            self.assertIsNone(refused('env -S "\\${NOPE}git push origin main"'))

    def test_set_and_unset_names_are_read_in_every_mix(self):
        """Up to MOST_NAMES names, one reading for each set of them unset;
        past it a command that holds a push is refused unread."""
        for command in ("env -S '${NOPE} -C ${HOME} git push origin main'",
                        "env -S '${NOPE}-u ${HOME} git push origin main'",
                        "env -S '${A} ${B} -C ${C} git push origin main'"):
            with self.subTest(command=command):
                self.assertEqual(refused(command), MAIN)
                self.assertEqual(template_hook(command), MAIN)
        self.assertIsNone(refused("env -S '${A} ${B} -C ${C} git push origin claude/7'"))
        many = "env -S '${A}${B}${C}${D}${E}${F}${G} git push origin claude/7'"
        self.assertEqual(refused(many), guard.SPLIT_TOO_MANY_NAMES)
        self.assertEqual(template_hook(many), guard.SPLIT_TOO_MANY_NAMES)
        self.assertEqual([reading.argv for reading in guard.readings_of(["env", "-S", "${A}${B}${C}${D}${E}${F}${G} ls"])],
                         [["env", "${A}${B}${C}${D}${E}${F}${G}", "ls"], ["env", "ls"]],
                         "no push: read as written, and with every variable unset (F29)")
        self.assertEqual(len(guard.unset_subsets(["${A}", "${B}", "${C}"])), 8)
        with mock.patch.object(guard, "unset_subsets",
                               lambda names: [frozenset(), frozenset(name[2:-1] for name in names)]):
            self.assertIsNone(refused("env -S '${NOPE} -C ${HOME} git push origin main'"),
                              "all set or all unset alone: -C takes git, or ${NOPE} runs")

    def test_a_push_env_spells_is_refused_unread_where_the_guard_cannot_read_it(self):
        """F28's third review: the refusals unread looked for push in the
        words as written, so pu""sh and pu${NOPE}sh, which env's -S makes
        push, passed both; a string nested too deep is refused unread
        whatever its words, and past the names the guard reads each mix of,
        a command is refused where its words may spell push once quotes,
        backslashes and ${NAME}s are out (holds_push)."""
        for command in ("env -S '${A}${B}${C}${D} git pu\"\"sh origin main'; echo push",
                        "env '" + "-S" * 17 + "git pu\"\"sh origin main'; echo push",
                        "env -S '${A}${B}${C} git pu${NOPE}sh origin main'; echo push",
                        "env -S '${A}${B}${C}${D}${E}${F}${G} git pu\"\"sh origin main'; echo push",
                        "env -S '${A}${B}${C}${D}${E}${F}${G} -S\"git pu'\"''\"'sh origin main\"'; echo push"):
            with self.subTest(command=command):
                self.assertIsNotNone(refused(command))
                self.assertIsNotNone(template_hook(command))
        self.assertEqual(guard.run({"tool_input": {"command": 'env -S \'git pu""sh origin main\''}, "cwd": "/"})[0],
                         guard.REFUSE, "the library's own hook asks of a text that spells push")
        self.assertEqual(guard.run({"tool_input": {"command": 'git pu""sh origin main'}, "cwd": "/"})[0], guard.REFUSE)
        self.assertTrue(guard.holds_push(["pu\\${A}s\"\"h"]))
        self.assertFalse(guard.holds_push(["pu\\_sh", "pu sh", "pul"]))
        self.assertIsNotNone(refused("env " + "-S" * 17 + "ls; git push origin claude/7"),
                             "nested too deep: the words env runs are not read")
        with mock.patch.object(guard, "holds_push", lambda argv: any("push" in word for word in argv)), \
                built_words_unread():
            self.assertIsNone(refused("env -S '${A}${B}${C}${D}${E}${F}${G} git pu\"\"sh origin main'; echo push"))

    def test_every_mix_is_read_up_to_the_bound(self):
        """F28's third review: past three names the guard refused every
        command that held push as written, though env runs no push in
        these, or only the owner's own; up to MOST_NAMES every mix is read,
        since a push one mix alone runs is found by no other, as here where
        B alone is set, and the readings spend the budget at most once."""
        for command in ("env -S 'echo ${A} ${B} ${C} ${D} push'", "env -S 'printf %s ${A}${B}${C}${D}' push",
                        "env -S 'git commit -m \"push ${A} ${B} ${C} ${D}\"'",
                        "env -S '${A} ${B} ${C} ${D}' git push -u origin claude/7",
                        "env -S '${A} ${B} ${C} ${D} ${E} ${F}' git push -u origin claude/7"):
            with self.subTest(command=command):
                self.assertIsNone(refused(command))
                self.assertIsNone(template_hook(command))
        mix = "env -S '${A}-u ${B} ${C}-u ${D}' x git push origin main"
        self.assertEqual(refused(mix), MAIN)
        self.assertEqual(template_hook(mix), MAIN)
        if gnu_coreutils("env"):
            done = subprocess.run(["env", "-u", "A", "-u", "C", "-u", "D", "B=1", "env", "-S", "${A}-u ${B} ${C}-u ${D}",
                                   "x", "printf", "%s", "ran"], capture_output=True, text=True)
            self.assertEqual(done.stdout, "ran", "B alone set: -u 1 -u x, then the command")
        with mock.patch.object(guard, "unset_subsets",
                               lambda names: [frozenset(), frozenset(name[2:-1] for name in names)]):
            self.assertIsNone(refused(mix), "all kept: ${A}-u runs; all unset: -u -u, then x runs")
        wide = "env -S '${A}${B}${C}${D}${E}${F} " + "-i " * 30000 + "git push origin claude/7'"
        started = time.monotonic()
        self.assertEqual(refused(wide), guard.SPLIT_TOO_MANY_NAMES)
        self.assertLess(time.monotonic() - started, 3.0)
        self.assertIsNone(refused("env -S '${A}${B}${C}${D}${E}${F} " + "-i " * 30000 + "ls'"))

    def test_nested_strings_and_flat_chains_are_read_in_time(self):
        """A string nested in quoted -S strings is split once a level, so a
        wide one nested 14 to 16 deep spends the budget and is refused
        unread, quickly; a narrow one is read by its content; and -S taking
        the next word as its value starts from that word's depth, so a flat
        chain of any length is read by its content."""
        def nested(levels, inner):
            for _ in range(levels - 1):
                inner = "-S '" + inner.replace("\\", "\\\\").replace("'", "\\'") + "'"
            return "env -S " + shlex.quote(inner)
        for levels in (14, 15, 16):
            head = len(nested(levels, ""))
            command = nested(levels, "-i " * ((guard.MAX_COMMAND - 2 * head - 400) // 3 // 2) + "git push origin main")
            self.assertLessEqual(len(command), guard.MAX_COMMAND)
            with self.subTest(levels=levels):
                started = time.monotonic()
                self.assertEqual(refused(command), guard.SPLIT_TOO_DEEP)
                self.assertEqual(template_hook(command), guard.SPLIT_TOO_DEEP)
                self.assertLess(time.monotonic() - started, 3.0)
        self.assertEqual(refused(nested(16, "-i git push origin main")), MAIN)
        self.assertIsNone(refused(nested(16, "-i git push origin claude/7")))
        self.assertEqual(refused(nested(17, "-i git push origin claude/7")), guard.SPLIT_TOO_DEEP)
        for count in (17, 40):
            with self.subTest(count=count):
                self.assertIsNone(refused("env " + "-S " * count + "git push origin claude/7"))
                self.assertEqual(refused("env " + "-S " * count + "git push origin main"), MAIN)
                self.assertEqual(template_hook("env " + "-S " * count + "git push origin main"), MAIN)
        chain = "env " + "-S " * ((guard.MAX_COMMAND - 40) // 3) + "git push origin main"
        started = time.monotonic()
        self.assertEqual(refused(chain), MAIN)
        self.assertLess(time.monotonic() - started, 3.0)


HOME = os.path.expanduser("~")


def push_places(command, here="/w/s", is_directory=lambda place: True):
    """The directory each push of a shell command runs in, in order, as the
    guard follows the shell from here (guard.placed_commands,
    guard.followed_and_unmoved), every directory a cd names being one
    unless is_directory says otherwise."""
    return [guard.followed_and_unmoved(argv, shell, here)[0]
            for argv, shell in guard.placed_commands(command, here, is_directory)
            if guard.push_arguments(argv) is not None]


class PlaceTest(unittest.TestCase):
    """Where each push runs (F21): the directories git's -C and env's -C
    name, joined as git and env read them, the shell's own moves, which hold
    for what follows them in the same shell, and None where this module
    cannot tell, which the guard then judges by the push's words alone."""

    def test_git_and_env_name_the_directory_a_push_runs_in(self):
        """Joined as chdir reads them, left for the system to resolve, so a
        .. after a symbolic link climbs from where the link leads, as git's
        and env's own chdir does (OtherCloneTest has it over git)."""
        for command, place in (("git -C ../other push origin x", "/w/s/../other"),
                               ("git -C .. -C other push", "/w/s/../other"),
                               ("git -C /elsewhere push", "/elsewhere"),
                               ("git -C '' push", "/w/s"),
                               ("git -C ~ push", HOME),
                               ("git -c user.name=x -C ../other push", "/w/s/../other"),
                               ("git --config-env user.name=HOME -C ../other push", "/w/s/../other"),
                               ("git --work-tree=../other push", "/w/s"),
                               ("env -C ../other git push", "/w/s/../other"),
                               ("env -C../other git push", "/w/s/../other"),
                               ("env -iC ../other git push", "/w/s/../other"),
                               ("env --chdir=../other git push", "/w/s/../other"),
                               ("env --chdir ../other git -C x push", "/w/s/../other/x"),
                               ("env -u HOME git push", "/w/s"),
                               ("env -C sub -C ../other git push", "/w/s/../other"),
                               ("env -C sub --chdir=../other git push", "/w/s/../other"),
                               ("env -C a env -C b git push", "/w/s/a/b"),
                               ("git --shallow-file x -C ../other push", "/w/s/../other")):
            with self.subTest(command=command):
                self.assertEqual(push_places(command), [place])

    def test_env_changes_directory_once_to_the_last_it_is_given(self):
        """GNU env reads its options first and changes directory after, to the
        last directory -C or --chdir gave it, from where it was run; git's
        own -C, by contrast, are joined on in turn (F21's third review)."""
        if shutil.which("env") is None or subprocess.run(["env", "-C", "/", "true"]).returncode != 0:
            self.skipTest("no env that takes -C")
        with tempfile.TemporaryDirectory() as scratch:
            Path(scratch, "sub").mkdir()
            Path(scratch, "other").mkdir()
            ran = subprocess.run(["env", "-C", "sub", "-C", "other", "pwd"], cwd=Path(scratch, "sub").parent,
                                 capture_output=True, text=True)
            self.assertEqual(Path(ran.stdout.strip()).resolve(), Path(scratch, "other").resolve())
        self.assertEqual(guard.env_directory(["-C", "sub", "-C", "../other"]), "../other")
        self.assertEqual(guard.env_directory(["-u", "HOME"]), None)

    def test_env_s_chdir_is_read_by_any_start_of_its_name_that_names_it_alone(self):
        """GNU env reads --ch, --c=DIR and --chd as --chdir, each start of it
        that names no other option, and a value the option before it needs,
        attached or the next word, as that option's, so "env --uns --ch"
        unsets a variable named --ch and changes no directory (F26: a push
        after --c=DIR was judged where env was run, and one after --ch DIR
        not at all, DIR read as the command). Each place is where env 9.4
        runs pwd."""
        for command, place in (("env --ch ../other git push", "/w/s/../other"),
                               ("env --c=../other git push", "/w/s/../other"),
                               ("env --chd ../other git -C x push", "/w/s/../other/x"),
                               ("env --uns HOME --ch ../other git push", "/w/s/../other"),
                               ("env --def --ch ../other git push", "/w/s/../other"),
                               ("env --ch sub -C ../other git push", "/w/s/../other"),
                               ("env -C sub --c ../other git push", "/w/s/../other"),
                               ("env --ch=../other --chdir sub git push", "/w/s/sub"),
                               ("env --uns --ch git push", "/w/s"),
                               ("env --u=--ch git push", "/w/s")):
            with self.subTest(command=command):
                self.assertEqual(push_places(command), [place])
        self.assertEqual(guard.env_directory(["--ch", "a", "--c=b"]), "b")
        self.assertEqual(guard.env_directory(["--uns", "--ch"]), None)
        self.assertEqual(guard.env_directory(["--debug", "--d"]), None)

    def test_a_push_that_names_its_repository_or_a_path_the_shell_expands_runs_where_this_cannot_tell(self):
        for command in ("git -C $DIR push", "git -C \"$DIR\" push", "git -C ../o* push", "git -C `pwd` push",
                        "git --git-dir=../other/.git push", "git --git-dir ../other/.git push", "git --bare push",
                        "GIT_DIR=../other/.git git push", "env GIT_DIR=../other/.git git push",
                        "GIT_REFERENCE_BACKEND=files://../other/.git git push",
                        "env GIT_REFERENCE_BACKEND=files:///w/other/.git git -C /w/s push"):
            with self.subTest(command=command):
                self.assertEqual(set(push_places(command)), {None}, "once for each reading that finds it")

    def test_a_variable_that_names_the_repository_holds_whatever_cd_or_minus_c_comes_after(self):
        """A move changes the directory and not the variable, so a push after
        GIT_DIR, or GIT_REFERENCE_BACKEND, exported, runs where this module
        cannot tell, and after one set alone, which git sees only where it
        was exported before, where the shell stands too (F29), through an absolute cd or -C too, until a
        subshell's ) or the end of a pipeline's part (F21's fourth review:
        an absolute -C after the export was taken for where the push runs).
        GIT_COMMON_DIR moves no ref (OtherCloneTest shows it over git)."""
        for command, places in (("export GIT_DIR=/w/s/.git; git -C /w/other push", [None]),
                                ("export GIT_DIR=/w/s/.git; env -C /w/other git push", [None]),
                                ("export GIT_DIR=/w/s/.git; cd /w/other && git push", [None]),
                                ("GIT_DIR=/w/s/.git; pushd /w/other && popd && git push", ["/w/s"]),
                                ("declare -x GIT_REFERENCE_BACKEND=files:///w/s/.git; git -C /w/other push", [None]),
                                ("export GIT_REFERENCE_BACKEND; cd /w/other; git push", [None]),
                                ("(export GIT_DIR=/w/s/.git); git -C /w/other push", ["/w/other"]),
                                ("export GIT_DIR=/w/s/.git | cat; git -C /w/other push", ["/w/other"]),
                                ("export GIT_COMMON_DIR=/w/s/.git; git -C /w/other push", ["/w/other"])):
            with self.subTest(command=command):
                self.assertEqual(push_places(command), places)

    def test_the_shell_s_moves_hold_for_what_follows_them_in_the_same_shell(self):
        for command, places in (("cd ../other && git push", ["/w/other"]),
                                ("cd ../other; git push", ["/w/other"]),
                                ("cd ../other\ngit push", ["/w/other"]),
                                ("cd ../other || exit 1; git push", ["/w/other"]),
                                ("cd /elsewhere && git -C sub push", ["/elsewhere/sub"]),
                                ("cd && git push", [HOME]),
                                ("cd -L -- ../other && git push", ["/w/other"]),
                                ("builtin cd ../other && git push", ["/w/other"]),
                                ("command cd ../other && git push", ["/w/other"]),
                                ("if cd ../other; then git push; fi", ["/w/other"]),
                                ("cd ../a && cd ../b && git push", ["/w/b"]),
                                ("{ cd ../other; git push; }; git push", ["/w/other", "/w/other"]),
                                ("pushd ../other && git push && popd && git push", ["/w/other", "/w/s"]),
                                ("pushd -n ../other; git push", ["/w/s"]),
                                ("env cd ../other; git push", ["/w/s"]),
                                ("time cd ../other; git push", ["/w/other"]),
                                ("time -p cd ../other; git push", ["/w/other"]),
                                ("nice cd ../other; git push", ["/w/s"]),
                                ("export FOO=1; git push", ["/w/s"]),
                                ("git status; git push", ["/w/s"])):
            with self.subTest(command=command):
                self.assertEqual(push_places(command), places)

    def test_an_absolute_path_is_a_place_wherever_the_shell_stood(self):
        """After a move this module cannot follow, an absolute path still
        names its directory (F21's third review: until then it stayed
        unknown, so a lease through it went unjudged)."""
        for command, places in (("cd $X && git -C /w/other push", ["/w/other"]),
                                ("cd $X && cd /w/other && git push", ["/w/other"]),
                                ("cd $X && cd ~ && git push", [HOME]),
                                ("cd $X && git -C ../other push", [None])):
            with self.subTest(command=command):
                self.assertEqual(push_places(command), places)

    def test_a_move_this_cannot_follow_leaves_the_directory_unknown(self):
        for command in ("cd - && git push", "cd -P ../other && git push", "cd -LP ../other && git push",
                        "cd $X && git push", "cd ~/$X && git push", "pushd && git push",
                        "pushd +1 && git push", "popd && git push", "export GIT_DIR=../o/.git; git push",
                        "declare -x GIT_DIR=../o/.git; git push"):
            with self.subTest(command=command):
                self.assertEqual(push_places(command), [None])

    def test_a_cd_or_pushd_to_what_is_not_a_directory_leaves_the_shell_where_it_stood(self):
        """The shell runs what follows a failed cd from where it stood, so
        the push is judged there; until F21's second review it was judged
        in a directory that holds nothing, so a lease from the clone the
        shell never left went unjudged."""
        def there(place):
            return place != "/w/nowhere"

        for command, places in (("cd ../nowhere; git push", ["/w/s"]),
                                ("cd ../nowhere\ngit push", ["/w/s"]),
                                ("cd ../nowhere || true; git push", ["/w/s"]),
                                ("pushd ../nowhere; git push", ["/w/s"]),
                                ("cd ../nowhere; cd ../other; git push", ["/w/other"]),
                                ("cd ../other; cd ../nowhere; git push", ["/w/other"]),
                                ("git -C ../nowhere push", ["/w/s/../nowhere"])):
            with self.subTest(command=command):
                self.assertEqual(push_places(command, is_directory=there), places)

    def test_a_subshell_a_pipeline_and_a_background_list_keep_their_moves_to_themselves(self):
        for command, places in (("(cd ../other && git push); git push", ["/w/other", "/w/s"]),
                                ("(cd ../other; git push) && git push", ["/w/other", "/w/s"]),
                                ("(cd ../other)>log; git push", ["/w/s"]),
                                ("(cd ../a; (cd ../b; git push); git push); git push", ["/w/b", "/w/a", "/w/s"]),
                                ("cd ../other | cat; git push", ["/w/s"]),
                                ("cd ../other |& cat; git push", ["/w/s"]),
                                ("git push | cd ../x; git push", ["/w/s", "/w/s"]),
                                ("cd ../other & git push", ["/w/s"]),
                                ("cd ../other && git push & git push", ["/w/other", "/w/s"])):
            with self.subTest(command=command):
                self.assertEqual(push_places(command), places)

    def test_a_push_after_a_body_is_placed_as_each_reading_places_it(self):
        """The whole command moves the shell by a cd in a body, as this module
        reads it; with the body cut out it runs no cd, as bash runs none, and
        that reading adds no push the whole placed in the same shell (F25)."""
        self.assertEqual(push_places("cat <<'EOF'\ncd ../x\nEOF\ngit push"), ["/w/x", "/w/s"])
        self.assertEqual(push_places("cat <<'EOF'\nIt's\nEOF\ngit push; git push"), ["/w/s", "/w/s"])


class CloneTest(unittest.TestCase):
    """Each push is judged in each clone it may run in (guard.refused_push,
    F21): its current branch and its claim files are that clone's, each
    clone asked once; a push after a move is judged also where the command
    starts, as if no move ran, and, by a relative -C, in the session's own
    clone too, and a push whose clone this module cannot tell, or whose
    repository a variable names, by its words and in the session's own
    clone, and one by a -C from a ~ in the session's own clone too. So
    every push is judged in the session's own clone, as before the fix,
    save one whose clone git's or env's -C names by an absolute path, or a
    relative one with no cd, pushd or popd before it, holding nothing the
    shell expands, and whose repository nothing names, which is judged
    where the -C names alone (F21's third and fourth reviews)."""

    BRANCHES = {"/w/s": ("claude/7", "main"), "/w/other": ("main", "main")}

    def setUp(self):
        self.asked = []

    def branches_of(self, place):
        self.asked.append(place)
        return self.BRANCHES.get(os.path.normpath(place), (None, "main"))

    def reader_of(self, place):
        tables = {"/w/s": {}, "/w/other": {(ORIGIN_7, "7"): CLAIM_A, ("claude/7", "7"): CLAIM_B}}
        return files_at(tables.get(os.path.normpath(place), {}))

    def refused(self, command, here="/w/s", is_directory=lambda place: True):
        return guard.refused_push(command, here, self.branches_of, self.reader_of, is_directory)

    def test_a_push_of_another_clone_s_current_branch_is_judged_by_that_branch(self):
        for command in ("git -C ../other push origin HEAD", "git -C ../other push", "cd ../other && git push",
                        "env -C ../other git push -u origin HEAD"):
            with self.subTest(command=command):
                self.assertEqual(self.refused(command), MAIN)
        for command in ("git push origin HEAD", "(cd ../other); git push", "cd ../other | cat; git push"):
            with self.subTest(command=command):
                self.assertIsNone(self.refused(command))

    def test_a_lease_is_judged_by_the_claim_files_of_the_clone_it_runs_in(self):
        """The session's own clone has not fetched a's claim, the other one
        has: until F21's fix the lease below was judged in the first, which
        cannot judge it, and git took it in the second."""
        lease = "git -C ../other push --force-with-lease origin claude/7"
        reason = self.refused(lease)
        self.assertIn("claude/7 on origin is a's claim", reason)
        self.assertIn("the branch you push claims #7 for b", reason)
        self.assertIsNone(self.refused("git push --force-with-lease origin claude/7"),
                          "the session's own clone holds no claim file to judge by")

    def test_each_place_is_asked_once(self):
        """A place as the push names it: git -C's, joined as chdir reads it,
        and the shell's own logical one may be one clone or two, and are
        asked apart."""
        self.refused("git push origin claude/7; git -C ../other push origin x; git -C ../other push origin y; "
                     "cd ../other; git push origin z; git push origin w")
        self.assertEqual(self.asked, ["/w/s", "/w/s/../other", "/w/other"])

    def test_a_push_whose_clone_this_cannot_tell_is_judged_by_its_words_and_in_the_session_s_own_clone(self):
        self.assertEqual(self.refused("cd $X && git push origin main"), MAIN, "the session's own default branch")
        self.assertIsNone(self.refused("cd $X && git push"), "the session's own claim branch, as before the fix")
        self.assertEqual(self.asked, ["/w/s", "/w/s"], "once a command, for its words and as the push's clone")
        self.assertEqual(self.refused("cd $X && git push --force origin claude/7"), FORCE)
        self.assertEqual(self.refused("cd $X && git push origin HEAD", "/w/other"), MAIN + guard.UNMOVED,
                         "the session's own clone is on main, as the push may be")
        self.assertEqual(self.refused('git -C "$(git rev-parse --show-toplevel)" push origin HEAD', "/w/other"),
                         MAIN + guard.UNTOLD)
        self.assertEqual(self.refused("GIT_DIR=../s/.git git push --force-with-lease origin claude/7", "/w/other"),
                         self.refused("git push --force-with-lease origin claude/7", "/w/other") + guard.UNTOLD)

    def test_a_push_after_a_move_is_judged_where_the_command_starts_too(self):
        """A cd this module reads and the shell does not run, in a
        here-document's body, after a test that fails, in a function never
        called, sent the push to a clone that holds no claim file, which
        passed a lease that git takes from the session's own (F21's third
        review: a regression against 0.5.0, which judged every push there)."""
        lease = "git push --force-with-lease origin claude/7"
        held = self.refused(lease, "/w/other")
        self.assertIn("claude/7 on origin is a's claim", held)
        for moves in ("cat > /dev/null <<'EOF'\ncd ../s\nEOF\n", '[ -n "" ] && cd ../s; ', "f() { cd ../s; }; ",
                      "true || cd ../s; ", "{ cd ../s; } | cat; ", "pushd ../s; popd; popd; ",
                      "if false; then cd ../s; fi; ", "(case x in x) cd ../s;; esac); ", "cd ../s extra; ",
                      "cd ../s/missing/..; ", 'cd "~"; '):
            with self.subTest(moves=moves):
                self.assertEqual(self.refused(moves + lease, "/w/other"), held + guard.UNMOVED)
        self.assertEqual(self.refused("cd ../other && " + lease), held, "judged where the shell's cd takes it")
        self.assertEqual(self.refused("cd ../s && git push origin HEAD", "/w/other"), MAIN + guard.UNMOVED,
                         "what it costs: a cd the shell makes, refused for what the session's own clone shows")
        self.assertIsNone(self.refused("git -C ../s push origin HEAD", "/w/other"), "git -C is judged where it runs")
        with mock.patch.object(guard, "push_places", lambda argv, shell, here: [guard.Reading(
                guard.push_place(argv, shell.directory))]):
            self.assertEqual(self.refused("cat > /dev/null <<'EOF'\ncd ../s\nEOF\n" + lease, "/w/other"), held,
                             "since F25's fix the reading with the body cut out judges it where it starts")
            with mock.patch.object(guard, "here_document_bodies", lambda command: []):
                self.assertIsNone(self.refused("cat > /dev/null <<'EOF'\ncd ../s\nEOF\n" + lease, "/w/other"),
                                  "as built until F21's third review: judged in s alone, which shows no claim file")

    def test_a_relative_minus_c_after_a_move_is_judged_in_the_session_s_own_clone_too(self):
        """A cd into a directory the command makes first reads as failed,
        and one behind a test that fails or in a here-document's body as
        made, so after any cd, pushd or popd a relative -C may name another
        clone than the one it runs in, the session's own among them; the
        push is judged there too, where an absolute -C names its clone
        wherever the shell stands (F21's fourth review: each of these
        passed, and bash pushed main, or took a's claim, from the session's
        own clone)."""
        def there(place):
            return not os.path.normpath(place).startswith(("/w/other/tmpdir", "/w/other/build"))

        held = self.refused("git push --force-with-lease origin claude/7", "/w/other")
        held_head = self.refused("git push --force-with-lease origin HEAD:claude/7", "/w/other")
        self.assertIn("claude/7 on origin is a's claim", held)
        self.assertIn("claude/7 on origin is a's claim", held_head)
        for command, reason in (
                ("mkdir -p tmpdir && cd tmpdir && git -C .. push origin HEAD", MAIN),
                ("mkdir -p build && cd build && env -C .. git push origin HEAD", MAIN),
                ("mkdir -p build && cd build && cmake .. >/dev/null 2>&1; git -C .. push", MAIN),
                ("mkdir -p build/out && cd build/out && git -C ../.. push --force-with-lease origin claude/7", held),
                ("cd sub; false && cd /tmp; git -C .. push --force-with-lease origin HEAD:claude/7", held_head),
                ("cd sub\ncat > /dev/null <<'EOF'\ncd /tmp\nEOF\n"
                 "git -C .. push --force-with-lease origin HEAD:claude/7", held_head)):
            with self.subTest(command=command):
                self.assertEqual(self.refused(command, "/w/other", there), reason + guard.UNMOVED)
        for command in ("cd /tmp && git -C /w/s push origin HEAD", "cd /tmp && env -C /w/s git push origin HEAD",
                        "pushd /tmp && git -C /w/s/.. -C s push origin HEAD"):
            with self.subTest(command=command):
                self.assertIsNone(self.refused(command, "/w/other"),
                                  "an absolute -C is judged where it names alone, whatever cd came before")
        self.assertEqual(self.refused("cd /tmp && git -C ../w/s push origin HEAD", "/w/other"), MAIN + guard.UNMOVED,
                         "what it costs: a relative -C after a cd the shell makes, refused for what the session's "
                         "own clone shows")
        with mock.patch.object(guard, "after_a_move", lambda argv, shell: False):
            self.assertIsNone(self.refused("mkdir -p tmpdir && cd tmpdir && git -C .. push origin HEAD", "/w/other",
                                           there), "as built until F21's fourth review: judged in /w alone")

    def test_a_variable_that_names_the_repository_has_the_push_judged_in_the_session_s_own_clone(self):
        """GIT_DIR, or GIT_REFERENCE_BACKEND, exported, or set alone, where it
        may (F29), names the repository whatever cd or -C comes after, so the push is judged by
        its words and in the session's own clone, as one with GIT_DIR on it
        is, with UNTOLD's advice and never UNMOVED's, a cd before it or not
        (F21's fourth review: after the export an absolute -C was judged
        where it names alone, and passed, though git took the refs GIT_DIR
        named)."""
        lease = "push --force-with-lease origin claude/7"
        held = self.refused("git " + lease, "/w/other")
        for command, reason in (("export GIT_DIR=/w/other/.git; git -C /w/s " + lease, held),
                                ('export GIT_DIR="$PWD/.git"; git -C /w/s push origin HEAD', MAIN),
                                ('export GIT_DIR="$PWD/.git"; env -C /w/s git push origin HEAD', MAIN),
                                ("GIT_DIR=/w/other/.git; git -C /w/s " + lease, held),
                                ("export GIT_DIR=/w/other/.git; cd /w/s && git " + lease, held),
                                ("cd /w/s; export GIT_DIR=/w/other/.git; git push origin HEAD", MAIN),
                                ("declare -x GIT_REFERENCE_BACKEND=files:///w/other/.git; git -C /w/s " + lease, held),
                                ("GIT_REFERENCE_BACKEND=files:///w/other/.git git -C /w/s " + lease, held),
                                ("export GIT_DIR=.git; git push origin HEAD", MAIN)):
            with self.subTest(command=command):
                self.assertEqual(self.refused(command, "/w/other"), reason + guard.UNTOLD)
        self.assertIsNone(self.refused("(export GIT_DIR=/w/other/.git); git -C /w/s " + lease, "/w/other"),
                          "the subshell's export ends at its ), and the push runs in s")
        self.assertIsNone(self.refused("export GIT_COMMON_DIR=/w/other/.git; git -C /w/s " + lease, "/w/other"),
                          "GIT_COMMON_DIR moves no ref")
        with mock.patch.object(guard, "followed_and_unmoved", lambda argv, shell, here: (
                guard.push_place(argv, shell.directory), guard.push_place(argv, here))):
            self.assertIsNone(self.refused("export GIT_DIR=/w/other/.git; git -C /w/s " + lease, "/w/other"),
                              "as built until F21's fourth review: judged in s alone, which shows no claim file")

    def test_bash_s_tildes_for_the_shell_s_own_directories_are_places_this_cannot_tell(self):
        """~+ is where the shell stands, ~- where it stood before, and ~N,
        ~+N and ~-N are entries of its directory stack, none of which this
        module keeps, where os.path.expanduser left them directories named ~+
        and ~-: a push through one is judged by its words and in the
        session's own clone, by git's or env's -C with UNTOLD's advice and
        after a cd or pushd with UNMOVED's (F21's fourth review). ~ and ~user
        stay home directories, and ~+x, which bash leaves as written, is a
        directory of that name."""
        for path in ("~+", "~-", "~+/sub", "~-/..", "~1", "~+2", "~-0/sub"):
            with self.subTest(path=path):
                self.assertIsNone(guard.joined("/w/s", path))
                self.assertIsNone(guard.joined("/w/s", path, physical=True))
                for command in (f"git -C {path} push", f"env -C {path} git push", f"cd {path} && git push",
                                f"pushd {path} && git push", f"cd /w/other && git -C {path} push"):
                    self.assertEqual(push_places(command), [None], command)
                self.assertEqual(self.refused(f"git -C {path} push origin HEAD", "/w/other"), MAIN + guard.UNTOLD)
                self.assertEqual(self.refused(f"env -C {path} git push origin HEAD", "/w/other"), MAIN + guard.UNTOLD)
                self.assertEqual(self.refused(f"cd {path} && git push origin HEAD", "/w/other"), MAIN + guard.UNMOVED)
        self.assertEqual(guard.joined("/w/s", "~"), HOME)
        self.assertEqual(guard.joined("/w/s", "~+x", physical=True), "/w/s/~+x")
        self.assertEqual(guard.joined("/w/s", "a/~-"), "/w/s/a/~-")

    def test_a_minus_c_from_a_tilde_is_judged_in_the_session_s_own_clone_too(self):
        """This module reads a ~ from the hook's own HOME, while a HOME the
        command sets before it, assigned or exported, sends the shell
        elsewhere, and quotes, which this module does not keep, leave a ~ as
        written, so a push by a -C from a ~ is judged where this module
        reads it and in the session's own clone too, with UNTOLD's advice
        (F21's fourth review: with HOME set in the command, a lease git
        takes from the session's own clone was judged in the hook's ~/other
        alone, and passed). What it costs, a push by git -C ~/x from a
        session on main refused as a push to main, is what 0.5.0's guard
        did. An absolute -C after the ~ names the clone alone, and a cd to
        a ~ is judged where the command starts too, as after any move."""
        lease = "push --force-with-lease origin claude/7"
        held = self.refused("git " + lease, "/w/other")
        for command, reason in (("HOME=/w; git -C ~/other " + lease, held),
                                ("export HOME=/w; git -C ~/other " + lease, held),
                                ("HOME=/w; env -C ~/other git " + lease, held),
                                ('git -C "~/other" ' + lease, held),
                                ("git -C ~/x push origin HEAD", MAIN),
                                ("git -C ~ push origin HEAD", MAIN),
                                ("git -C ~root/x push origin HEAD", MAIN),
                                ("env --chdir=~/x git push origin HEAD", MAIN),
                                ("git -C /w/s -C ~/x push origin HEAD", MAIN),
                                ("git -C ~/x -C sub push origin HEAD", MAIN),
                                ("cd /tmp && git -C ~/x push origin HEAD", MAIN)):
            with self.subTest(command=command):
                self.assertEqual(self.refused(command, "/w/other"), reason + guard.UNTOLD)
        for command in ("git -C ~/x -C /w/s push origin HEAD", "env -C ~/x git -C /w/s push origin HEAD",
                        "git -C /w/s push origin HEAD", "git -C ../s push origin HEAD"):
            with self.subTest(command=command):
                self.assertIsNone(self.refused(command, "/w/other"),
                                  "an absolute -C, or a relative one with no move before it, names its clone alone")
        self.assertEqual(self.refused("cd ~/x && git push origin HEAD", "/w/other"), MAIN + guard.UNMOVED,
                         "a cd to a ~ is judged where the command starts too, as after any move")
        with mock.patch.object(guard, "from_a_tilde", lambda argv: False):
            for command in ("HOME=/w; git -C ~/other " + lease, "export HOME=/w; git -C ~/other " + lease):
                with self.subTest(command=command):
                    self.assertIsNone(self.refused(command, "/w/other"),
                                      "as built at a71a391: judged in the hook's ~/other alone, which is no clone")


class RunTest(unittest.TestCase):
    """What the hook answers for one tool call, with git's two answers
    about the branches held still: run() is what cli.py's guard subcommand
    calls after decoding stdin."""

    def run_guard(self, command):
        payload = {"tool_input": {"command": command}, "cwd": str(ROOT)}
        with mock.patch.object(guard, "branches", return_value=("claude/7", "main")):
            return guard.run(payload, str(ROOT))

    def test_forbidden_push_is_refused_with_a_reason(self):
        code, message = self.run_guard("git push origin main")
        self.assertEqual(code, 2)
        self.assertIn("pull requests", message)

    def test_allowed_push_passes(self):
        code, message = self.run_guard("git push -u origin claude/7")
        self.assertEqual(code, 0)
        self.assertEqual(message, "")

    def test_push_to_main_on_a_later_line_is_refused(self):
        code, message = self.run_guard("git add -A\ngit commit -m x\ngit push origin main")
        self.assertEqual(code, 2)
        self.assertIn("pull requests", message)

    def test_claim_push_then_a_line_naming_main_passes(self):
        for command in ("git push -u origin claude/7\ngit fetch origin main",
                        "git push -u origin claude/7\n# then open the pull request against main",
                        "git push -u origin claude/7 # not main"):
            self.assertEqual(self.run_guard(command), (0, ""), command)

    def test_a_here_document_body_is_read_as_commands(self):
        """The trade the docstring states: the hook reads the command whole,
        bodies and all, beside its reading with the bodies cut out (F25), so
        a body line that starts a push to main is refused and the person
        rephrases it, while a body that names no push passes as before."""
        refused, message = self.run_guard("git commit -F - <<'EOF'\nClaim #7\n\ngit push origin main\nEOF\n"
                                          "git push -u origin claude/7")
        self.assertEqual(refused, 2)
        self.assertIn("pull requests", message)
        self.assertEqual(self.run_guard("git commit -F - <<'EOF'\nClaim #7\n\nThe board first.\nEOF\n"
                                        "git push -u origin claude/7"), (0, ""))

    def test_a_push_behind_a_prefix_is_judged_as_the_push_itself(self):
        refused = self.run_guard("git push origin main")
        self.assertEqual(refused[0], 2)
        for prefix in ("FOO=1 ", "env ", "command ", "nice ", "time ", "env FOO=1 nice -n 5 "):
            self.assertEqual(self.run_guard(prefix + "git push origin main"), refused, prefix)
            self.assertEqual(self.run_guard(prefix + "git push -u origin claude/7"), (0, ""), prefix)
        self.assertEqual(self.run_guard("time git push origin +claude/7"), (2, PLUS))

    def test_a_push_inside_a_compound_command_is_judged_as_the_push_itself(self):
        # The reserved words run nothing of their own, so the push after
        # one runs; bash 5.2 ran each of these.
        for command in ("! git push origin main", "if git push origin main; then echo ok; fi",
                        "if ! git push origin main; then echo failed; fi",
                        "while ! git push origin main; do sleep 1; done", "until git push origin main; do sleep 5; done",
                        "for i in 1 2; do git push origin main; done", "if false; then :; else git push origin main; fi",
                        "if false; then :; elif git push origin main; then :; fi", "{ git push origin main; }",
                        "false || { git push origin main; }", "f() { git push origin main; }; f",
                        "function f { git push origin main; }; f"):
            self.assertEqual(self.run_guard(command), (2, MAIN), command)
        for command in ("if git push -u origin claude/7; then echo ok; fi",
                        "for i in 1 2 3; do git push origin claude/7 && break; sleep 2; done",
                        "while read -r b; do git push origin \"$b\"; done", "do_not=1 echo git push origin main"):
            self.assertEqual(self.run_guard(command), (0, ""), command)

    def test_a_push_behind_exec_nohup_or_timeout_is_judged_as_the_push_itself(self):
        for command in ("exec git push origin main", "exec -a pusher git push origin main",
                        "exec -cla pusher git push origin main", "nohup git push origin main",
                        "timeout 60 git push origin main", "timeout -s KILL -k 5 1m git push origin main",
                        "timeout --signal=TERM --kill-after 5 10 git push origin main", "timeout -- 60 git push origin main",
                        "FOO+=1 git push origin main", "env -iu HOME git push origin main"):
            self.assertEqual(self.run_guard(command), (2, MAIN), command)
        self.assertEqual(self.run_guard("timeout 60 git push -u origin claude/7"), (0, ""))

    def test_a_branch_written_as_git_resolves_it_is_judged_as_that_branch(self):
        for command in ("git push origin heads/main", "git push origin HEAD:heads/main",
                        "git push --delete origin heads/main"):
            self.assertEqual(self.run_guard(command), (2, MAIN), command)
        self.assertEqual(self.run_guard("git push origin :heads/board"), (2, BOARD))
        self.assertEqual(self.run_guard("git push -u origin heads/claude/7"), (0, ""))

    def test_a_wrapper_this_module_does_not_name_is_out_of_reach(self):
        """The trade the docstring states: a wrapper this module does not name
        is no git, so the push behind it passes, and branch protection stands
        behind it. What bash -c and eval run is read since F32's fix
        (HandedTextTest), as env -S is since F28's (EnvAssignmentTest)."""
        for command in ("sudo git push origin main", "echo main | xargs git push origin"):
            self.assertEqual(self.run_guard(command), (0, ""), command)

    def test_command_without_push_passes_without_git(self):
        with mock.patch.object(guard, "branches", side_effect=AssertionError("git was asked")):
            self.assertEqual(guard.run({"tool_input": {"command": "git status"}}), (0, ""))

    def test_git_is_asked_in_the_payloads_cwd_before_the_callers(self):
        asked = []

        def remember(cwd):
            asked.append(cwd)
            return "claude/7", "main"
        with mock.patch.object(guard, "branches", side_effect=remember):
            guard.run({"tool_input": {"command": "git push"}, "cwd": "/session"}, "/hook")
            guard.run({"tool_input": {"command": "git push"}}, "/hook")
            guard.run({"tool_input": {"command": "git push"}})
        self.assertEqual(asked, ["/session", "/hook", "."])

    def test_broken_payload_passes(self):
        for payload in (None, "not json", [], {}, {"tool_input": None}, {"tool_input": {}}):
            self.assertEqual(guard.run(payload), (0, ""), repr(payload))

    def test_a_payload_of_the_wrong_shape_passes_without_git(self):
        """The old main() crashed on these, which Claude Code reads as a
        hook error and lets the call run; run() says so without raising."""
        shapes = ({"tool_input": "git push origin main"},
                  {"tool_input": ["git push origin main"]},
                  {"tool_input": {"command": ["git", "push", "origin", "main"]}},
                  {"tool_input": {"command": 7}})
        with mock.patch.object(guard, "branches", side_effect=AssertionError("git was asked")):
            for payload in shapes:
                self.assertEqual(guard.run(payload), (0, ""), repr(payload))

    def test_a_payload_cwd_that_is_not_text_is_passed_over(self):
        asked = []

        def remember(cwd):
            asked.append(cwd)
            return "claude/7", "main"
        with mock.patch.object(guard, "branches", side_effect=remember):
            for where in (7, "", None, ["/x"]):
                guard.run({"tool_input": {"command": "git push"}, "cwd": where}, "/hook")
        self.assertEqual(asked, ["/hook"] * 4)


GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "LC_ALL": "C",
           "GIT_TERMINAL_PROMPT": "0", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
           "GIT_CONFIG_COUNT": "5", "GIT_CONFIG_KEY_0": "gc.auto", "GIT_CONFIG_VALUE_0": "0",
           "GIT_CONFIG_KEY_1": "gc.autoDetach", "GIT_CONFIG_VALUE_1": "false",
           "GIT_CONFIG_KEY_2": "maintenance.auto", "GIT_CONFIG_VALUE_2": "false",
           "GIT_CONFIG_KEY_3": "maintenance.autoDetach", "GIT_CONFIG_VALUE_3": "false",
           "GIT_CONFIG_KEY_4": "receive.autogc", "GIT_CONFIG_VALUE_4": "false"}


def git(cwd, *args):
    done = subprocess.run(["git", *args], cwd=cwd, env=GIT_ENV, capture_output=True, text=True, check=True)
    return done.stdout.strip()


def git_version():
    """The version of the git on PATH, as (major, minor), or (0, 0) where it
    says none."""
    said = subprocess.run(["git", "--version"], capture_output=True, text=True).stdout
    found = re.search(r"(\d+)\.(\d+)", said)
    return (int(found.group(1)), int(found.group(2))) if found else (0, 0)


def dry_run(command, where):
    """What bash prints for command with its push made a dry run, from
    where: the refs git would send, and whether it would force them."""
    dry = command.replace(" push ", " push --dry-run --porcelain ")
    return subprocess.run(["bash", "-c", dry], cwd=where, env=GIT_ENV, capture_output=True, text=True).stdout


def scratch_clone(where):
    """A clone as b's session holds one: on origin claude/7 is a's claim,
    finished (the remote-tracking ref's tip dropped the claim file a's
    first commit added); the local claude/7 is b's own claim of #7 from
    main, finished the same way."""
    git(where, "init", "-q", "-b", "main")
    for key in ("gc.auto", "gc.autoDetach", "maintenance.auto", "maintenance.autoDetach", "receive.autogc"):
        git(where, "config", key, "0" if key == "gc.auto" else "false")
    claim = Path(where, "docs", "agents", "claims")
    Path(where, "README.md").write_text("base\n")
    git(where, "add", "."); git(where, "commit", "-q", "-m", "base")
    for worker, text, base in (("a", CLAIM_A, "main"), ("b", CLAIM_B, "main"), ("b", CLAIM_B, "a-done")):
        git(where, "checkout", "-q", "-B", "claude/7", base)
        claim.mkdir(parents=True, exist_ok=True)
        (claim / "7.md").write_text(text)
        git(where, "add", "."); git(where, "commit", "-q", "-m", f"{worker} claims 7")
        git(where, "update-ref", f"refs/tags/{worker}-claim", git(where, "rev-parse", "HEAD"))
        git(where, "rm", "-q", "docs/agents/claims/7.md"); git(where, "commit", "-q", "-m", f"{worker} finishes")
        git(where, "update-ref", f"refs/tags/{worker}-done", git(where, "rev-parse", "HEAD"))
        if worker == "a":
            git(where, "update-ref", ORIGIN_7, git(where, "rev-parse", "HEAD"))
    # The last pass left claude/7 as b's claim made again over a's merged
    # history, so a's add of the file is in its history under b's.


class ClaimFileReaderTest(unittest.TestCase):
    """The reader over a real clone: a claim file at a ref's tip, else where
    its history first added it, else None."""

    def setUp(self):
        self.where = tempfile.TemporaryDirectory()
        scratch_clone(self.where.name)
        self.read = guard.claim_file_reader(self.where.name)

    def tearDown(self):
        self.where.cleanup()

    def test_the_file_at_the_tip_then_where_the_history_first_added_it(self):
        self.assertEqual(self.read("a-claim", "7"), CLAIM_A.strip(), "at the tip")
        self.assertEqual(self.read(ORIGIN_7, "7"), CLAIM_A.strip(), "the tip dropped it; where it was first added")
        self.assertEqual(self.read("b-done", "7"), CLAIM_B.strip())
        self.assertEqual(self.read("claude/7", "7"), CLAIM_B.strip(),
                         "the issue claimed again after a's claim merged: the last add, b's, not the first, a's")
        self.assertEqual(self.read("HEAD", "7"), CLAIM_B.strip())
        self.assertEqual(self.read(git(self.where.name, "rev-parse", "b-claim"), "7"), CLAIM_B.strip())

    def test_a_ref_that_starts_with_a_dash_is_a_ref_to_git_and_not_an_option(self):
        self.assertIsNone(self.read("--output=/tmp/guard-test-never-written", "7"))
        self.assertIsNone(self.read("-q", "7"))
        self.assertFalse(Path("/tmp/guard-test-never-written").exists())

    def test_none_for_a_ref_the_clone_lacks_or_a_file_no_commit_added(self):
        self.assertIsNone(self.read("refs/remotes/origin/claude/8", "8"))
        self.assertIsNone(self.read("claude/7", "8"))
        self.assertIsNone(self.read("main", "7"))

    def test_the_hook_refuses_the_lease_and_passes_the_holder_s_own(self):
        payload = {"tool_input": {"command": "git push --force-with-lease origin claude/7"}, "cwd": self.where.name}
        with mock.patch.object(guard, "branches", return_value=("claude/7", "main")):
            code, reason = guard.run(payload)
            self.assertEqual(code, guard.REFUSE)
            self.assertIn("claude/7 on origin is a's claim", reason)
            self.assertIn("the branch you push claims #7 for b", reason)
            variable = {"tool_input": {"command": "git push --force-with-lease=claude/7:$TIP origin claude/7"},
                        "cwd": self.where.name}
            self.assertEqual(guard.run(variable)[0], guard.REFUSE, "a lease on a commit the shell expands")
            git(self.where.name, "update-ref", ORIGIN_7, "b-claim")
            self.assertEqual(guard.run(payload), (guard.PASS, ""), "origin's claim file names b too")
            self.assertEqual(guard.run(variable), (guard.PASS, ""))
            plain = {"tool_input": {"command": "git push origin claude/7"}, "cwd": self.where.name}
            self.assertEqual(guard.run(plain), (guard.PASS, ""), "a plain push reads no claim file")


def settle(where):
    """No automatic maintenance in a scratch repository, set in its own
    configuration, since git does not hand the environment's to the
    receive-pack it starts for a local remote."""
    for key in ("gc.auto", "gc.autoDetach", "maintenance.auto", "maintenance.autoDetach", "receive.autogc"):
        git(where, "config", key, "0" if key == "gc.auto" else "false")


class OtherCloneTest(unittest.TestCase):
    """F21 over real clones: b's session works in its clone s, on its own
    claim claude/8, made before a claimed #7, so s has never seen a's
    claim; b's second clone of the same repository, other, beside it, was
    made after a's claim and stands on main. A push run in other through
    git -C is judged in other."""

    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        root = Path(self.scratch.name)
        origin, seed, self.session, self.other = root / "origin.git", root / "seed", root / "s", root / "other"
        git(root, "init", "-q", "--bare", "-b", "main", str(origin))
        settle(origin)
        git(root, "clone", "-q", str(origin), str(seed))
        settle(seed)
        Path(seed, "README.md").write_text("base\n")
        git(seed, "add", "."); git(seed, "commit", "-q", "-m", "base"); git(seed, "push", "-q", "origin", "HEAD:main")
        git(root, "clone", "-q", str(origin), str(self.session))
        settle(self.session)
        git(self.session, "switch", "-q", "-c", "claude/8")
        git(seed, "switch", "-q", "-c", "claude/7")
        Path(seed, "docs", "agents", "claims").mkdir(parents=True)
        Path(seed, "docs", "agents", "claims", "7.md").write_text(CLAIM_A)
        git(seed, "add", "."); git(seed, "commit", "-q", "-m", "a claims 7"); git(seed, "push", "-q", "origin", "claude/7")
        git(root, "clone", "-q", str(origin), str(self.other))
        settle(self.other)

    def tearDown(self):
        self.scratch.cleanup()

    def hook(self, command, where=None):
        return guard.run({"tool_input": {"command": command}, "cwd": str(where or self.session)})

    def claim_of_b_in_other(self):
        """b's claim of #7 made in other, which fetched a's: git would take
        a lease of it there."""
        git(self.other, "switch", "-q", "-c", "claude/7", "main")
        Path(self.other, "docs", "agents", "claims").mkdir(parents=True)
        Path(self.other, "docs", "agents", "claims", "7.md").write_text(CLAIM_B)
        git(self.other, "add", "."); git(self.other, "commit", "-q", "-m", "b claims 7")

    def test_a_push_of_the_other_clone_s_main_is_refused(self):
        for command in ("git -C ../other push origin HEAD", "cd ../other && git push origin HEAD"):
            with self.subTest(command=command):
                self.assertEqual(self.hook(command), (guard.REFUSE, MAIN))
        self.assertEqual(self.hook("git push -u origin HEAD"), (guard.PASS, ""), "the session's own claim")
        with mock.patch.object(guard, "push_place", lambda argv, here: here):
            self.assertEqual(self.hook("git -C ../other push origin HEAD"), (guard.PASS, ""),
                             "as built until F21's fix: HEAD read as the session's claude/8")

    def test_a_lease_from_the_clone_that_fetched_another_s_claim_is_refused(self):
        self.claim_of_b_in_other()
        dry = subprocess.run(["git", "push", "--dry-run", "--porcelain", "--force-with-lease", "origin", "claude/7"],
                             cwd=self.other, env=GIT_ENV, capture_output=True, text=True)
        self.assertEqual(dry.returncode, 0, "git itself would take a's claim: the lease holds in other")
        self.assertIn("(forced update)", dry.stdout)
        lease = "git -C ../other push --force-with-lease origin claude/7"
        code, reason = self.hook(lease)
        self.assertEqual(code, guard.REFUSE)
        self.assertIn("claude/7 on origin is a's claim", reason)
        with mock.patch.object(guard, "push_place", lambda argv, here: here):
            self.assertEqual(self.hook(lease), (guard.PASS, ""),
                             "as built until F21's fix: judged in s, which holds no claim file of #7")

    def test_a_push_through_env_s_abbreviated_options_is_judged_in_the_clone_env_runs_it_in(self):
        """env reads --ch as --chdir and --uns as --unset, each with its
        value, so from s these run git in other, which pushes its main and,
        once b has claimed #7 there, takes a's claim; until F26's fix the
        hook read --ch and --uns as flags and the word after each as the
        command, and passed them, and read --c=../other as no move, judging
        the push in s, on its own claim claude/8."""
        main = "env --uns HOME --c=../other git push origin HEAD"
        self.assertIn("refs/heads/main", dry_run(main, self.session), "env runs git in other")
        self.assertEqual(self.hook(main), (guard.REFUSE, MAIN))
        self.claim_of_b_in_other()
        lease = "env --ch ../other git push --force-with-lease origin claude/7"
        self.assertIn("(forced update)", dry_run(lease, self.session), "git would take a's claim from other")
        code, reason = self.hook(lease)
        self.assertEqual(code, guard.REFUSE)
        self.assertIn("claude/7 on origin is a's claim", reason)
        with mock.patch.object(guard, "long_option_of", named_in_full):
            for command in (main, lease):
                with self.subTest(command=command):
                    self.assertEqual(self.hook(command), (guard.PASS, ""),
                                     "as built until F26's fix: the word after --uns or --ch read as the command")
        with mock.patch.object(guard, "names_chdir", lambda word: word.partition("=")[0] == "--chdir"):
            for command in (main, lease):
                with self.subTest(command=command):
                    self.assertEqual(self.hook(command), (guard.PASS, ""),
                                     "--c= and --ch read as no move: judged in s, on its own claim")

    def test_a_push_behind_env_s_assignments_and_split_string_is_judged_in_the_clone_it_runs_in(self):
        """From s, env runs git in other behind a word it reads as an
        assignment, as 1x=2, and behind a string -S splits, and env
        GIT_DIR=x alone sets nothing in the shell, so the lease after it
        runs in other too; until F28's fix the hook read 1x=2 and the
        string as the command env runs and passed both, and judged the
        lease after env GIT_DIR=x in s alone, which never fetched a's
        claim."""
        main = "env 1x=2 git -C ../other push origin HEAD"
        self.assertIn("refs/heads/main", dry_run(main, self.session), "env runs git in other")
        self.assertEqual(self.hook(main), (guard.REFUSE, MAIN))
        self.claim_of_b_in_other()
        leases = ("env A-B=1 git -C ../other push --force-with-lease origin claude/7",
                  "env -S 'git -C ../other push --force-with-lease origin claude/7'",
                  "env GIT_DIR=x; git -C ../other push --force-with-lease origin claude/7")
        for lease in leases:
            with self.subTest(lease=lease):
                self.assertIn("(forced update)", dry_run(lease, self.session), "git would take a's claim")
                code, reason = self.hook(lease)
                self.assertEqual(code, guard.REFUSE)
                self.assertIn("claude/7 on origin is a's claim", reason)
        for name, replacement, command in (
                ("env_assigns", lambda word: bool(guard.ASSIGNMENT.match(word)), leases[0]),
                ("split_string", lambda text, unset=False: None, leases[1]),
                ("sets_the_shells_own", lambda found: True, leases[2])):
            with self.subTest(mutant=name), mock.patch.object(guard, name, replacement):
                self.assertEqual(self.hook(command), (guard.PASS, ""), "as built until F28's fix")

    def test_a_lease_after_a_cd_that_fails_is_judged_where_the_shell_stood(self):
        """From s, the shell's cd into other is made and the cd into nowhere
        fails, so the push runs from other; judged in nowhere, which shows
        nothing, and where the command starts, in s, which never fetched
        a's claim, it passed."""
        self.claim_of_b_in_other()
        lease = "cd ../other; cd ../nowhere; git push --force-with-lease origin claude/7"
        ran = subprocess.run(["bash", "-c", "cd ../other; cd ../nowhere; git rev-parse --abbrev-ref HEAD"],
                             cwd=self.session, env=GIT_ENV, capture_output=True, text=True)
        self.assertEqual(ran.stdout.strip(), "claude/7", "bash runs what follows the failed cd from other")
        code, reason = self.hook(lease)
        self.assertEqual(code, guard.REFUSE)
        self.assertIn("claude/7 on origin is a's claim", reason)
        self.assertEqual(self.hook("cd ../nowhere; git push --force-with-lease origin claude/7", self.other)[0],
                         guard.REFUSE)
        with mock.patch.object(guard, "reached", lambda shell, target, stack, is_directory: guard.Shell(target, stack)):
            self.assertEqual(self.hook(lease), (guard.PASS, ""),
                             "as built until F21's second review: judged in ../nowhere, which shows nothing")

    def test_a_lease_after_a_cd_in_a_here_document_s_body_is_judged_where_the_shell_stands(self):
        """bash reads the body as text, so the push runs from other, whose
        lease git would take; this module reads the body's cd as one the
        shell makes, into s, and judges the push in other too (F21's
        third review: a regression against 0.5.0)."""
        self.claim_of_b_in_other()
        lease = "cat > /dev/null <<'EOF'\ncd ../s\nEOF\ngit push --force-with-lease origin claude/7"
        ran = subprocess.run(["bash", "-c", lease.replace("git push --force-with-lease origin claude/7",
                                                          "git rev-parse --show-toplevel")],
                             cwd=self.other, env=GIT_ENV, capture_output=True, text=True)
        self.assertEqual(Path(ran.stdout.strip()).resolve(), self.other.resolve())
        code, reason = self.hook(lease, self.other)
        self.assertEqual(code, guard.REFUSE)
        self.assertTrue(reason.endswith(guard.UNMOVED), reason)
        code, reason = self.hook('git -C "$(git rev-parse --show-toplevel)" push --force-with-lease origin claude/7',
                                 self.other)
        self.assertEqual(code, guard.REFUSE)
        self.assertTrue(reason.endswith(guard.UNTOLD), reason)
        self.assertEqual(self.hook("time cd ../other; git push --force-with-lease origin claude/7")[0], guard.REFUSE,
                         "bash's time runs cd in the shell itself")
        self.assertEqual(self.hook(f"cd $X; git -C {self.other} push --force-with-lease origin claude/7")[0],
                         guard.REFUSE, "an absolute path after a place this module cannot tell")

    def test_a_lease_beside_a_quote_that_never_closes_or_quoted_bodies_is_refused(self):
        """bash runs each of these leases from other, where git takes a's
        claim: it runs the push before a line it cannot read, and reads the
        bodies as text; until F25's fix the hook found no push in them."""
        self.claim_of_b_in_other()
        lease = "git push --force-with-lease origin claude/7"
        for command in (f"{lease}\necho \"unclosed",
                        f"cat > /dev/null <<'EOF'\nDon't stop\nEOF\n{lease}\ncat > /dev/null <<'EOF'\nIt's done\nEOF",
                        f"msg=\"$(cat <<'EOF'\nSay \"hi\nEOF\n)\"\n{lease}\nbody=\"$(cat <<'EOF'\nQuote\" here\nEOF\n)\""):
            with self.subTest(command=command):
                self.assertIn("(forced update)", dry_run(command, self.other), "bash runs the lease, and git takes it")
                code, reason = self.hook(command, self.other)
                self.assertEqual(code, guard.REFUSE)
                self.assertIn("claude/7 on origin is a's claim", reason)
                strict = guard.plain_text
                with mock.patch.object(guard, "plain_text", lambda command, **options: strict(command)), \
                        mock.patch.object(guard, "here_document_bodies", lambda command: []), unsubstituted():
                    self.assertEqual(self.hook(command, self.other), (guard.PASS, ""), "as built until F25's fix")

    def test_a_relative_minus_c_after_a_cd_the_hook_misreads_is_judged_where_the_command_starts_too(self):
        """bash makes tmpdir and build/out before its cd into them, which the
        hook, run first, reads as failed, and skips the cd behind a test that
        fails, which the hook reads as made: either way the -C after it names
        another directory to the hook than the one git runs in, other, from
        which git would push main or take a's claim; the hook judges the push
        in other too (F21's fourth review: until then each passed)."""
        main = "mkdir -p tmpdir && cd tmpdir && git -C .. push origin HEAD"
        for command in (main, "mkdir -p build && cd build && env -C .. git push origin HEAD",
                        "mkdir -p build && cd build && cmake .. >/dev/null 2>&1; git -C .. push"):
            with self.subTest(command=command):
                self.assertEqual(self.hook(command, self.other), (guard.REFUSE, MAIN + guard.UNMOVED))
        self.assertIn("refs/heads/main", dry_run(main, self.other), "git -C .. pushes other's main")
        self.claim_of_b_in_other()
        Path(self.other, "sub").mkdir()
        for lease in ("mkdir -p build/out && cd build/out && git -C ../.. push --force-with-lease origin claude/7",
                      "cd sub; false && cd /tmp; git -C .. push --force-with-lease origin HEAD:claude/7",
                      "cd sub\ncat > /dev/null <<'EOF'\ncd /tmp\nEOF\n"
                      "git -C .. push --force-with-lease origin HEAD:claude/7"):
            with self.subTest(lease=lease):
                code, reason = self.hook(lease, self.other)
                self.assertEqual(code, guard.REFUSE)
                self.assertIn("claude/7 on origin is a's claim", reason)
                self.assertTrue(reason.endswith(guard.UNMOVED), reason)
                self.assertIn("(forced update)", dry_run(lease, self.other), "git would take a's claim from other")
        self.assertEqual(self.hook(f"cd /tmp && git -C {self.session} push origin HEAD", self.other), (guard.PASS, ""),
                         "an absolute -C after a cd: judged in s alone, on its own claim claude/8")

    def test_an_exported_git_dir_holds_through_an_absolute_minus_c(self):
        """git pushes from the repository an exported GIT_DIR names, wherever
        -C points, so from other, on main, git pushes main, and once b has
        claimed #7 there, takes a's claim by other's refs though -C names s,
        which never fetched it; the hook judges each push by its words and
        in other, where the command starts, with UNTOLD's advice, a cd
        before it or not (F21's fourth review: judged in s alone, each
        passed)."""
        main = f'export GIT_DIR="$PWD/.git"; git -C {self.session} push origin HEAD'
        for command in (main, f'export GIT_DIR="$PWD/.git"; env -C {self.session} git push origin HEAD',
                        "export GIT_DIR=.git; git push origin HEAD"):
            with self.subTest(command=command):
                self.assertEqual(self.hook(command, self.other), (guard.REFUSE, MAIN + guard.UNTOLD))
        self.assertIn("refs/heads/main", dry_run(main, self.other))
        self.claim_of_b_in_other()
        lease = f"export GIT_DIR={self.other}/.git; git -C {self.session} push --force-with-lease origin claude/7"
        self.assertIn("(forced update)", dry_run(lease, self.other), "git takes the lease by other's refs")
        code, reason = self.hook(lease, self.other)
        self.assertEqual(code, guard.REFUSE)
        self.assertIn("claude/7 on origin is a's claim", reason)
        self.assertTrue(reason.endswith(guard.UNTOLD), reason)

    def test_a_reference_backend_moves_the_refs_and_a_common_dir_does_not(self):
        """git 2.54 and later keep the refs where GIT_REFERENCE_BACKEND says,
        so with other's, and other's objects to send, git takes a's claim
        though -C names s; the hook judges such a push in other too, on any
        git. GIT_COMMON_DIR moves no ref: git judges that lease by s's own,
        which have not fetched a's claim, as the hook does (F21's fourth
        review)."""
        self.claim_of_b_in_other()
        lease = (f"export GIT_REFERENCE_BACKEND=files://{self.other}/.git; "
                 f"git -C {self.session} push --force-with-lease origin claude/7")
        code, reason = self.hook(lease, self.other)
        self.assertEqual(code, guard.REFUSE)
        self.assertIn("claude/7 on origin is a's claim", reason)
        self.assertTrue(reason.endswith(guard.UNTOLD), reason)
        if git_version() >= (2, 54):
            objects = f"export GIT_ALTERNATE_OBJECT_DIRECTORIES={self.other}/.git/objects; "
            self.assertIn("(forced update)", dry_run(objects + lease, self.other))
        git(self.session, "branch", "claude/7")
        common = (f"export GIT_COMMON_DIR={self.other}/.git; "
                  f"git -C {self.session} push --force-with-lease origin claude/7")
        self.assertIn("[rejected] (stale info)", dry_run(common, self.other), "s's refs, which lack a's claim")
        self.assertEqual(self.hook(common, self.other), (guard.PASS, ""), "judged in s alone, as git judges it")

    def test_a_minus_c_from_a_tilde_is_judged_where_the_command_starts_too(self):
        """bash reads a ~ from the HOME the command sets, assigned or
        exported, and leaves a quoted one as written: git -C ~/other then
        runs in other, though the hook reads the ~ from its own HOME, and
        git -C "~" in other's own directory named ~, here a link back to
        other. From other, on main, git pushes main, and once b has claimed
        #7 there, takes a's claim; the hook judges each push in other too,
        where the command starts, with UNTOLD's advice (F21's fourth review:
        until then each was judged in the hook's ~/other or ~ alone, and
        passed)."""
        root = self.scratch.name
        Path(root, "home").mkdir()
        Path(self.other, ".git", "info").mkdir(exist_ok=True)
        with open(Path(self.other, ".git", "info", "exclude"), "a") as exclude:
            exclude.write("/~\n")
        Path(self.other, "~").symlink_to(".")
        pushes = (f"HOME={root}; git -C ~/other push origin HEAD",
                  f"export HOME={root}; git -C ~/other push origin HEAD", 'git -C "~" push origin HEAD')
        with mock.patch.dict(os.environ, {"HOME": str(Path(root, "home"))}):
            for command in pushes:
                with self.subTest(command=command):
                    self.assertIn("refs/heads/main", dry_run(command, self.other), "git pushes other's main")
                    self.assertEqual(self.hook(command, self.other), (guard.REFUSE, MAIN + guard.UNTOLD))
            self.claim_of_b_in_other()
            for command in pushes:
                lease = command.replace(" push origin HEAD", " push --force-with-lease origin claude/7")
                with self.subTest(lease=lease):
                    self.assertIn("(forced update)", dry_run(lease, self.other), "git would take a's claim")
                    code, reason = self.hook(lease, self.other)
                    self.assertEqual(code, guard.REFUSE)
                    self.assertIn("claude/7 on origin is a's claim", reason)
                    self.assertTrue(reason.endswith(guard.UNTOLD), reason)
                    with mock.patch.object(guard, "from_a_tilde", lambda argv: False):
                        self.assertEqual(self.hook(lease, self.other), (guard.PASS, ""),
                                         "as built at a71a391: judged where the hook reads the ~ alone")

    def test_git_s_minus_c_climbs_from_where_a_link_leads_and_cd_does_not(self):
        """s/peek leads into other: git -C peek/.. changes directory as the
        system resolves it, into other, while bash's cd peek/.. takes the
        step back along the path it keeps, into s."""
        Path(self.other, "inner").mkdir()
        Path(self.session, "peek").symlink_to(Path("..", "other", "inner"))
        for command, branch in (("git -C peek/.. rev-parse --abbrev-ref HEAD", "main"),
                                ("cd peek/.. && git rev-parse --abbrev-ref HEAD", "claude/8")):
            ran = subprocess.run(["bash", "-c", command], cwd=self.session, env=GIT_ENV, capture_output=True, text=True)
            self.assertEqual(ran.stdout.strip(), branch, command)
        self.assertEqual(self.hook("git -C peek/.. push origin HEAD"), (guard.REFUSE, MAIN))
        self.assertEqual(self.hook("cd peek/.. && git push origin HEAD"), (guard.PASS, ""))


if __name__ == "__main__":
    unittest.main()
