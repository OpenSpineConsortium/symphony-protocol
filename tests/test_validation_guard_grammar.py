"""The push guard against git's recorded answers (validation/guard_grammar.py,
DESIGN.md section 8): the file holds an answer for every argument list the
grammar generates; the guard refuses every forbidden push it can read and
passes every shape the rules allow; what it lets through is only what it
cannot read (G11b) or cannot know; and the rules read off git's offers say
what the prototype measured."""

import json
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from validation import guard_grammar as g  # noqa: E402

# Raised from 15 with F29's fix: the grammar grew by 4,129 commands, and
# each command is read in up to three more ways, its own text with each
# substitution a hole, every word unset and its braces expanded, which on 4
# processors took the judge from 11 s to 15 s; the 1,126 its first review
# added keep it near 16 s. Raised to 24 with F32's fix: its seven wrappers,
# 1,631 commands, and the bash -c wrapper's commands, now read twice, the
# second time as the text bash runs, took it to about 17 s.
BUDGET_SECONDS = 24


class TheGrammar(unittest.TestCase):
    def test_it_generates_the_parts_the_design_names(self):
        texts = [c.text for c in g.commands()]
        for shape in ("git push origin +claude/7", "git push -fu origin claude/7", "git push --al origin",
                      "git push --mirr origin", "git push origin heads/main", "FOO=1 git push origin main",
                      "bash -c 'git push origin main'", "git -c push.default=current push origin",
                      "git push --force-with-lease origin claude/7", "git push origin HEAD:claude/07",
                      "git -C . push origin main", "git --config-env user.name=HOME push origin +claude/7",
                      "git --shallow-file x push origin main", "env --uns FOO git push origin main",
                      "env --def git push origin main", "nice --adj 5 git push origin +claude/7",
                      "timeout --sig KILL 60 git push origin HEAD:board", "env 1x=2 git push origin main",
                      "env -- - A.B=1 git push origin +claude/7", "nice env x-y=1 git push origin HEAD:board",
                      "env -S 'git push origin main'", "env - --sp=x git push origin main",
                      "env -S '${NOPE} git push origin main'", "env -S '${NOPE} -u ${HOME} git push origin main'",
                      "git commit -F - <<'EOF'\nDon't stop\nEOF\ngit push origin main\ncat <<'EOF'\nIt's done\nEOF",
                      'x="$(git push origin main)"', "cat <(git push origin +claude/7)",
                      "$NOPE git push origin main", "env -S $'git push origin main'", "git $'pu\\x73h' origin main",
                      "git pu$(true)sh origin main", "git {push,} origin main", "$(which git) push origin main",
                      "git push -$(echo f) origin claude/7", "git push origin ma$(echo i)n",
                      "git push origin $\"main\"", "echo \\\n#'\ngit push origin main\n'",
                      "git pu\\\nsh origin main", "coproc git push origin main", "coproc X { git push origin main ; }",
                      "${NOPE:-git push} origin main", "git push origin ${NOPE[0]:-main}",
                      "git push origin \"${NOPE:-$'\\x6dain'}\"", "shopt -s extglob\ngit push origin @(main)",
                      "git push --no-verify origin $(echo HEAD):$(echo claude/)$(echo 7)",
                      "git push --no-verify$(true) origin claude/7", "git push origin ${A:-ma}$(echo in)",
                      "git push $(echo -)f origin claude/7", "mkdir +claude; touch +claude/7; git push origin ?claude/7",
                      "touch :main; git push origin [:]main", "X=main; git push origin :$X",
                      "eval 'git push origin main'", "sh -c 'git push origin main'", "bash <<<'git push origin main'",
                      "echo 'git push origin main' | bash", "printf '%s\\n' 'git push origin main' | sh",
                      "trap 'git push origin main' EXIT", "source /dev/stdin <<<'git push origin main'"):
            with self.subTest(shape=shape):
                self.assertIn(shape, texts)
        self.assertEqual(len(set(texts)), len(texts))
        self.assertEqual(len(g.argument_lists()), 1398, "a prefix changes what the guard reads, never git's words")
        self.assertEqual(len(texts), 76665, "since F28's fix and its reviews env's assignments and its -S, 1,631 "
                                            "more, since F24's a seventh and an eighth wrapper, a quoted and a "
                                            "process substitution, 16,776, since F29's the words bash builds, "
                                            "4,129, since its first review coproc and seven spellings, 1,126, and "
                                            "since its second five spellings, 112, and since F32's seven "
                                            "wrappers that hand a shell the command, 1,631")
        self.assertFalse(any(c.prefix in g.ABBREVIATED + g.ENV_ASSIGNED and (c.wrapper != "{}" or c.argv.startswith("-"))
                             for c in g.commands()), "an abbreviated wrapper is taken with the command alone")
        self.assertFalse(any(c.wrapper in (g.SPLIT, g.SPLIT_UNSET, g.SPLIT_MIXED) and (c.prefix or c.argv.startswith("-")) for c in g.commands()),
                         "env -S is taken with the command alone")


class GitsAnswers(unittest.TestCase):
    def test_the_file_is_ascii_and_keyed_by_gits_version(self):
        text = g.ANSWERS.read_text(encoding="ascii")
        data = json.loads(text)
        self.assertTrue(data["git"].startswith("git version "))
        self.assertEqual(sorted(data["answers"]), g.argument_lists())

    def test_git_offers_what_the_prototype_measured(self):
        answers = g.read_answers()

        def fresh(argv):
            return sorted(ref.removeprefix("refs/heads/") + " " + kind for ref, kind in answers[argv]["fresh"])

        self.assertEqual(fresh("push -f origin claude/7"), ["claude/7 forced"])
        self.assertEqual(fresh("push -fu origin claude/7"), ["claude/7 forced"])
        self.assertEqual(fresh("push origin +claude/7"), ["claude/7 forced"])
        self.assertEqual(fresh("push --force-with-lease origin claude/7"), ["claude/7 forced"])
        self.assertEqual(answers["push --force-with-lease origin claude/7"]["stale"], [], "stale info, refused by git")
        self.assertEqual(fresh("push --al origin"), ["claude/8 fast-forward", "main fast-forward"],
                         "claude/7 and feature are no fast-forward, so git does not offer them")
        self.assertEqual(fresh("push --force-with-lease origin feature"), ["feature forced"], "a lease outside claude/")
        self.assertEqual(answers["push --force-with-lease origin feature"]["stale"], [])
        forced_outside = {ref for a in answers.values() for ref, kind in a["fresh"]
                          if kind == "forced" and not ref.startswith("refs/heads/claude/")}
        self.assertEqual(forced_outside, {"refs/heads/feature"}, "the lease-outside rule has an offer to fire on")
        self.assertGreater(len(fresh("push --mirr origin")), 2)
        self.assertEqual(fresh("push origin heads/main"), ["main fast-forward"])
        self.assertEqual(fresh("push origin HEAD:main"), ["main fast-forward"])
        self.assertEqual(fresh("push origin HEAD:claude/07"), ["claude/07 create"])
        self.assertEqual(fresh("push origin claude/7"), [], "not a fast-forward: git refuses it itself")

    def test_the_rules_read_off_the_offers(self):
        forced_7 = {("refs/heads/claude/7", "forced")}
        self.assertEqual(g.rules_verdict(forced_7, set()), None, "a lease on one's own claim")
        self.assertIn("plain forced", g.rules_verdict(forced_7, forced_7))
        self.assertIn("default or the board", g.rules_verdict({("refs/heads/main", "fast-forward")}, set()))
        self.assertIn("default or the board", g.rules_verdict(set(), {("refs/heads/board", "delete")}))
        self.assertIn("lease outside", g.rules_verdict({("refs/heads/feature", "forced")}, set()))
        self.assertIn("more than one", g.rules_verdict({("refs/heads/a", "create"), ("refs/heads/b", "create")}, set()))
        self.assertIn("claims nothing", g.rules_verdict({("refs/heads/claude/07", "create")}, set()))
        self.assertEqual(g.rules_verdict({("refs/heads/claude/8", "delete")}, set()), None, "whose, only GitHub knows")
        self.assertEqual(g.rules_verdict(set(), set()), None)


class TheGuardJudged(unittest.TestCase):
    def test_it_agrees_with_git_on_every_readable_command_in_the_budget(self):
        began = time.perf_counter()
        judgement = g.judge()
        self.assertLess(time.perf_counter() - began, BUDGET_SECONDS)
        self.assertEqual(judgement.missing, ())
        self.assertEqual(judgement.failures, {}, g.report(judgement))
        self.assertEqual(judgement.commands, 76665)
        let_through = {d.why for d in judgement.classes if d.kind == "let through"}
        self.assertTrue(all("G11b" in why for why in let_through), let_through)

    def test_a_missing_answer_fails_the_lane(self):
        answers = g.read_answers()
        del answers["push -f origin claude/7"]
        judgement = g.judge(answers)
        self.assertEqual(judgement.missing, ("push -f origin claude/7",))

    def test_the_lane_bites_on_a_guard_that_passes_a_lease_outside_claude(self):
        from unittest import mock

        from sdlc_protocol import guard
        original = guard.refusal

        def lenient(args, current, default, claim_file_at=None):
            reason = original(args, current, default, claim_file_at)
            return None if reason and reason.startswith("--force-with-lease to") else reason

        with mock.patch.object(guard, "refusal", lenient):
            judgement = g.judge(commands=[c for c in g.commands() if c.prefix == "" and c.wrapper == "{}"])
        self.assertTrue(any("lease outside" in d.why for d in judgement.failures), g.report(judgement))

    def test_the_lane_bites_on_a_guard_that_passes_a_plain_force(self):
        from unittest import mock

        from sdlc_protocol import guard
        original = guard.refusal

        def lenient(args, current, default, claim_file_at=None):
            reason = original(args, current, default, claim_file_at)
            return None if reason and reason.startswith("--force overwrites") else reason

        with mock.patch.object(guard, "refusal", lenient):
            judgement = g.judge(commands=[c for c in g.commands() if c.prefix == "" and c.wrapper == "{}"])
        self.assertTrue(judgement.failures)
        self.assertTrue(any("plain forced" in d.why for d in judgement.failures))

    def test_the_lane_bites_on_a_guard_that_reads_a_wrapper_s_long_option_only_in_full(self):
        """F26: read by its whole name alone, --uns, --adj and --sig take no
        value, so the word after each is read as the command and every
        forbidden push behind it passes, as on the guard before the fix;
        --def, which names no option in full either, is read as a flag,
        and the push after it is judged."""
        from unittest import mock

        from sdlc_protocol import guard

        def in_full(word, wrapper):
            name = word[2:].partition("=")[0]
            return name if name in wrapper.long_options else None

        let_through = {}
        for prefix in g.ABBREVIATED:
            commands = [c for c in g.commands() if c.prefix == prefix]
            self.assertEqual(g.judge(commands=commands).failures, {}, prefix)
            with mock.patch.object(guard, "long_option_of", in_full):
                let_through[prefix] = sum(g.judge(commands=commands).failures.values())
        self.assertEqual(let_through, {"env --uns FOO ": 157, "env --def ": 0, "nice --adj 5 ": 157,
                                       "timeout --sig KILL 60 ": 157})


    def test_the_lane_bites_on_a_guard_that_reads_env_s_words_as_the_shell_reads_them(self):
        """F28: read as the shell reads a word, 1x=2, A.B=1 and x-y=1 are
        the command env runs, and so is the lone - after env's --, and
        with no string split env -S hides the command in one word, so
        every forbidden push behind each passes, as on the guard before
        the fix; and, from its review, --sp=x after a lone -, read past it
        as an option, splits into the command, and ${NOPE}, read only as
        written, is the command too."""
        from unittest import mock

        from sdlc_protocol import guard

        rows = [(prefix, "{}") for prefix in g.ENV_ASSIGNED] + [("", g.SPLIT), ("", g.SPLIT_UNSET)]
        let_through = {}
        for row in rows:
            commands = [c for c in g.commands() if (c.prefix, c.wrapper) == row]
            self.assertEqual(g.judge(commands=commands).failures, {}, row)
            with mock.patch.object(guard, "env_assigns", lambda word: bool(guard.ASSIGNMENT.match(word))), \
                    mock.patch.object(guard, "split_string", lambda text, unset=False: None):
                let_through[row] = sum(g.judge(commands=commands).failures.values())
        self.assertEqual(let_through, {row: 157 for row in rows})
        dashed = [c for c in g.commands() if c.prefix == "env -- - A.B=1 "]
        with mock.patch.object(guard, "past_lone_dash", lambda rest, read: None):
            self.assertEqual(sum(g.judge(commands=dashed).failures.values()), 157)
        ended = [c for c in g.commands() if c.prefix == "env - --sp=x "]
        with mock.patch.object(guard, "ends_options", lambda word: False):
            self.assertEqual(sum(g.judge(commands=ended).failures.values()), 157,
                             "F28's review: read past the lone -, --sp=x splits into the command")
        unset = [c for c in g.commands() if c.wrapper == g.SPLIT_UNSET]
        with mock.patch.object(guard, "readings_of", lambda argv: [guard.launch(argv)]):
            self.assertEqual(sum(g.judge(commands=unset).failures.values()), 157,
                             "F28's review: ${NOPE} read only as written is the command")

    def test_the_lane_bites_on_a_guard_that_reads_the_words_bash_builds_as_written(self):
        """F29: under each mutant that undoes a part of the fix, the rows
        of the grammar that part reads let forbidden pushes through, as on
        the guard before the fix, and none on the fix."""
        from validation import mutants

        rows = {"every word read set, none unset": lambda c: c.prefix in ("$NOPE ", "${NOPE:-} ", "env $NOPE "),
                "a $'...' read as a $ and a quoted span": lambda c: c.wrapper == g.ANSI_C_SPLIT,
                "a line continuation read as ending a word's start": lambda c: c.wrapper == g.CONTINUED_COMMENT,
                "arithmetic jumped over by the scan": lambda c: c.wrapper in (g.ARITHMETIC_BODY,
                                                                                 g.QUOTED_ARITHMETIC_BODY),
                "a word bash builds read as its text alone": lambda c: c.spelled and c.spelled.git != "git",
                "braces read as written": lambda c: c.spelled and c.spelled.verb == "{push,}",
                "an option bash builds read as written": lambda c: c.spelled and c.spelled.option[0],
                "a name bash builds read as written": lambda c: c.spelled and "$(" in c.spelled.name[1]}
        for name, row in rows.items():
            with self.subTest(mutant=name):
                commands = [c for c in g.commands() if row(c)]
                self.assertTrue(commands)
                self.assertEqual(g.judge(commands=commands).failures, {})
                with mutants.switched_on(mutants.MUTANTS[name]):
                    self.assertGreater(sum(g.judge(commands=commands).failures.values()), 0)

    def test_the_lane_bites_on_a_guard_without_the_first_review_s_rules(self):
        """F29's first and second reviews: under each mutant that undoes one of its
        rules, the rows of the grammar that rule reads let a forbidden push
        through, or refuse an allowed one, and none on the fix."""
        from validation import mutants

        def spelled(part, text):
            """The commands whose spelling of part, as bash reads it, holds text."""
            def holds(c):
                written = getattr(c.spelled, part, "")
                return text in (written[-1] if isinstance(written, tuple) else written)
            return lambda c: bool(c.spelled) and holds(c)

        rows = {"the hook's gate read with continuations in": spelled("verb", "\\\n"),
                "coproc read as the command": lambda c: c.prefix in g.COPROCS or c.wrapper == g.NAMED_COPROC,
                "coproc's name read as the command": lambda c: c.wrapper == g.NAMED_COPROC,
                "a ${ } read as closing at its word's end": spelled("git", "${NOPE:-git"),
                "an array's ${ } read as giving nothing": spelled("name", "[0]"),
                "a $'...' in a default read as written": spelled("name", "$'"),
                "extended patterns left unread": spelled("name", "@("),
                "a word of expansions alone read as built": spelled("name", "$(echo HEAD)"),
                "a refspec of holes read as : where each is nothing": spelled("name", "$(echo HEAD)"),
                "a built option refused after a whole flag": spelled("option", "$(true)"),
                # F29's second review.
                "a default read as a hole alone": spelled("name", "${A:-ma}"),
                "a word that may open with a dash read as no option": spelled("option", "$(echo -)f"),
                "a pattern read as giving no +": spelled("name", "?claude/7"),
                "a colon a pattern gives read as none": spelled("name", "[:]main"),
                "a colon beside one hole kept as written": spelled("name", ":$X")}
        for name, row in rows.items():
            with self.subTest(mutant=name):
                commands = [c for c in g.commands() if row(c)]
                self.assertTrue(commands)
                self.assertEqual(g.judge(commands=commands).failures, {})
                with mutants.switched_on(mutants.MUTANTS[name]):
                    self.assertGreater(sum(g.judge(commands=commands).failures.values()), 0)

    def test_the_lane_bites_on_a_guard_that_reads_a_command_whole_or_not_at_all(self):
        """F25: read whole and strictly, with no body told, the session's
        here-documents pair their bodies' apostrophes around the push, so
        every forbidden push in that wrapper passes, as on the guard before
        the fix; with the fix the wrapper is judged as the bare command."""
        from unittest import mock

        from sdlc_protocol import guard

        commands = [c for c in g.commands() if c.wrapper == g.HERE_DOCUMENTS]
        self.assertEqual(g.judge(commands=commands).failures, {})
        bare = {(c.prefix, c.argv): g.guard_refuses(c.text) for c in g.commands() if c.wrapper == "{}"}
        self.assertTrue(all(g.guard_refuses(c.text) == bare[c.prefix, c.argv] for c in commands[::7]))
        strict = guard.plain_text
        with mock.patch.object(guard, "plain_text", lambda command, **options: strict(command)), \
                mock.patch.object(guard, "here_document_bodies", lambda command: []):
            self.assertEqual(sum(g.judge(commands=commands).failures.values()), 5670)

    def test_the_lane_bites_on_a_guard_that_reads_no_substitution_apart(self):
        """F24: with no substitution read apart, a push in a double-quoted
        $( ) is part of a word and one in a <( ) a redirection's target,
        so every forbidden push in those two wrappers passes, as on the
        guard before the fix; with the fix each is judged as the bare
        command."""
        from unittest import mock

        from sdlc_protocol import guard

        bare = {(c.prefix, c.argv): g.guard_refuses(c.text) for c in g.commands() if c.wrapper == "{}"}
        for wrapper in (g.QUOTED_SUBSTITUTION, g.PROCESS_SUBSTITUTION):
            commands = [c for c in g.commands() if c.wrapper == wrapper]
            with self.subTest(wrapper=wrapper):
                self.assertEqual(g.judge(commands=commands).failures, {})
                self.assertTrue(all(g.guard_refuses(c.text) == bare[c.prefix, c.argv] for c in commands[::7]))
                with mock.patch.object(guard, "read_apart", lambda command: (command, "")):
                    self.assertEqual(sum(g.judge(commands=commands).failures.values()), 5670)


if __name__ == "__main__":
    unittest.main()
