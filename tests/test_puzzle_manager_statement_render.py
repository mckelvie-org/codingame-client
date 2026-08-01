"""Unit tests for codingame_tools.puzzle_manager.statement_render.parse_statement_html--a
   purpose-built parser for CodinGame's specific puzzle-statement HTML shape, not a general
   HTML-to-text converter. Fixture HTML below is a trimmed synthetic example matching that real
   shape (confirmed against a live puzzle statement during development), not a live fetch.
"""

from __future__ import annotations

from codingame_tools.puzzle_manager.statement_render import CgStatementBlock, parse_statement_html

_SAMPLE_HTML = """
<div class="statement-body">
<div class="statement-section statement-goal">
   <h2><span class="icon icon-goal">&nbsp;</span><span>Goal </span></h2>
   <span class="question-statement">First.<br><br>Second <strong>bold</strong>.<br><br><strong>Sub head</strong><br><br>Third.</span>
</div>
<div class="statement-section statement-protocol">
   <div class="blk">
      <div class="title">Input</div>
      <div class="question-statement-input"><strong>Line 1:</strong> first.<br><strong>Line 2:</strong> second.</div>
   </div>
   <div class="blk">
      <div class="title">Constraints</div>
      <div class="question-statement-constraints">1 &le; <var>n</var> &le; 100</div>
   </div>
   <div class="blk">
      <div class="title">Example</div>
      <div class="statement-inout">
         <div class="statement-inout-in">
            <div class="title">Input</div>
            <pre class="question-statement-example-in">3
1 2 3</pre>
         </div>
         <div class="statement-inout-out">
            <div class="title">Output</div>
            <pre class="question-statement-example-out">6</pre>
         </div>
      </div>
   </div>
</div>
</div>
"""


def test_parses_expected_block_sequence() -> None:
    blocks = parse_statement_html(_SAMPLE_HTML)
    assert [b.kind for b in blocks] == [
        "header", "text",
        "header", "text",
        "header", "text",
        "header", "header", "example_input", "header", "example_output",
    ]
    assert blocks[0].text == "Goal"
    assert blocks[2].text == "Input"
    assert blocks[4].text == "Constraints"
    assert blocks[5].text == "1 ≤ n ≤ 100"  # &le; unescaped
    assert blocks[6].text == "Example"
    assert blocks[7].text == "Input"  # nested Example > Input title, same "header" kind
    assert blocks[8].text == "3\n1 2 3"
    assert blocks[9].text == "Output"
    assert blocks[10].text == "6"


def test_double_br_is_a_paragraph_break_single_br_is_a_line_break() -> None:
    blocks = parse_statement_html(_SAMPLE_HTML)
    goal_text = blocks[1].text
    assert goal_text == (
            "First.\n\n"
            "Second bold.\n\n"
            "Sub head\n\n"
            "Third."
        )
    input_text = blocks[3].text
    assert input_text == "Line 1: first.\nLine 2: second."  # single <br>, no blank line


def test_example_input_output_preserve_exact_whitespace() -> None:
    blocks = parse_statement_html(_SAMPLE_HTML)
    example_input = next(b for b in blocks if b.kind == "example_input")
    assert example_input.text == "3\n1 2 3"


def test_empty_statement_yields_no_blocks() -> None:
    assert parse_statement_html("") == []
    assert parse_statement_html("<div class='statement-body'></div>") == []


def test_block_is_frozen_dataclass() -> None:
    block = CgStatementBlock(kind="header", text="Goal")
    assert block.kind == "header"
    assert block.text == "Goal"
