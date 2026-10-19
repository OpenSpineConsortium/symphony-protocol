"""Reading STATE.md as a worker reads it: the rows of each section.

The invariants compare what the board rendered with what the oracle says,
and the scripted workers decide from the page alone, so both read it here.
Sections are found by board.py's own heading constants, never by their
wording, so a heading reworded on purpose changes nothing here; a cell is
read by its column.
"""

import re

from sdlc_protocol import board

NODE = re.compile(r'^  i(\d+)\["')
EDGE = re.compile(r"^  i(\d+) (-->|-\.->|==>) i(\d+)$")
EPIC_HEADING = re.compile(r"^### Epic #(\d+)")


def rows(page, heading):
    """The cells of each row of the section under heading, "(none)" left out."""
    found, inside = [], False
    for line in page.splitlines():
        if line.startswith("## "):
            inside = line == heading
            continue
        if not inside or not line.startswith("| "):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split(" | ")]
        if line.startswith("| ---") or cells == list(columns_of(heading)) or cells[0] == "(none)":
            continue
        found.append(cells)
    return found


def columns_of(heading):
    return {
        board.CLAIM_HEADING: board.CLAIM_COLUMNS,
        board.PULL_HEADING: board.PULL_COLUMNS,
        board.OVERLAP_HEADING: board.OVERLAP_COLUMNS,
        board.QUEUE_HEADING: board.ISSUE_COLUMNS,
        board.GIVEN_HEADING: board.GIVEN_COLUMNS,
        board.BLOCKER_HEADING: board.ISSUE_COLUMNS,
        board.MERGED_HEADING: board.MERGED_COLUMNS,
    }[heading]


def titles(page, heading):
    """A section of issues as a map from issue number to its Title cell."""
    return {number(r[0]): r[1] for r in rows(page, heading)}


def dependency_blocks(page):
    """The Dependencies section's flowcharts, by what each is headed, "goals"
    or the epic's number: the numbers of the nodes, sorted, and the edges
    as (from, to, arrow), where the arrow is --> for an open blocker, -.->
    for a closed one and ==> from a goal to its epic. {} where the page
    has no section."""
    found, key, inside = {}, None, False
    for line in page.splitlines():
        if line.startswith("## "):
            inside = line == board.DEPENDENCIES_HEADING
            key = None
        elif inside and line.startswith("### "):
            key = "goals" if line == board.GOALS_HEADING else int(EPIC_HEADING.match(line).group(1))
            found[key] = ([], set())
        elif key is not None and (found_node := NODE.match(line)):
            found[key][0].append(int(found_node.group(1)))
        elif key is not None and (found_edge := EDGE.match(line)):
            found[key][1].add((int(found_edge.group(1)), int(found_edge.group(3)), found_edge.group(2)))
    return {key: (sorted(nodes), edges) for key, (nodes, edges) in found.items()}


def not_drawn(page):
    """The sentence the section carries in place of its charts, or ""."""
    return next((line for line in page.splitlines() if line in board.NOT_DRAWN.values()), "")


def number(cell):
    """#12 as 12; None for any other cell, "(not a claim)" among them."""
    text = cell.lstrip("#")
    return int(text) if cell.startswith("#") and text.isdigit() and text.isascii() else None


def queue(page):
    return sorted(number(r[0]) for r in rows(page, board.QUEUE_HEADING))


def given(page):
    return {number(r[0]): [w.strip() for w in r[2].split(",")] for r in rows(page, board.GIVEN_HEADING)}


def labelled(page, heading):
    """A section of issues (the Queue, Blockers) as a map from issue number
    to the labels its row shows."""
    return {number(r[0]): [n.strip() for n in r[2].split(",") if n.strip()] for r in rows(page, heading)}


def blockers(page):
    """The Blockers section as a map from issue number to its labels."""
    return labelled(page, board.BLOCKER_HEADING)


def queue_labelled(page):
    """The Queue as a map from issue number to its labels."""
    return labelled(page, board.QUEUE_HEADING)


def claims(page):
    """The Claims section's rows as (issue cell, branch, worker, pull cell)."""
    return [(r[0], r[1], r[2], r[3]) for r in rows(page, board.CLAIM_HEADING)]


def claim_branches(page):
    return sorted(r[1] for r in rows(page, board.CLAIM_HEADING))


def overlaps(page):
    return {r[0]: [number(n.strip()) for n in r[1].split(",")] for r in rows(page, board.OVERLAP_HEADING)}


def pulls(page):
    return sorted(number(r[0]) for r in rows(page, board.PULL_HEADING))


def merged(page):
    """The Recently merged section's pull request numbers, newest first, as
    the page lists them."""
    return [number(r[0]) for r in rows(page, board.MERGED_HEADING)]


def not_claims(page):
    """The branches the Claims section lists as no claim (board.NOT_A_CLAIM
    in the issue cell): a name that reads as a claim and claims nothing."""
    return sorted(r[1] for r in rows(page, board.CLAIM_HEADING) if r[0] == board.NOT_A_CLAIM)


def claim_workers(page):
    """The Claims section as a map from branch to the worker shown."""
    return {r[1]: r[2] for r in rows(page, board.CLAIM_HEADING)}


def claim_rows(page):
    """The Claims section's rows whole, the files each touches included."""
    return [tuple(r) for r in rows(page, board.CLAIM_HEADING)]
