"""Hold a claude/<issue> pull request to the claim protocol.

The protocol says what a claim looks like; this module makes the checkable
parts of it a list of problems, for CI to fail on, so a pull request that
forgot them cannot merge however the session that made it was feeling:

- A claim branch belongs to the repository, never a fork.
- The body closes its own issue, so the merge closes it.
- A draft still carries docs/agents/claims/<issue>.md: the claim stays
  visible exactly as long as it holds.
- A pull request marked ready has deleted it: finishing lets go.
- A head branch that reads as a claim, claude/ and digits, is the
  issue's claim branch, its number as GitHub writes it; claude/03 claims
  nothing, while its author meant a claim on #3.
- No pull request adds or changes, against its base, a claim file other
  than its own issue's on its own claim branch: a claim file of another
  issue that reached the default branch would read as that issue's claim
  (Pick) and make the board and the push guard read a later claim's
  branch, once it brought the default branch in, as that file's worker's
  (F31). Deleting a claim file passes, so a stale one on the default
  branch can always be taken off.

Any other head branch, dependabot's or a person's, is not a claim and
passes but for the claim files it adds or changes. The pull request is
the object GitHub's event carries; whether the claim file exists in the
checkout, and which claim files the change adds or changes, are the
caller's to say, so nothing here reads a file.
"""

import re

from .claims import CLAIM_DIR, branch_of, claim_path, key_of, meant_number, number_in, number_of, reads_as_claim

# The forms GitHub links a pull request to an issue with; the protocol
# writes "Closes #N" and the rest are the same promise.
CLOSES = r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#%d\b"
PROTOCOL = "docs/agents/PROTOCOL.md"


def head_branch(pull):
    return ((pull or {}).get("head") or {}).get("ref") or ""


def claim_number(pull):
    """The issue a pull request claims, from its head branch; None when the
    branch is no claim."""
    return number_of(head_branch(pull))


def repository_of(side):
    """The full name of the repository a pull request's head or base is in."""
    return ((side or {}).get("repo") or {}).get("full_name")


def closes_its_issue(pull, number):
    return re.search(CLOSES % number, pull.get("body") or "") is not None


def claim_file_number(path):
    """The issue whose claim file a repository path is,
    docs/agents/claims/<issue>.md with the issue's number as claim_path
    writes it, or None for any other path, the folder's README.md among
    them."""
    folder, _, name = str(path).rpartition("/")
    if folder != CLAIM_DIR or not name.endswith(".md"):
        return None
    return number_in(name[:-len(".md")])


def claim_files_changed(name_status):
    """The issues whose claim files a diff adds or changes, in number
    order, from `git diff --no-renames --name-status -z` output (bytes or
    text): a status, then its path, each ended by a NUL. A deleted file
    is left out, since taking a claim file off frees what it held."""
    text = name_status.decode("utf-8", "surrogateescape") if isinstance(name_status, bytes) else name_status
    fields = text.split("\0")
    found = set()
    for status, path in zip(fields[0::2], fields[1::2]):
        number = claim_file_number(path)
        if number is not None and not status.startswith("D"):
            found.add(number)
    return sorted(found)


def stray_claim_files(pull, changed_claims):
    """The problems of the claim files a pull request adds or changes that
    are not its own: every one, where its head is no claim branch here,
    and every one but its own issue's, where it is (F31)."""
    number = claim_number(pull)
    own = number if number is not None and repository_of(pull.get("head")) == repository_of(pull.get("base")) else None
    return [f"{claim_path(n)} is added or changed here, and a claim file is only its own claim branch's: once "
            f"merged it would read as a claim on #{n} on the default branch ({PROTOCOL}, Rules)"
            for n in sorted(set(changed_claims)) if n != own]


def problems_for(pull, claim_file_exists, changed_claims=()):
    """Every way this pull request breaks the protocol; [] when it keeps
    the rules. claim_file_exists says whether docs/agents/claims/<issue>.md
    is in the checkout: a bool, or a callable given the issue number, for
    a caller that would rather not parse the branch itself.
    changed_claims are the issues whose claim files the pull request adds
    or changes against its base (claim_files_changed), each of which but
    its own claim's is a problem (stray_claim_files)."""
    branch = head_branch(pull)
    number = claim_number(pull)
    strays = stray_claim_files(pull, changed_claims)
    if number is None:
        return ([misnamed(branch)] if reads_as_claim(branch) else []) + strays
    if callable(claim_file_exists):
        claim_file_exists = claim_file_exists(number)
    problems = []
    if repository_of(pull.get("head")) != repository_of(pull.get("base")):
        problems.append(f"{branch}: a claim branch lives in this repository, not in a fork "
                        f"({PROTOCOL}, Claim)")
    if not closes_its_issue(pull, number):
        problems.append(f"the body does not close #{number}, so the merge would leave the issue open; "
                        f'write "Closes #{number}" ({PROTOCOL}, Finish)')
    path = claim_path(number)
    if pull.get("draft"):
        if not claim_file_exists:
            problems.append(f"{path} is missing: a draft carries its claim file ({PROTOCOL}, Claim)")
    elif claim_file_exists:
        problems.append(f"{path} is still here: a pull request marked ready has deleted its claim file "
                        f"({PROTOCOL}, Finish)")
    return problems + strays


def misnamed(branch):
    """The problem with a head branch that reads as a claim and claims
    nothing (claims.reads_as_claim): the issue it seems to mean has its own
    claim branch, which is where the work goes."""
    meant = meant_number(key_of(branch))
    there = f"; the claim branch of #{meant} is {branch_of(meant)}, so push the work there" if meant is not None else ""
    return (f"{branch} reads as a claim branch and claims nothing, since a claim branch is claude/ and the "
            f"issue's number in one to nine ASCII digits with no leading zero{there} ({PROTOCOL}, Claim)")
