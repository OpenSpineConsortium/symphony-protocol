# Board

As of commit 0123abc on main. Rewritten by .github/workflows/board.yml; do not edit by hand.

## Claims (open claude/<issue> branches and docs/agents/claims/<issue>.md)

| Issue | Branch | Worker | PR | Files it touches |
| --- | --- | --- | --- | --- |
| #22 | claude/22 | alice | (no pull request yet) | sdlc_protocol/board.py |

## Open pull requests

| PR | Title | Branch | State (clean, behind, conflicting, blocked, unknown) | Last update |
| --- | --- | --- | --- | --- |
| (none) |  |  |  |  |

## Overlaps (files that more than one piece of open work changes; land the work in this order: a blocker first, then work marked ready, then the oldest)

| File | Open work, in the order it should land |
| --- | --- |
| (none) |  |

## Queue (open issues labelled todo, unclaimed and given to no worker)

| Issue | Title | Labels |
| --- | --- | --- |
| #23 | Write the body \| with "quotes" and <tags> #5 and a title long enough to be cut short (blocked by #22) | todo |
| #99 | Settle the colours | todo |

## Given to workers (open issues a worker's label names, not yet claimed)

| Issue | Title | Worker |
| --- | --- | --- |
| #24 | Write the docs (blocked by 2 open issues) | bob |

## Blockers (open issues labelled blocker)

| Issue | Title | Labels |
| --- | --- | --- |
| #25 | Fix the build (blocked by 1 open issue) | blocker |

## Recently merged (the last 5)

| PR | Title | Branch | Merged |
| --- | --- | --- | --- |
| (none) |  |  |  |

## Dependencies

Each open epic's tasks as GitHub's sub-issues and blocked-by relations hold them: an arrow runs from the issue that blocks to the issue it blocks, dotted once the blocker is closed; a node's shade is its state, and an epic's heading counts its closed tasks.

### Goals

```mermaid
flowchart TD
  i20["#20 Draw the board (1/3)"]
  i30["#30 Ship the graph (0/1)"]:::todo
  i30 ==> i20
  classDef todo fill:#ffffff,stroke:#0e8a16,color:#000000
  classDef claimed fill:#fff8d6,stroke:#fbca04,color:#000000
  classDef review fill:#e3f0ff,stroke:#1d76db,color:#000000
  classDef blocked fill:#ffe7e7,stroke:#e99695,color:#000000
  classDef closed fill:#eeeeee,stroke:#999999,color:#666666
```

### Epic #20: Draw the board (1/3)

```mermaid
flowchart TD
  i21["#21 Read the summary"]:::closed
  i22["#22 Render the section"]:::claimed
  i23["#23 Write the body #124; with #quot;quotes#quot; and #lt;t..."]:::todo
  i99["#99 Settle the colours"]:::todo
  i21 -.-> i23
  i22 --> i23
  i99 --> i22
  classDef todo fill:#ffffff,stroke:#0e8a16,color:#000000
  classDef claimed fill:#fff8d6,stroke:#fbca04,color:#000000
  classDef review fill:#e3f0ff,stroke:#1d76db,color:#000000
  classDef blocked fill:#ffe7e7,stroke:#e99695,color:#000000
  classDef closed fill:#eeeeee,stroke:#999999,color:#666666
```
