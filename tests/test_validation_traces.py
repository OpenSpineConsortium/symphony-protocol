"""The regression traces of DESIGN.md 5.3, one per finding, F1 to F32
(validation/traces/, played by validation/replay.py), and known.json, the
record of what is red on purpose: every trace loads and plays with no
mismatch; its red results are exactly what known.json records, as built
and with each open finding's switch off in the oracle; a trace of a
finding fixed, in 0.4.1 or on main after it, is green and turns red at
the step the design's table names under the mutant that undoes the fix;
and every entry of
known.json names a trace or scenario, a step it has, a guarantee the
invariants know and a finding of DESIGN.md's section 13."""

import re
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import sdlc_protocol  # noqa: E402
from validation import invariants, known, mutants, oracle, replay, scenarios  # noqa: E402

DESIGN = (ROOT / "validation" / "DESIGN.md").read_text(encoding="ascii")
FINDINGS_IN_DESIGN = set(re.findall(r"^\*\*(F\d+)\. ", DESIGN, re.M))
BUDGET_SECONDS = 10
# A fixed finding, each mutant of validation/mutants.py that undoes a part
# of its fix, the step the trace then goes red at (numbered as played, an
# announce counting as three) and the guarantee DESIGN.md's table names;
# F6's fix has two parts, the render's sort key and the quoted path. F8's
# trace goes red at its first board run, step 13, where b's claim, its
# head dated 48 hours back, was pushed an hour before and is released
# once idleness is read by the committer date, and where the activity
# lists a push from a's head after the run read the branch, which the
# run reads the activity again for once the before side of an entry is
# ignored; at its second, step 14, where a's claim, its head dated 72
# hours ahead, a day idle by its push, is held once idleness is read by
# the committer date; at its third, step 15, where GitHub answers the
# first read of b's push with a 500 and the run reads it no more once the
# push is read once; at the run after c pushes its released head again,
# step 23, where that branch stands as a claim, not deleted, once the
# release that kept the head counts by its time alone, or only from the
# push on, since it came before; and at the last, step 25, where a's
# branch, whose release the label claimed undid, has gone a day without
# a push and is not released once a release comment holds a kept head
# whatever the labels say, and b's, the board counting its kept release,
# is released twice once no head is read as kept; and, since F8's second
# review, at step 28, where a's kept head, pushed again a day after the
# board deleted it, meets an activity a push behind whose newest entry is
# that delete, and at step 37, where c's claim commit, pushed back a day
# after a commit moved claude/3 off it, meets one whose newest entry is
# that commit's push, each claim released in the run its push started
# once a stale entry off the head dates it; and at step 29, where a's
# kept head, its release undone, is released again by a run whose
# comment GitHub refuses, and the labels stay off once the earlier
# release of the head is taken for the comment the post would have
# written; and, since F8's fix check, at the five runs after c's two
# commits dated back: at step 39, where both reads are a push behind and
# the floor is the commit's own minute, the log says the claim is read
# from its floor once a floor at the committer date is taken for later;
# at step 41, where the floor is later than a commit dated two days
# back, c's claim is released in the run its push started once the floor
# is dropped; at step 42, where the second read is refused, likewise once
# the floor is the last read's alone; at step 43, where the second read
# lists a push after the run read the branch, the log says the claim is
# read from its floor once that read is judged with no moment of the
# run; and at step 44, where the newest of two such pushes names the head
# on neither side, the run reads again once a fresh entry dates only
# where it moved the branch off the head; and, since F8's third review,
# at step 45, where the first read is two pushes behind and the second
# one, c's claim is released once the floor is the first read's alone
# or the earlier of the two; at step 47, where the read lists the
# branch's delete after the run read it, the run reads again and the
# log says the claim is read from its floor once a fresh delete dates
# nothing; and at step 49, where a's claim anew, its commit dated two
# days back, meets reads both a push behind in the run its own push
# started, it is released once the run's event is ignored; and, since F8's
# follow-up's second review, at step 53, where c has pushed claude/3 back
# to its claim commit, the head the branch's making at 101 set, and the
# run its push started reads the activity two pushes behind, listing that
# making newest, c's claim is released once such a push is trusted in
# that run. F9's
# trace goes red at its first board run, step 2, where the draft level
# with main is told it moved once the adapter reads the comparison's
# ahead_by for behind_by, and at its second, step 4, where the draft
# behind main hears nothing once the adapter takes GitHub's word alone;
# F13's at its first board run, step 4, where b's draft lands before a's,
# whose branch was made first, once the order is by number again or once
# a draft is dated by its opening; at its second, step 5, where GitHub
# refuses the first read of the activity, the run fails once the refusal
# escapes, and the drafts land by their openings once no branch is asked
# about on its own; and at its third, step 7, where GitHub refuses every
# read, c's claim, which nothing dates then, lands first once such work
# counts first. F15's at its run that fails at the comment, step 6, where
# the todo the release put on stays on once the putting back forgets it,
# and at the next run, step 7, where the release puts no todo on once the
# rule is gone, or the page that run writes leaves #1 out of the Queue once
# the snapshot forgets the todo. F16's at its second board run, step 4,
# where the draft GitHub calls clean while it is behind main hears "main
# moved", which the spec says the rules do not hold it for, once such a
# word is compared. F17's at its second board run, step 7, where a's idle
# claim is due while sam's ready pull request from a fork bears its
# branch's name: the claim is not released once that pull request is
# read as the claim's, by the coordinator, by the adapter's ready
# branches or by the board's reading of a release, and sam's pull request
# hears nothing, or is left off the page, once the release's rename is
# read as closing it; and at its last run, step 9, after main has moved
# past sam's branch, which hears no "main moved" once a pull request from
# a fork is left out of the word (F17's review). F18's at its first deal,
# step 1, where #1, which the labels of a and b give, goes to neither once
# such a task is dealt as one given alone, or a takes it before #2, given
# to it alone, once the task given alone waits for the rest; and at its
# second, step 5, after b has claimed #1, its Announce still to come, and
# c has claimed #3 and labelled it blocked, where a is told to carry b's
# claim once whose a claim is is read from the labels alone, and c its
# waiting claim once a claim labelled blocked is carried. F19's at its
# first board run, step 6, where sam, who may not write, has opened a
# pull request marked ready from a's own claude/1 before a opened its
# draft: the claim's row names sam's pull request, or the Overlaps fold
# it into the claim's work, once it is read as the claim's own; and at
# its second, step 7, where a's claim is due: it is not released once
# sam's ready pull request is read as finishing it, by the adapter's
# marking, the coordinator, the adapter's ready branches or the board's
# reading of a release, and sam's pull request, which the release's
# rename closes, is listed or spoken to once the rename is read as
# leaving it open. F20's at its first board run, step 8, where GitHub
# writes a's release comment and loses its answer, then refuses the read
# of the issue's comments after it: the release counts and the branch
# is renamed in that run once the run takes the refused read for the
# comment standing, and the run fails once the refused read is let
# through; each again at its third, step 10, for b's comment GitHub
# never wrote; and at its eighth, step 21, where GitHub refuses the
# comment on b's new claim with a 422 and then the read after it: the
# labels go back once a refused read finds no comment, where after the
# server errors of steps 8 and 10 such a read leaves them off since
# F23's fix, as one that lists none does, so a refusal is where that
# mutant differs (F23's review). F21's at b's first lease from its
# second clone, step 1, by git -C, which is taken once the guard
# ignores git's and env's -C, at its second, step 2, by cd, taken once
# the guard does not follow the shell's moves, and at its third, step
# 3, after a cd that is made and one that fails, taken once the guard
# takes the second cd as made; and at b's leases from its own clone,
# step 5, by a -C the shell expands, taken once a push is judged only
# where the shell's moves take it, or once a push whose clone cannot
# be told is judged by its words alone, the first of these until F25's
# fix taken a step sooner, at step 4, after a here-document whose body
# holds a cd, which the reading with the body cut out now judges where
# the command starts too; and, from F21's fourth review, step 6, by a
# -C relative to where a cd behind a test that fails would have taken
# the shell, taken once such a -C is judged where it names alone, step
# 7, with GIT_DIR exported before an absolute -C, taken once GIT_DIR
# is forgotten when an absolute path names a place, and step 8, by a
# -C from a ~ after HOME is set in the command, taken once such a -C
# is judged where it names alone. F22's at its first board run, step
# 11, after #1 was reopened once a's pull request merged and the
# repository deleted claude/1: claimed, in-review and worker:a stay on
# once the coordinator leaves a reopened issue as it is, and a label
# goes on after one came off once todo is put on last; at its second,
# step 23, where b's pull request, marked ready, finishes the claim on
# #1 closed and reopened, its in-review comes off once a ready pull
# request is not read; at its third, step 26, where b's merged branch
# is kept and #1 reopened, in-review stays once the claim branch is
# not read, the coordinator then planning to free #1 wholly and,
# reading claude/1 again, freeing nothing, or once in-review is left
# on where a branch stands; at its fifth, step 38, where a's merged
# pull request closed #1 after b's release and the owner reopened it,
# b's released branch still standing, claimed and worker:a stay once a
# release before the last close is read as an undo (F22's review); at
# its sixth, step 50, where a's merged branch, kept a day after its
# last commit, is not released in the run that takes its in-review off
# once the releases due are read before the freeing; at its seventh,
# step 52, where the owner put claimed back on the reopened #1 to undo
# the release that run made, claimed comes off once the released
# branch is not read; at its eighth, step 57, where the owner closed
# #1 and reopened it after that release and put claimed back again,
# claimed comes off once claimed put on after the close is read as the
# ended claim's (F22's second review); at its ninth since F22's third
# review, step 71, where b claimed #1 after it was closed and reopened
# again and the owner closed b's ready pull request unmerged and
# deleted claude/1, claimed and worker:b stay once a claim made since
# the close is read as an undo; and, since that review's review, step
# 73, where the owner put claimed back an hour after that delete to
# undo a's release, claimed comes off once any entry since the close
# is read as the claim's whenever the label went on. F23's at its
# first board run, step 16, where GitHub writes a's release comment,
# answers 502 and lists it only after the run's read of the issue's
# comments: the labels go back beside the comment once a read that
# lists none is taken for one GitHub never wrote whatever it answered;
# at its third, step 18, where the post of b's comment has no answer
# at all, once no answer is taken for a refusal; at its seventh, step
# 22, where GitHub refuses d's comment with a 422, the labels stay off
# once a refusal is taken for a comment listed late; and, from its
# review, at its ninth, step 28, where GitHub refuses the comment on
# d's second claim for a rate limit having written it and lists it
# late, the labels go back beside the comment once a rate limit's
# refusal is taken for one that wrote nothing; and, from its second
# review, at its eleventh, step 34, where GitHub refuses the comment
# on d's third claim for a rate limit having written it, then the
# client's second try with a 422, and lists it late, the labels go
# back beside the comment once a refusal after a rate limit's is read
# by its last try alone; and F26's at its first guard step, step 1,
# env --uns FOO before a push to main, which passes once a wrapper's
# long option is read only by its whole name, as do its second and
# third, nice --adj 5 and timeout --sig KILL 60; at its fourth, step
# 4, env --def before a push to main, which passes once a value an
# option may take is taken from the next word; and at b's lease from
# its second clone by env --ch, step 5, taken once env's --chdir is
# read only by its whole name. F25's at b's leases from its own clone:
# step 2, before a line whose quote never closes, taken once such a
# quote hides the command; step 3, between two here-documents whose
# bodies' apostrophes pair around it, taken once no body is told; step
# 4, between two in double-quoted substitutions, taken once a << in
# such a substitution is read as text; step 5, in a substitution in a
# body the shell expands, taken once an expanded body's substitutions
# are cut out with it; and step 6, after a body a line EOF)" ends,
# taken once a body in a substitution ends only at its delimiter's own
# line; step 7, after a body a line E and a backslash, then one OF,
# ends, taken once an expanded body's backslash-newline is kept; and
# step 8, between the here-documents of two ((cd .); ...) subshells,
# taken once every (( is read as arithmetic; and, since its second
# review, step 9, between two bodies whose substitutions close on
# their operators' own lines, taken once such a body waits for a
# newline in the substitution that closed; step 10, after a body whose
# substitution holds a body of its own with an apostrophe, taken once
# an expanded body's substitution is kept with its own bodies; step
# 11, between two double-quoted substitutions whose case patterns hold
# here-documents, taken once a pattern's ) closes its substitution;
# and step 12, between the bodies of ((echo "))"); ...) and a later
# one, taken once arithmetic's parentheses are counted inside quotes;
# and, since its third review, step 13, between two double-quoted
# substitutions that hold ${y:-)} before a here-document, taken once a
# parameter expansion is read as text, and step 14, the same with a
# backquoted case command, taken once a backquoted span is read as
# text; and, since its fourth review, step 15, after echo $${ and a
# body with an apostrophe, taken once $$ is read as a $ before what
# follows, step 16, between two double-quoted substitutions that hold
# $[ ) ] before a here-document, taken once old-style arithmetic is
# read as text, and step 17, after x=`echo "`, taken once a backquoted
# span's quotes are read as the quoting around it. Its step 1, after a
# body with an apostrophe, is the finding's first shape, which both of
# the fix's readings read, so no one mutant takes it. F24's at b's
# leases from its own clone: step 1, in out="$(...)", taken once no
# substitution is read apart; step 2, in cat <(...), taken once a
# process substitution is read as a redirection; step 3, in a $( )
# three deep in double quotes, taken once a nested substitution is left
# unread; step 4, in a backquoted span in a double-quoted $( ), taken
# once such a span is read as text; step 5, in a double-quoted $( )
# inside arithmetic, taken once arithmetic is read as no substitution;
# step 6, after a $'...' that holds an escaped apostrophe, taken once
# such a span is read as an ordinary quoted one; and, from its first
# review, step 7, in a single quote in a double-quoted ${ }, taken once
# such a quote quotes; step 9, in a single quote in $(( )), taken once
# arithmetic is read as commands; step 10, the same in $[ ], taken once
# a quote there quotes; step 11, in arithmetic on a line of an expanded
# body, taken once a body's arithmetic is left out of what it runs; and
# step 13, in the second of two substitutions whose own texts read
# alike, taken once they are told apart by their own texts alone; and
# step 14, after a here-document a backquoted span's backslash hid, taken
# once such a span's bodies are left in.
# F27's at its first release, step 16, where GitHub takes claimed off
# a's issue and answers 502, once a label whose removal failed is never
# put back, at its third, step 20, where GitHub refuses to take claimed
# off c's issue with a 422, once such a label is put back whatever
# GitHub answered, and, from its review, at its fourth, step 22, where
# claimed's removal on d's issue is refused for a rate limit having
# taken it off and answered 404 on the client's second try, once that
# 404 is read as a label never on. F28's at its first guard step, step
# 1, env 1x=2 before a push to main, which passes once only a shell
# name's assignment is read after env; at its second, step 2, env -- -
# before a forced push, which passes once env's lone - is not read; at
# its fourth, step 4, env -S with the push as its string, which passes
# once the string is not split; and at b's lease from its second clone
# by git -C after env GIT_DIR=x alone, step 7, taken once env's lone
# assignment is read as the shell's; and, from its review, at its fifth
# guard step, step 8, env - --sp=x before a push to main, which passes
# once a lone - is read past as an option; at its sixth, step 9, env -S
# with ${NOPE} before the push, which passes once the string's variables
# are read only as written; and at b's leases after /usr/bin/time
# GIT_DIR=x, step 10, and "time" GIT_DIR=x, step 11, taken once time is
# matched by its program's name, or a time the guard cannot tell is read
# as the keyword alone; and, from its second review, at its seventh guard
# step, step 12, env -S with ${NOPE} -u ${HOME} before the push, which
# passes once the string's names are read all set or all unset; and,
# from its third review, at b's lease inside an -S string of seven names,
# the last after -u, with push spelled pu""sh, step 13, taken once push is
# looked for only as written. Since F29's fix three mutants of F24 and
# F25 name new targets or switch a reading off with them: the substitution
# in double quotes is read_apart's, the quoted span ansi_c_close's, and
# arithmetic opens no substitution anywhere inside it, since the scan steps
# into it now; F25's double parentheses and backquoted quotes are undone
# with the reading of the command's own text off, which reads the words
# around a misread span as bash does whatever the rule made of the span.
# F29's at its first guard step, step 1, git $'pu\x73h', its second, step
# 2, env -S $'git push ...', and b's lease onto claude/$'1', step 29, each
# passing once a $'...' is read as a $ and a quoted span; step 3, a push to
# $"main", once a $"..." is read so; step 4, git pu$(true)sh, once the
# command's own text is not read; steps 5 and 6, git $(echo push) and
# $(which git) push, once a word bash builds is read as its text alone;
# step 7, $NOPE git push, once no word is read unset; step 8, git {push,},
# once braces are read as written; step 9, git push -$(echo f), once an
# option bash builds is read as written; step 10, a push to ma$(echo i)n,
# once a name bash builds is; step 11, the push after echo \, a newline and
# #', once a continuation ends a word's start; steps 12 and 13, the push in
# a here-document's substitution in $(( )), once the scan jumps over
# arithmetic; step 28, b's lease after GIT_DIR=x alone, taken once that
# assignment is read as naming the repository for good; and step 30, b's
# lease after a body whose delimiter is E$(echo x)F, taken once the
# delimiter is cut at the substitution. From its first review: step 14, a
# push by --no-verify to $(echo HEAD):$(echo claude/)$(echo 7), refused
# once a name of more than one expansion is read as built or the refspec
# as : where each is nothing; step 15, --no-verify$(true), refused once
# every built option is; step 16, git pu\, a newline and sh, let through
# once the hook's gate reads the continuation in; steps 17 and 18, coproc
# before the push and coproc X before braces around it, once coproc or its
# name is read as the command; step 19, ${NOPE:-git push} origin main,
# once a ${ } closes at its word's end; step 20, ${NOPE[0]:-main}, once a
# subscript is not read; step 21, a $'...' in a quoted default, once it is
# read as written; and step 22, @(main) after shopt -s extglob, once
# extended patterns are left unread. From its second review: step 23,
# ${A:-ma}$(echo in), once a default is read as a hole alone; step 24,
# $(echo -)f, once only a word that opens with - is read as an option;
# step 25, ?claude/7 beside a file +claude/7, once no pattern gives a +;
# step 26, [:]main beside a file :main, once no pattern gives a colon; and
# step 27, :$X after X=main, once every built word whose unset value is
# only colons is kept as written. F30's at b's marking ready, step 5,
# where #100 keeps its claim file, once the protocol check lets such a pull request through, on
# which GitHub's refusal of the owner's merge rests. F31's at carol's
# pull request from notes/1, step 2, which adds #1's claim file, once the
# check reads no claim file the change adds or changes, or none on a
# pull request that is no claim's; and at b's stacked draft, step 5,
# which adds a's claim file beside its own, once it reads none or a claim
# branch's every one as its own.
UNDONE = {
    "F1": [("the comment before the labels", 5, "G3L")],
    "F2": [("a piece of work named by the number it is shown by", 4, "G7"),
           ("a marker counted whenever it came", 8, "G7"),
           ("the markers on a claim's own pull request never read", 15, "G7"),
           ("an undated claim taking no marker", 16, "G7")],
    "F3": [("the guard passes --force", 1, "G11a")],
    "F4": [("each leg dealt from its own look", 9, "G14")],
    "F14": [("given to workers needing the label todo", 0, "G9")],
    "F5": [("a claim number with leading zeros", 2, "G1")],
    "F6": [("a sort key that calls int after isdigit", 1, "G15"), ("a branch name sent unquoted", 3, "G15")],
    "F7": [("the guard passes a lease onto another's claim", 1, "G11a")],
    "F8": [("idleness by the committer date", 13, "G2"), ("idleness by the committer date", 14, "G3"),
           ("the before side ignored", 13, "G2"), ("the push read once", 15, "G2"),
           ("a kept head dated by its push", 23, "G5"), ("kept counts only at or after the push", 23, "G5"),
           ("a kept release undone holds for good", 25, "G3"), ("a kept head released again", 25, "G2"),
           ("a stale entry off the head dates it", 28, "G2"), ("a stale entry off the head dates it", 37, "G2"),
           ("a kept head's old release taken for the lost comment", 29, "G3L"),
           ("a floor at the committer date taken for later", 39, "G2"), ("the floor dropped", 41, "G3"),
           ("the floor of the last read alone", 42, "G3"),
           ("the second read judged with no moment of the run", 43, "G2"),
           ("a fresh entry dating only off the head", 44, "G2"),
           ("the floor of the first read alone", 45, "G3"), ("the earlier floor", 45, "G3"),
           ("a fresh delete dates nothing", 47, "G2"), ("the run's event ignored", 49, "G3"),
           ("an older push trusted in the run its push started", 53, "G3")],
    "F9": [("an opaque state read by GitHub's word alone", 4, "G10"), ("the comparison read by ahead_by", 2, "G10")],
    "F10": [("a finished draft's release by hand not seen", 9, "G5")],
    "F11": [("a refused comment stops the run", 6, "G15")],
    "F12": [("main moved told only in the push's run", 10, "G10")],
    "F13": [("the landing order by number", 4, "G7"), ("a pull request dated by its opening", 4, "G7"),
            ("a refused activity read stops the run", 5, "G15"), ("a branch never asked about on its own", 5, "G7"),
            ("work nothing dates landing first", 7, "G7")],
    "F15": [("a release that leaves todo off", 7, "G3"), ("a failed release leaves its todo on", 6, "G3L"),
            ("the release's own page without its todo", 7, "G5")],
    "F16": [("a clean word compared", 4, "G10")],
    "F17": [("a fork's ready pull request finishes a claim", 7, "G3"),
            ("a fork's ready pull request skipped as a claim's", 7, "G3"),
            ("a fork's ready pull request keeps a release from counting", 7, "G3"),
            ("a fork's pull request silenced with a released claim", 7, "G10"),
            ("a fork's pull request left off with a released claim", 7, "G9"),
            ("a fork's pull request never told main moved", 9, "G10")],
    "F18": [("a shared task dealt to none", 1, "G14"), ("a shared task before one given alone", 1, "G14"),
            ("the clerk carrying by labels alone", 5, "G14"), ("a blocked claim carried", 5, "G14")],
    "F19": [("no pull request taken for a stranger's", 7, "G3"),
            ("a stranger's ready pull request finishes a claim", 7, "G3"),
            ("a stranger's ready pull request skipped as a claim's", 7, "G3"),
            ("a stranger's ready pull request keeps a release from counting", 7, "G3"),
            ("a stranger's pull request named on a claim's row", 6, "G9"),
            ("a stranger's pull request taken for a claim's work", 6, "G7"),
            ("a stranger's pull request listed after its release", 7, "G9"),
            ("a stranger's pull request spoken to after its release", 7, "G10")],
    "F20": [("an unsettled release put back", 21, "G3L"), ("an unsettled release counted", 8, "G3L"),
            ("an unsettled release failing the run", 8, "G15")],
    "F21": [("the guard ignores git's and env's -C", 1, "G11a"),
            ("the guard does not follow the shell's moves", 2, "G11a"),
            ("a cd to what is not a directory taken as made", 3, "G11a"),
            ("a push judged only where the shell's moves take it", 5, "G11a"),
            ("a push whose clone cannot be told judged by its words alone", 5, "G11a"),
            ("a relative -C after a move judged where it names alone", 6, "G11a"),
            ("GIT_DIR forgotten once an absolute path names a place", 7, "G11a"),
            ("a -C by ~ judged where it names alone", 8, "G11a")],
    "F22": [("a reopened issue left as it is", 11, "G8"), ("todo put on last", 11, "G8"),
            ("a ready pull request's in-review taken off", 23, "G8"),
            ("a claim branch not read for a reopened issue", 26, "G8"),
            ("in-review left on where a branch stands", 26, "G8"),
            ("a release before the last close read as an undo", 38, "G8"),
            ("the releases due read before the freeing", 50, "G3"),
            ("a released branch not read for a reopened issue", 52, "G8"),
            ("claimed put back after the close read as the ended claim's", 57, "G8"),
            ("a claim made since the close read as an undo", 71, "G8"),
            ("an undo after an ended claim read as the claim's", 73, "G8")],
    "F23": [("a late comment's labels put back", 16, "G3L"), ("no answer taken for a refusal", 18, "G3L"),
            ("a refusal taken for a late comment", 22, "G3L"),
            ("a rate limit's refusal taken for one that wrote nothing", 28, "G3L"),
            ("a refusal after a rate limit read by its last try alone", 34, "G3L")],
    "F26": [("a long option read only in full", 1, "G11a"),
            ("an optional value taken from the next word", 4, "G11a"),
            ("env's abbreviated --chdir not read", 5, "G11a")],
    "F25": [("a quote that never closes hiding the command", 2, "G11a"),
            ("no here-document's body told", 3, "G11a"),
            ("a here-document in a quoted substitution read as text", 4, "G11a"),
            ("an expanded body's substitutions cut out with it", 5, "G11a"),
            ("a body in a substitution ended only by its delimiter's own line", 6, "G11a"),
            ("an expanded body's backslash-newline kept", 7, "G11a"),
            ("every double parenthesis read as arithmetic", 8, "G11a"),
            ("a body that waits for a newline in the substitution that closed", 9, "G11a"),
            ("an expanded body's substitution kept with its own bodies", 10, "G11a"),
            ("a case pattern's parenthesis closing its substitution", 11, "G11a"),
            ("arithmetic's parentheses counted inside quotes", 12, "G11a"),
            ("a parameter expansion read as text", 13, "G11a"),
            ("a backquoted span read as text", 14, "G11a"),
            ("$$ read as a $ before what follows", 15, "G11a"),
            ("old-style arithmetic read as text", 16, "G11a"),
            ("a backquoted span's quotes read as the quoting around it", 17, "G11a")],
    "F24": [("a substitution in double quotes read as part of its word", 1, "G11a"),
            ("a process substitution read as a redirection", 2, "G11a"),
            ("a nested substitution left unread", 3, "G11a"),
            ("a backquoted span in a substitution read as text", 4, "G11a"),
            ("arithmetic read as no substitution", 5, "G11a"),
            ("a $'...' read as a quoted span", 6, "G11a"),
            ("a single quote in a double-quoted ${ } read as a quote", 7, "G11a"),
            ("arithmetic read as commands", 9, "G11a"),
            ("a single quote in $[ ] read as a quote", 10, "G11a"),
            ("a body's arithmetic left out of what it runs", 11, "G11a"),
            ("substitutions told alike by their own texts alone", 13, "G11a"),
            ("a backquoted span's hidden bodies left in", 14, "G11a")],
    "F27": [("a label taken off and lost stays off", 16, "G3L"),
            ("a label refused its removal put back", 20, "G3L"),
            ("a 404 after a rate limit read as never on", 22, "G3L")],
    "F28": [("env's assignments read as the shell's", 1, "G11a"), ("env's lone - not read", 2, "G11a"),
            ("env's -S string not split", 4, "G11a"), ("env's lone assignment read as the shell's", 7, "G11a"),
            ("a lone - read past as one of env's options", 8, "G11a"),
            ("an -S string's variables read only as written", 9, "G11a"),
            ("time matched by its program's name", 10, "G11a"),
            ("a time the guard cannot tell read as the keyword alone", 11, "G11a"),
            ("every ${NAME} read all set or all unset", 12, "G11a"),
            ("a push env's -S spells read only as written", 13, "G11a")],
    "F29": [("a $'...' read as a $ and a quoted span", 1, "G11a"), ("a $'...' read as a $ and a quoted span", 2, "G11a"),
            ('a $"..." read as a $ and a quoted span', 3, "G11a"), ("a command's own text left unread", 4, "G11a"),
            ("a word bash builds read as its text alone", 5, "G11a"),
            ("a word bash builds read as its text alone", 6, "G11a"), ("every word read set, none unset", 7, "G11a"),
            ("braces read as written", 8, "G11a"), ("an option bash builds read as written", 9, "G11a"),
            ("a name bash builds read as written", 10, "G11a"),
            ("a line continuation read as ending a word's start", 11, "G11a"),
            ("arithmetic jumped over by the scan", 12, "G11a"), ("arithmetic jumped over by the scan", 13, "G11a"),
            ("a word of expansions alone read as built", 14, "G11a"),
            ("a refspec of holes read as : where each is nothing", 14, "G11a"),
            ("a built option refused after a whole flag", 15, "G11a"),
            ("the hook's gate read with continuations in", 16, "G11a"), ("coproc read as the command", 17, "G11a"),
            ("coproc's name read as the command", 18, "G11a"), ("a ${ } read as closing at its word's end", 19, "G11a"),
            ("an array's ${ } read as giving nothing", 20, "G11a"), ("a $'...' in a default read as written", 21, "G11a"),
            ("extended patterns left unread", 22, "G11a"), ("a default read as a hole alone", 23, "G11a"),
            ("a word that may open with a dash read as no option", 24, "G11a"),
            ("a pattern read as giving no +", 25, "G11a"), ("a colon a pattern gives read as none", 26, "G11a"),
            ("a colon beside one hole kept as written", 27, "G11a"),
            ("a lone assignment read as naming the repository for good", 28, "G11a"),
            ("a $'...' read as a $ and a quoted span", 29, "G11a"),
            ("a here-document's delimiter cut at a substitution", 30, "G11a")],
    "F30": [("a ready pull request's claim file let through", 5, "G12")],
    "F32": [("text handed to a shell left unread", 1, "G11a"), ("text handed to a shell left unread", 2, "G11a"),
            ("a shell's -c string read as a script's name", 1, "G11a"),
            ("a shell's -c string read as a script's name", 3, "G11a"),
            ("a shell's -c string read as a script's name", 10, "G1"), ("eval's words left unread", 2, "G11a"),
            ("trap's action left unread", 7, "G11a"), ("a shell's standard input left unread", 4, "G11a"),
            ("a shell's standard input left unread", 5, "G11a"), ("a here-string left off standard input", 4, "G11a"),
            ("a here-string left off standard input", 8, "G11a"), ("what a pipe carries left unread", 5, "G11a"),
            ("what a pipe carries left unread", 11, "G1"), ("source of standard input read as a file's", 8, "G11a")],
    "F31": [("a claim file of another issue let through", 2, "G12"),
            ("a claim file of another issue let through", 5, "G12"),
            ("a pull request that is no claim's let carry a claim file", 2, "G12"),
            ("a claim branch's every claim file its own", 5, "G12")],
}
# The findings with a trace, every one settled since F25's fix: F1, F3,
# F5, F6, F10 and F11 fixed in 0.4.1; F2, F4, F7, F8, F9, F12, F13, F14,
# F15, F17, F18, F19 and F20 fixed in 0.5.0, and F21, F22, F26, F23, F25,
# F27, F24, F28, F29, F31 and F32 on main after it (known.json's fixed_after); and F16,
# fixed in the spec's words, which the library as built already keeps,
# so known.json names no version for it; and F30, fixed in the harness,
# whose model let the owner make a merge GitHub refuses, the library
# unchanged, so known.json names no version for it either.
FIXED = ("F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12", "F13", "F14", "F15", "F16", "F17",
         "F18", "F19", "F20", "F21", "F22", "F23", "F24", "F25", "F26", "F27", "F28", "F29", "F30",
         "F31", "F32")
# Findings red as built, which no rule of the library answers: none since
# F4's fix; the test keeps the case for the next one.
RED_AS_BUILT = ()


class TheTraces(unittest.TestCase):
    def setUp(self):
        self.traces = replay.traces()

    def test_one_trace_per_finding_of_the_design(self):
        self.assertEqual(sorted(self.traces, key=lambda f: int(f[1:])), list(replay.FINDINGS))
        self.assertEqual(set(replay.FINDINGS), FINDINGS_IN_DESIGN)
        for finding, trace in self.traces.items():
            with self.subTest(finding=finding):
                self.assertEqual(trace.path.stem, finding)
                self.assertEqual(trace.scenario.name, finding)
                self.assertTrue(trace.title and trace.status)
                self.assertTrue(trace.scenario.steps)
                self.assertTrue(set(trace.breaks) <= set(invariants.GUARANTEES))

    def test_every_trace_plays_with_no_mismatch_and_is_red_where_known_json_says(self):
        """As built, and with each switch of the oracle off in turn: a
        switch off shows its own finding where the file records it and
        nothing else, and the traces of the fixed findings stay green."""
        began = time.perf_counter()
        for finding, trace in self.traces.items():
            for switched_off in (None, *sorted(known.AS_BUILT)):
                with self.subTest(finding=finding, switched_off=switched_off):
                    reading = oracle.AS_BUILT if switched_off is None else oracle.AS_BUILT - {switched_off}
                    record = replay.replay(trace, reading)
                    self.assertEqual(record.mismatches, [], "\n".join(record.timeline))
                    found = replay.results(record)
                    self.assertEqual(known.differences("trace", finding, found, switched_off), [],
                                     "\n".join(record.timeline))
        self.assertLess(time.perf_counter() - began, BUDGET_SECONDS)

    def test_the_fixed_findings_are_green_and_the_open_ones_red_as_the_design_says(self):
        for finding, trace in self.traces.items():
            with self.subTest(finding=finding):
                entries = known.entries_of("trace", finding)
                if finding in FIXED:
                    self.assertIn("fixed", trace.status)
                    self.assertEqual(entries, [])
                elif finding in RED_AS_BUILT:
                    self.assertTrue(entries and all(e.finding == finding for e in entries))
                    self.assertNotIn(finding, known.AS_BUILT)
                else:
                    self.assertIn(finding, known.AS_BUILT)
                    self.assertTrue(entries and all(e.finding == finding for e in entries))
                self.assertTrue({e.guarantee for e in entries} <= set(trace.breaks))

    def test_each_fixed_finding_s_trace_turns_red_under_the_mutant_that_undoes_its_fix(self):
        """So a trace recorded green from the start is known to bite: the
        step and the guarantee are the design's table's (DESIGN.md, 5.3)."""
        self.assertEqual(sorted(UNDONE), sorted(FIXED))
        for finding, undoings in UNDONE.items():
            for mutant, step, guarantee in undoings:
                with self.subTest(finding=finding, mutant=mutant):
                    trace = self.traces[finding]
                    self.assertEqual(replay.results(replay.replay(trace)), set())
                    with mutants.switched_on(mutants.MUTANTS[mutant]):
                        record = replay.replay(trace)
                    self.assertIn((step, guarantee), replay.results(record), "\n".join(record.timeline))
                    self.assertIn(guarantee, trace.breaks)

    def test_a_step_naming_a_released_branch_the_run_never_made_is_a_mismatch_and_not_played(self):
        """The mutation lane plays every trace under every mutant: F8's
        push of c's released head names a branch a mutant that skips the
        rename never makes, so the step is a mismatch the record names and
        the lane reads the violations of the steps that played."""
        trace = self.traces["F8"]
        with mutants.switched_on(mutants.MUTANTS["the rename skipped"]):
            record = replay.replay(trace)
        self.assertIn((18, "not played: no released branch of #3"), record.mismatches)
        self.assertIn((13, "G3"), replay.results(record))

    def test_f4_s_trace_deals_from_the_run_s_one_look_and_twice_under_its_mutant(self):
        """The run looks before main moves, so c is dealt nothing; with
        each leg looking for itself, c's later look deals #6 twice."""
        trace = self.traces["F4"]
        record = replay.replay(trace)
        self.assertEqual(replay.results(record), set())
        self.assertIn("{'a': 'take 5', 'b': 'take 6', 'c': 'none'}", record.timeline[-1])
        with mutants.switched_on(mutants.MUTANTS["each leg dealt from its own look"]):
            record = replay.replay(trace)
        self.assertEqual({(v.guarantee, v.detail) for _, v in record.violations},
                         {("G14", "#6 dealt twice from differing looks: {'a': 'take 5', 'b': 'take 6', 'c': 'take 6'}")})

    def test_f18_s_trace_deals_by_pick_and_is_red_under_the_labels_alone_mutant(self):
        """Each deal of F18's trace is judged by Pick on the run's look,
        where no claim has a pull request yet (dealing.pick_problems); with
        the fix, #1 goes to b, the first of a and b with nothing else to
        do, and b, once it holds #1, carries it, before its Announce has
        come and while a's label is still on. The mutant that reads the
        holder from the labels alone, one rule of the clerk as built until
        the fix, sends a to b's claim at step 5. The Announce then takes
        a's label off, so the labels name the holder alone (the spec's
        Announce, from F18's review)."""
        record = replay.replay(self.traces["F18"])
        self.assertEqual(replay.results(record), set())
        deals = [line for line in record.timeline if " deal " in line]
        self.assertEqual(len(deals), 2)
        self.assertIn("{'a': 'take 2', 'b': 'take 1', 'c': 'take 3'}", deals[0])
        self.assertIn("{'a': 'take 2', 'b': 'carry 1', 'c': 'none'}", deals[1])
        self.assertTrue(any("label-off b 1 worker:a: label taken off" in line for line in record.timeline),
                        "\n".join(record.timeline))
        with mutants.switched_on(mutants.MUTANTS["the clerk carrying by labels alone"]):
            record = replay.replay(self.traces["F18"])
        self.assertEqual({(at, v.detail) for at, v in record.violations},
                         {(5, "a carries #1, whose claim is b's"),
                          (5, "b carries nothing though its claim on #1 is its own")})

    def test_f7_s_trace_is_green_and_red_for_g1_too_under_its_mutant(self):
        """The fence refuses the careless lease (G11a at the lease); with
        it gone git takes the lease and the board names b (G1 too)."""
        trace = self.traces["F7"]
        self.assertEqual(replay.results(replay.replay(trace)), set())
        with mutants.switched_on(mutants.MUTANTS["the guard passes a lease onto another's claim"]):
            record = replay.replay(trace)
        self.assertEqual(replay.results(record), {(1, "G11a"), (1, "G1"), (2, "G1")})
        self.assertIn(("G1", "the board names b for claude/1, whose holder is a"),
                      {(v.guarantee, v.detail) for _, v in record.violations})

    def test_f3_s_commands_are_judged_by_git_s_recorded_answers(self):
        record = replay.replay(self.traces["F3"])
        self.assertEqual(record.checks, 6)
        self.assertTrue(all("judged by git" in line for line in record.timeline))

    def test_a_trace_reads_as_a_report(self):
        trace = self.traces["F1"]
        text = replay.report(trace, replay.replay(trace))
        self.assertIn("F1 (fixed in 0.4.1 (#11))", text)
        self.assertIn("red: none", text)
        self.assertIn("board board schedule", text)


class KnownJson(unittest.TestCase):
    def test_the_oracle_s_switches_are_the_file_s(self):
        self.assertEqual(oracle.AS_BUILT, known.AS_BUILT)
        self.assertEqual(known.AS_BUILT, frozenset(), "no finding is read as built since F2's fix")

    def test_every_entry_names_a_step_of_a_trace_or_scenario_a_guarantee_and_a_finding(self):
        traces = replay.traces()
        for entry in known.ENTRIES:
            with self.subTest(entry=entry):
                steps = (traces[entry.name].scenario if entry.kind == "trace" else scenarios.SCENARIOS[entry.name]).steps
                self.assertTrue(0 <= entry.step < len(steps))
                self.assertIn(entry.guarantee, invariants.GUARANTEES)
                self.assertIn(entry.finding, FINDINGS_IN_DESIGN)
                self.assertEqual(steps[entry.step].shows, entry.finding)

    def test_every_step_a_trace_or_scenario_says_shows_a_finding_is_an_entry(self):
        shown = {("trace", f, i, s.shows) for f, t in replay.traces().items() for i, s in enumerate(t.scenario.steps)
                 if s.shows}
        shown |= {("scenario", n, i, s.shows) for n, sc in scenarios.SCENARIOS.items() for i, s in enumerate(sc.steps)
                  if s.shows}
        self.assertEqual(shown, {(e.kind, e.name, e.step, e.finding) for e in known.ENTRIES})

    def test_a_finding_s_switch_in_the_oracle_has_entries_to_show_it(self):
        for finding in sorted(known.AS_BUILT):
            with self.subTest(finding=finding):
                self.assertTrue([e for e in known.ENTRIES if e.finding == finding])

    def test_expected_reads_the_file_as_its_docstring_says(self):
        self.assertEqual(known.expected("trace", "F4"), set())
        self.assertEqual(known.expected("trace", "F7"), set())
        self.assertEqual(known.expected("trace", "F2"), set())
        self.assertEqual(known.expected("trace", "F2", "F2"), set(), "F2's entries went with its fix")
        self.assertEqual(known.expected("scenario", "S05q", "F2"), set())
        self.assertEqual(known.expected("scenario", "S05q", "F12"), set())
        self.assertEqual(known.differences("trace", "F2", {(4, "G7")}, "F2"),
                         ["trace F2 with F2 read from the spec: red and not recorded: step 4, G7"])
        self.assertEqual(known.differences("trace", "F1", {(0, "G3")}),
                         ["trace F1 as built: red and not recorded: step 0, G3"])

    def test_a_finding_fixed_on_main_is_recorded_with_the_last_version_that_has_it(self):
        """fixed_after is the canary's: it runs the release the canary
        repository vendors, so a finding fixed on main is still known there
        at that version and before, and new from the next release on."""
        self.assertEqual(known.FIXED_AFTER,
                         {"F2": "0.4.1", "F4": "0.4.1", "F7": "0.4.1", "F8": "0.4.1", "F9": "0.4.1", "F12": "0.4.1",
                          "F13": "0.4.1", "F14": "0.4.1", "F15": "0.4.1", "F17": "0.4.1", "F18": "0.4.1",
                          "F19": "0.4.1", "F20": "0.4.1", "F21": "0.5.0", "F22": "0.5.0", "F23": "0.5.0", "F24": "0.5.0",
                          "F25": "0.5.0", "F26": "0.5.0", "F27": "0.5.0", "F28": "0.5.0", "F29": "0.5.0",
                          "F31": "0.5.0", "F32": "0.5.0"})
        current = known.version_key(sdlc_protocol.__version__)
        for finding, version in known.FIXED_AFTER.items():
            with self.subTest(finding=finding):
                self.assertIn(finding, FINDINGS_IN_DESIGN)
                self.assertNotIn(finding, known.AS_BUILT, "a finding is as built or fixed, never both")
                self.assertIsNotNone(known.version_key(version))
                self.assertLessEqual(known.version_key(version), current,
                                     "the last version with a finding is one main has stated, never a later one")
        fixed_in_0_5_0 = {"F2", "F4", "F7", "F8", "F9", "F12", "F13", "F14", "F15", "F17", "F18", "F19", "F20"}
        fixed_after_0_5_0 = {"F21", "F22", "F23", "F24", "F25", "F26", "F27", "F28", "F29", "F31", "F32"}
        self.assertEqual(known.as_built_for("0.4.1"), known.AS_BUILT | fixed_in_0_5_0 | fixed_after_0_5_0)
        self.assertEqual(known.as_built_for("0.4.0"), known.AS_BUILT | fixed_in_0_5_0 | fixed_after_0_5_0)
        self.assertEqual(known.as_built_for("0.4.2"), known.AS_BUILT | fixed_after_0_5_0,
                         "the next release carries the fixes")
        self.assertEqual(known.as_built_for("0.5.0"), known.AS_BUILT | fixed_after_0_5_0)
        self.assertEqual(known.as_built_for("0.5.1"), known.AS_BUILT,
                         "the release after 0.5.0 carries F21's, F22's, F23's, F24's, F25's, F26's, F27's, "
                         "F28's, F29's, F31's and F32's fixes")
        self.assertEqual(known.as_built_for("1.0.0"), known.AS_BUILT)
        for none in (None, "", "unknown", "0.4", "0.4.1-dirty", "1" * 10 + ".0.0"):
            self.assertEqual(known.as_built_for(none), known.AS_BUILT, none)
        self.assertEqual(known.version_key("0.4.1"), (0, 4, 1))
        self.assertGreater(known.version_key("0.10.0"), known.version_key("0.9.9"))


if __name__ == "__main__":
    unittest.main()
