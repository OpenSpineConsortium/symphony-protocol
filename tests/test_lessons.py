"""scripts/lessons.py holds the lessons to the code: a command's promised
output must be found, in order, in what it prints, a blank line between a
command and its output still pairs them (the bug that once let every lesson
pass unchecked), each lesson's notebook is its commands cell for cell with
links that work away from the repository, the committed notebooks match
their lessons, and every real lesson prints what it says it prints."""

import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import lessons  # noqa: E402

LESSON = """# A lesson

Intro.

```bash setup
export LAB="$(mktemp -d)"
```

```bash run
cd "$LAB"
echo one
echo two
```

```output
one
two
```

```bash run
cd "$LAB"
echo unchecked
```
"""


def written(text, name="01-x.md"):
    path = Path(tempfile.mkdtemp()) / name
    path.write_text(text, encoding="utf-8")
    return path


class Matching(unittest.TestCase):
    def test_lines_are_found_in_order_within_actual_lines(self):
        self.assertIsNone(lessons.missing_lines("a\nc", "  xa\nb\ncx\n"))

    def test_a_line_out_of_order_is_missing(self):
        self.assertEqual(lessons.missing_lines("c\na", "a\nc\n"), "a")

    def test_two_expected_lines_may_share_one_actual_line(self):
        self.assertIsNone(lessons.missing_lines("## Overlaps\nin this order", "## Overlaps (in this order)"))


class Parsing(unittest.TestCase):
    def test_a_blank_line_between_a_command_and_its_output_still_pairs_them(self):
        self.assertEqual(lessons.steps(written(LESSON)),
                         [('cd "$LAB"\necho one\necho two', "one\ntwo"), ('cd "$LAB"\necho unchecked', None)])

    def test_a_wrong_output_fails_the_lesson(self):
        problems = lessons.test_lesson(written(LESSON.replace("one\ntwo\n```", "one\nthree\n```")), ROOT)
        self.assertEqual(len(problems), 1)
        self.assertIn("never printed 'three'", problems[0])

    def test_a_command_outside_the_practice_folder_is_refused(self):
        problems = lessons.lesson_shape(written(LESSON.replace('cd "$LAB"\necho unchecked', "echo unchecked")))
        self.assertEqual(len(problems), 1)
        self.assertIn('block 2 does not open with cd "$LAB"', problems[0])


class Notebooks(unittest.TestCase):
    def test_each_command_is_a_bash_cell_from_the_practice_folder(self):
        made = lessons.notebook_of(written(LESSON))
        code = ["".join(c["source"]) for c in made["cells"] if c["cell_type"] == "code"]
        self.assertIn("ls-remote", code[0])
        self.assertEqual(code[1:], ['%%bash\ncd "$LAB"\necho one\necho two', '%%bash\ncd "$LAB"\necho unchecked'])

    def test_links_lead_to_colab_or_to_github(self):
        text = "[l2](02-x.md), [p](../spec/PROTOCOL.md#claim), [w](https://x.org), [a](#here), ![f](a.svg)"
        self.assertEqual(lessons.links_for_colab(text),
                         f"[l2]({lessons.COLAB}02-x.ipynb), "
                         f"[p]({lessons.LIBRARY_URL}/blob/main/spec/PROTOCOL.md#claim), "
                         "[w](https://x.org), [a](#here), ![f](a.svg)")

    def test_the_committed_notebooks_match_their_lessons(self):
        self.assertEqual(lessons.notebooks(Namespace(check=True)), 0)


class TheLessons(unittest.TestCase):
    def test_every_lesson_is_listed_and_well_formed(self):
        self.assertEqual(lessons.check(Namespace()), 0)

    def test_every_lesson_prints_what_it_says(self):
        for path in lessons.lessons():
            with self.subTest(lesson=path.name):
                self.assertEqual(lessons.test_lesson(path, ROOT), [])


if __name__ == "__main__":
    unittest.main()
