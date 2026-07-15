"""AI question generation: SAT taxonomy, prompt engineering, and LLM calls.

The taxonomy mirrors the College Board Digital SAT question bank exactly:
Math (4 content domains, 19 skills) and Reading & Writing (4 content domains,
10 skills). Each skill carries a detailed spec that is spliced into a
per-subject base prompt. The English skill names must stay verbatim-identical
to the question_type values used across the site (practice filters etc.).

Rendering contract with the frontend (RenderWithMath.jsx):
  - Inline math:  $...$          (KaTeX)
  - Block math:   $$...$$        (KaTeX; tables use \\begin{array}{|c|c|} inside)
  - Figures:      [svg]<svg ...>...</svg>[/svg]  (sanitized inline SVG)
  - Text markup:  \\textit{..} \\textbf{..} \\underline{..}, \\n line breaks,
    and bullet lines that start with *** (used for Rhetorical Synthesis notes)
"""

import json
import os
import re

# ---------------------------------------------------------------------------
# Difficulty rubric (site uses 1-5; College Board bank uses easy/medium/hard)
# ---------------------------------------------------------------------------

DIFFICULTY_RUBRIC = """\
DIFFICULTY SCALE (1-5). CRITICAL: this platform hosts ONLY hard SAT math. The
whole scale is shifted UP — there are no easy warm-up items here. Even a
difficulty-1 question should make a well-prepared student stop and think; the
real SAT is trending harder every year, and this bank targets that upper end.

These absolute anchors are authoritative. They OVERRIDE any numeric "difficulty
knob" hints inside the per-skill notes below — those legacy notes used an
easy-to-hard scale, so read them only for WHICH techniques a skill can draw on,
never for how hard to pitch the item.

- 1  Hard end of the standard SAT (a College Board "Hard"): genuine multi-step
    reasoning or one non-obvious idea. Never a one-liner or a plug-and-chug.
- 2  Among the hardest standard SAT items (~top 10% of the real test): needs a
    real insight most students miss — a clever manipulation, reasoning about
    expressions instead of solved values, or a non-obvious setup — plus clean
    execution.
- 3  At or just past the ceiling of what the real SAT asks: two ideas combined,
    layered reasoning, or a slightly unusual representation. A strong student
    must form a genuine plan before writing anything down.
- 4  BEYOND the SAT — early-contest level (about AMC 10/12). Innovative, not a
    known template. Solving hinges on spotting a non-standard idea: a
    substitution, a symmetry, an invariant, a clever reframing. A prepared
    student needs 30-60 seconds of thought just to SEE THE PATH before any
    computation. There must be no textbook formula that maps straight to the
    answer.
- 5  The "prevent a perfect score" tier: mid-AMC to low-AIME level thinking,
    adapted to stay inside SAT topic boundaries. Deeply non-trivial and
    creative — the one-in-a-test stunner only the most experienced, best-prepared
    students crack. Demands a real insight or a multi-idea chain. Hard because of
    the IDEA required, never because of tedious arithmetic.

RULES FOR DIFFICULTY 4 AND 5 (read carefully — most AI questions fail here):
- Innovate. Do NOT take a standard SAT template and enlarge the numbers. Invent a
  fresh setup that rewards insight over recall. Use real creativity and
  imagination.
- The solver must NOT be able to read the stem and immediately know the formula
  to apply. If a well-drilled student can answer on autopilot, it is TOO EASY —
  redesign it from a different angle.
- Still fully solvable by hand in a few minutes, with no calculator trick, no
  out-of-scope theorem, and no heavy computation. The difficulty lives in the
  hidden idea, not in long algebra.
- Stay inside the stated skill's topic area: an AMC-flavored problem that still
  clearly belongs to this SAT skill (e.g. still recognizably "Circles" or
  "Nonlinear functions"), an advanced version of it — not an unrelated olympiad
  problem.
- Difficulty 5 in particular should be the hardest thing on the platform. Aim
  high; assume the audience is elite.
"""

# ---------------------------------------------------------------------------
# Shared formatting + output contract
# ---------------------------------------------------------------------------

SHARED_TAIL = """\
ANSWER-KEY BALANCE (IMPORTANT — do not default to one letter):
- Spread the correct answers across A, B, C, and D. Across a batch aim for a
  roughly even split; do NOT let any letter dominate and do NOT habitually put
  the answer at C (or B). For each single question the correct choice should be
  equally likely to sit in any of the four slots — choose its position at random.
- Before finalizing, scan your batch's answer key. If one letter appears much
  more than the others, REORDER the choices of some questions to rebalance it.

OUTPUT CONTRACT (strict):
Return ONLY a single copyable Markdown code block labeled json, with no text
before or after it. The JSON array goes inside that block; do not output plain
JSON outside a code block. This outer code block is the only Markdown allowed —
inside JSON strings, follow the no-Markdown renderer rules above. Each element:
{
  "question": "stem text using only the renderer markup described above",
  "choice_a": "...", "choice_b": "...", "choice_c": "...", "choice_d": "...",
  "answer": "A" | "B" | "C" | "D",
  "difficulty": <int 1-5>,
  "question_type": "<the skill name given below, verbatim>",
  "explanation": "worked solution + distractor notes"
}
JSON strings must escape backslashes (write \\\\textit / \\\\frac in the JSON
source so the parsed value is \\textit / \\frac) and must not contain raw
newlines — use \\n.
"""

FORMAT_RULES = """\
FORMATTING RULES (STRICT — the website renders every field with a KaTeX + light
markup renderer. Malformed formatting shows up broken to students, so follow
these EXACTLY, in the question stem, all four choices, and the explanation.)

MATH — always KaTeX inside dollar delimiters:
- Inline math goes between single dollars: $3x + 5 = 11$. Display/centered math
  goes between double dollars on its own line: $$y = 2x^2 - 4$$.
- NEVER write bare ASCII or Unicode math. Not 3x+5=11, not x^2, not x², not
  1/2, not sqrt(3), not <=, not pi, not ×/÷/√/π/≤/≥/≠/∞/°/±. Every one of these
  must be KaTeX: $x^{2}$, $\\frac{1}{2}$, $\\sqrt{3}$, $\\le$, $\\pi$, $\\times$,
  $\\div$, $\\ge$, $\\ne$, $\\infty$, $40^\\circ$, $\\pm$, $|x|$.
- Fractions $\\frac{a}{b}$, exponents $x^{2}$ (always brace the exponent),
  roots $\\sqrt{3}$ and $\\sqrt[3]{x}$, subscripts $x_{1}$.
- Balance every delimiter: each $ has a closing $, each $$ a closing $$. An
  unmatched dollar sign breaks the entire line. Do a final pass to check pairs.

DOLLAR-SIGN / CURRENCY PITFALL (this breaks often — handle it deliberately):
- A literal money "$" will be misread as a math delimiter and corrupt the text.
- So write money as words — "48 dollars", "a price of 48 dollars" — OR as KaTeX
  with an escaped dollar: $\\$48$ renders the characters "$48". NEVER type a raw
  $48 in prose.

MARKUP — the renderer only understands these; do NOT use Markdown:
- Line break: use the two characters \\n (in the JSON string). Put each display
  equation, each table, and each [svg] block on its own line with a \\n before
  and after it.
- Bold: $\\textbf{...}$ is NOT needed — use \\textbf{word} directly in text.
  Italic: \\textit{word}. Underline: \\underline{word}. (Use these sparingly.)
- Do NOT use Markdown syntax: no #, ##, no **bold**, no `backticks`, no Markdown
  tables, no "- " or "1. " list markers. They render literally as ugly text.

TABLES — a KaTeX array in display math (never a Markdown table):
  $$\\begin{array}{|c|c|} \\hline x & f(x) \\\\ \\hline 0 & 3 \\\\ \\hline 1 & 5 \\\\ \\hline \\end{array}$$

FIGURES (geometry diagrams, graphs, scatterplots, number lines) — a single
self-contained inline SVG wrapped in [svg]...[/svg], on its own line in the stem:
  * viewBox="0 0 340 H" with H <= 300; no width/height attributes.
  * Stroke color #334155; light fills like #cbd5e1 or none; label text with
    font-size="13" font-family="sans-serif" fill="#334155". Points as small
    filled circles r="3".
  * Label everything the solver needs (axis numbers, side lengths, angle marks,
    point names). Minimal and uncluttered, like a real SAT figure.
  * If not to scale, add plain text "Note: Figure not drawn to scale." after it.
  * NO <script>, <image>, <foreignObject>, <a>, event handlers, or external refs
    — plain shapes, paths, and text only.
  * NEVER put an [svg] block, a table, or a $$display$$ block inside an answer
    choice; choices are short inline text/KaTeX only.

STYLE (valid SAT-math voice, but creative — see the TASK section):
- Precise, clear wording. Stems are typically 1-4 sentences; word problems stay
  under ~90 words. No filler, no jokes, no real brand names. Use varied, realistic
  names/contexts (Priya, Marcus, Yuki, a biologist, a machinist, ...).
- Exactly 4 answer choices, exactly one correct. Wrong choices are PLAUSIBLE
  distractors from specific predictable errors (sign slip, swapped
  slope/intercept, forgot to distribute, radius-for-diameter, solved for x when
  asked for 2x+1, ...) — never random filler numbers, and never two choices that
  are secretly equal.
- When choices are numeric, order them ascending (or in a natural logical order).

EXPLANATION:
- Show the efficient solution path step by step in KaTeX (use \\n between steps,
  and $$...$$ for a key line). For difficulty 4-5, first name the KEY INSIGHT
  that unlocks the problem, then the steps.
- End with one short line per wrong choice naming the mistake that produces it,
  e.g. "Choice B results from ...".

""" + SHARED_TAIL

BASE_PROMPT = """\
You are an expert SAT Math item writer AND a competition-math problem composer
(AMC/AIME background). You know the digital SAT's tested skills, notation, and
distractor design cold, and you can also invent original, insight-driven
problems that go well beyond routine test-prep. Write ORIGINAL questions — never
copy a released item, and never just fill a familiar template with new numbers.

{format_rules}

{difficulty_rubric}

============================================================
CONTENT DOMAIN: {domain}
SKILL (use verbatim as "question_type"): {skill}
============================================================
{spec}
{variant_clause}
TASK: Write {count} original, CREATIVE multiple-choice question(s) for the skill
above, all at difficulty {difficulty} (use the absolute anchors in the DIFFICULTY
SCALE — do not drift easier). Requirements:
- Be genuinely creative and varied. Elaborate on the topic; invent fresh setups,
  contexts, representations, and stem phrasings. MIX across the skill's
  sub-topics (see the list above) so no two questions feel alike — even within a
  single difficulty level, and even at difficulty 3. Do not grind the same
  template. Do not imitate the exact phrasing of released SAT items.
- Every item must still be a valid, self-contained, single-correct-answer
  question that genuinely belongs to this skill's topic area.
- Honor the difficulty anchor strictly. For 4-5, lead with a hidden insight and
  make sure no textbook formula maps straight to the answer.
Before finalizing: (1) solve each question yourself and confirm the keyed answer
is correct AND unique; (2) confirm no distractor equals the correct value;
(3) balance the answer key across A/B/C/D per ANSWER-KEY BALANCE, reordering
choices where needed.
"""

# ---------------------------------------------------------------------------
# English (Reading & Writing) prompt machinery. Same output contract as math,
# but its own voice, formatting rules, and a descriptive difficulty scale —
# R&W hardness has no numeric metric, so the bands are soft by design.
# ---------------------------------------------------------------------------

ENGLISH_DIFFICULTY_RUBRIC = """\
DIFFICULTY SCALE (1-5). Reading & Writing difficulty has no clean numeric
metric, so these are descriptive bands with deliberately smooth boundaries.
Two levers control almost all of it: (a) TEXT DEMAND — the vocabulary, syntax,
register, and era of the passage — and (b) CHOICE DISCRIMINATION — how fine
the cut is between the credited answer and the best distractor. Raise
difficulty by tightening those levers, NEVER by making the item ambiguous: at
every level exactly one choice must be fully defensible from the text alone,
and any two careful expert readers must agree on the key.

- 1  Entry level, easily solved: a short, friendly passage in plain
    contemporary prose; the answer is nearly explicit in the text, and the
    three wrong choices are clearly wrong after one attentive read. A prepared
    student answers quickly and gains confidence.
- 2  Routine: one small interpretive step (a paraphrase, an obvious logical
    link). Distractors recycle words from the passage but misuse them; one is
    mildly tempting on a skim but collapses on a second look.
- 3  Mid-band, the middle of a real module: denser academic or literary prose,
    an answer that requires holding two parts of the text together, and at
    least one distractor that is half right — correct topic, wrong claim.
- 4  The hard end of a real SAT module: scholarly research summaries, older
    literary prose, or verse; subtle inference and function questions.
    Distractors are engineered from the classic wrong moves (too extreme, out
    of scope, right detail wrong emphasis, reversed relationship). Students
    who skim or who match keywords instead of logic get these wrong.
- 5  Distinguishably harder than 4 — the item that separates a 780 from an
    800. STACK several commonly-missed traps in a single question: the densest
    still-defensible text (19th-century fiction, poetry, or a technical
    research abstract), a fine-grained final cut where the best distractor
    differs from the key by a single overreach (an "always" where the text
    says "sometimes", a cause where it shows correlation, the author's view
    swapped for a critic's the author cites), and a stem that punishes
    autopilot answering. Still exactly one right answer, provable by pointing
    at specific words in the text.
"""

ENGLISH_FORMAT_RULES = """\
FORMATTING RULES (STRICT — the website renders every field with a light markup
renderer. Malformed markup shows up broken to students, so follow these
EXACTLY in the question stem, all four choices, and the explanation.)

MARKUP the renderer understands (and NOTHING else — no Markdown):
- Line break: the two characters \\n inside the JSON string. Separate the
  passage from the question line with a blank line (\\n\\n).
- Italics: \\textit{...} — use for titles of novels, plays, long poems, and
  ships. Bold: \\textbf{...} (rarely needed). Underline: \\underline{...} —
  REQUIRED around the target sentence in "function of the underlined
  sentence" items.
- Bulleted note line (Rhetorical Synthesis only): a line that starts with the
  three characters *** renders as a bullet. One note per line:
  \\n***Coral reefs shelter about a quarter of all marine species.\\n
- Blank to be completed: the seven characters _______ exactly where the word,
  phrase, or punctuation choice goes.
- Do NOT use Markdown: no **bold**, no # headings, no "- " or "1." lists, no
  backticks — they all render literally as ugly text.
- A literal dollar sign starts math mode and corrupts the text: write money
  as words ("48 dollars") or as $\\$48$, never a bare $48.

DATA TABLES (Command of Evidence, quantitative variants) — a KaTeX array in
display math on its own line (never a Markdown table), words wrapped in
\\text{...}:
  $$\\begin{array}{|l|c|c|} \\hline \\text{Site} & 2010 & 2020 \\\\ \\hline \\text{Reef A} & 34 & 12 \\\\ \\hline \\end{array}$$
Keep tables small (at most 5 rows x 4 columns), introduce them with a plain
sentence in the stem, and balance every delimiter.

GRAPHS (Command of Evidence, quantitative variants) — a single self-contained
bar or line chart as inline SVG wrapped in [svg]...[/svg], on its own line:
  * viewBox="0 0 340 H" with H <= 300; no width/height attributes.
  * Stroke #334155; bar fills #cbd5e1; text font-size="13"
    font-family="sans-serif" fill="#334155". Points as filled circles r="3".
  * Label everything the solver needs: axis titles with units, tick values,
    category names, and the plotted values themselves.
  * NO <script>, <image>, <foreignObject>, <a>, event handlers, or external
    refs — plain shapes, paths, and text only.
  * NEVER put an [svg] block, a table, or a $$...$$ block inside an answer
    choice; choices are short inline text only.

SAT READING & WRITING HOUSE STYLE:
- ONE self-contained passage of 25-150 words per question, then the question
  as its own final line. No shared passages across questions.
- Literary excerpts open with an attribution line woven into the passage
  field, e.g. "The following text is from Edith Wharton's 1905 novel
  \\textit{The House of Mirth}." Research passages instead weave the actors
  into the prose ("marine biologist Ana Osei and her colleagues...").
- Poetry keeps its line breaks (\\n at each verse line).
- Cross-Text items format as: Text 1\\n<passage>\\n\\nText 2\\n<passage>.
- Exactly 4 answer choices, exactly one correct, all four parallel in form,
  length, and grammatical fit (any choice must slot into the blank
  grammatically — students eliminate on logic, never on grammar mismatch,
  except in Standard English Conventions items where grammar IS the test).
- Choices stay SHORT where the skill allows: single words for vocabulary and
  transitions, one sentence elsewhere.

EXPLANATION:
- First prove the key: state why the credited choice is correct, quoting the
  exact words of the passage (or the exact table/graph values) that make it
  the only defensible answer. For Standard English Conventions, name the rule
  being tested (comma splice, subject-verb agreement across an interrupting
  phrase, dangling modifier, ...).
- Then one short line per wrong choice naming the SPECIFIC trap it springs,
  e.g. "Choice B is too extreme: the text says the effect 'can' occur, not
  that it always does." Name the reusable reasoning move so a student who
  missed the item learns something transferable.

""" + SHARED_TAIL

ENGLISH_BASE_PROMPT = """\
You are an expert SAT Reading & Writing item writer with a College Board
assessment-design background AND genuine literary range — equally at home in
nineteenth-century fiction, contemporary science journalism, poetry, art
history, and social-science research. Write ORIGINAL questions — never copy a
released item, and never fill a familiar template with swapped nouns. Every
question should reward close reading and leave the student knowing something
they did not know before.

PASSAGE SOURCING (this is where question quality is won — be creative):
- Literary and poetry passages: use REAL public-domain texts (published before
  1929), quoted or lightly adapted into a self-contained 25-150 word excerpt.
  Range far beyond the overused canon — instead of the same Austen and Dickens
  paragraphs, reach for Edith Wharton, Willa Cather, Charles Chesnutt, Zitkala-Sa,
  Sui Sin Far, W. E. B. Du Bois, Elizabeth Gaskell, Christina Rossetti, Paul
  Laurence Dunbar, or Turgenev, Chekhov, and Ibsen in translation. Name the
  author, year, and title in the attribution line. NEVER misattribute: if you
  are not certain of the exact source and wording, write an original passage in
  period style and attribute it to no one (e.g. "The following text is from a
  1902 short story.").
- Informational passages (science, history, arts, social science): write an
  original passage in College Board's neutral, information-dense register,
  built around a specific and plausible study, artist, invention, or episode.
  Mine genuinely interesting corners — underrated scientific findings,
  non-Western art movements, overlooked inventors, surprising historical
  reversals — so the passage itself is worth the student's attention.
- Every passage must be fully self-contained: solvable with zero outside
  knowledge, everything needed on the page, and nothing in the correct answer
  that rewards prior familiarity with the topic.

{format_rules}

{difficulty_rubric}

============================================================
CONTENT DOMAIN: {domain}
SKILL (use verbatim as "question_type"): {skill}
============================================================
{spec}
{variant_clause}
TASK: Write {count} original multiple-choice question(s) for the skill above,
all at difficulty {difficulty} (use the descriptive bands in the DIFFICULTY
SCALE — do not drift easier). Requirements:
- Vary the batch widely: different subject areas (literature, natural science,
  history, arts, social science), different passage styles, different named
  people and places — no two items should feel alike. Rotate across the
  sub-topics listed above and invent fresh angles beyond them.
- Use the skill's EXACT standardized stem phrasing given in the spec: on the
  real test the passage varies but the question wording is boilerplate.
- Honor the difficulty band strictly. For 4-5, engineer the best distractor to
  be the answer a keyword-matching or skimming student WOULD pick, and make
  the cut between it and the key fine but airtight.
Before finalizing: (1) re-read each passage cold and confirm the keyed answer
is the ONLY defensible choice — if a smart student could argue for a second
choice, tighten the passage or the choices until they cannot; (2) confirm each
distractor is wrong for one specific, explainable reason; (3) balance the
answer key across A/B/C/D per ANSWER-KEY BALANCE, reordering choices where
needed.
"""

# ---------------------------------------------------------------------------
# The math taxonomy: 4 official domains -> 19 official skills, each with a
# hand-engineered spec. Variants break broad skills into sub-types while
# keeping the official skill as the stored question_type.
# ---------------------------------------------------------------------------

MATH_DOMAINS = [
    {
        "name": "Algebra",
        "share": "~35% of the Math section (13-15 questions per test)",
        "skills": [
            {
                "name": "Linear equations in one variable",
                "blurb": "Solve, build, and interpret linear equations in a single variable.",
                "figures": "rare",
                "variants": [
                    "solve a bare equation (fractions or distribution required at difficulty 3+)",
                    "equation with a constant k: find k given a solution, or find the value that makes the equation have no solution / infinitely many solutions",
                    "one-sentence word problem that translates to ax + b = c",
                    "asked for an expression's value (e.g. find 3x - 2), not x itself",
                ],
                "spec": """\
WHAT IT TESTS: fluency solving ax + b = cx + d and building one-variable
linear equations from short contexts.
TYPICAL WORDING: "If 3(x - 4) = 2x + 5, what is the value of x?" /
"What value of p satisfies ...?" / "The equation shown has no solution.
What is the value of a?" Stems are 1-2 sentences; contexts (ages, prices,
totals) stay under 40 words.
DIFFICULTY KNOBS: 1-2 = integer one/two-step solves. 3 = fractions,
distribution, or simple contexts. 4-5 = unknown constants, no-solution /
infinitely-many-solutions structure (coefficients match, constants differ),
or being asked for a compound expression instead of x.
DISTRACTOR TRAPS: sign error moving a term, dividing only part of a side,
forgetting to distribute to the second term, answering x when the question
asks for an expression in x.""",
            },
            {
                "name": "Linear functions",
                "blurb": "Model, evaluate, and interpret linear functions f(x) = mx + b.",
                "figures": "sometimes: a line graph or an x/f(x) table",
                "variants": [
                    "evaluate or invert: given f(x) = mx + b, find f(k) or find x when f(x) = k",
                    "interpret slope or y-intercept in a real context (per-unit rate vs. starting value)",
                    "build f from a table of values or two given points",
                    "graph-based: identify the function from its graph, or read/compare values off a graphed line",
                ],
                "spec": """\
WHAT IT TESTS: linear functions as models — function notation, rate of change
(slope) as a per-unit quantity, intercept as an initial value.
TYPICAL WORDING: "The function f is defined by f(x) = 4x + 3. What is the
value of f(2)?" / "The function m(t) = 500 - 25t models the amount of water,
in liters, in a tank t minutes after... What is the best interpretation of 25
in this context?" Interpretation stems give a 1-2 sentence context, then ask
"Which of the following is the best interpretation of ...?" with four full
sentence choices.
TABLES: for table variants, give 3-4 (x, f(x)) rows in a KaTeX array with
constant first differences.
GRAPHS: for graph variants, draw a clean SVG coordinate grid (~5x5 units,
axis labels) with the line and 2 labeled lattice points.
DIFFICULTY KNOBS: 1-2 = direct evaluation. 3 = build from two points/table,
straightforward interpretation. 4-5 = interpretation with subtle unit
distractors, composed conditions like f(a) = a, or comparing two linear models.
DISTRACTOR TRAPS: swapping slope and intercept meanings, inverted slope
(run/rise), using Δx where Δy belongs, off-by-one when reading tables.""",
            },
            {
                "name": "Linear equations in two variables",
                "blurb": "Build and interpret two-variable linear relationships and their graphs.",
                "figures": "sometimes: line graphs; contexts often instead of figures",
                "variants": [
                    "write the equation modeling a context (two quantities with a fixed total or rate)",
                    "slope/intercepts from an equation or from two points; convert between forms",
                    "graph-based: match equation to graph or find x/y-intercepts and interpret them",
                    "find a constant so a line passes through a given point, or is parallel/perpendicular to another",
                ],
                "spec": """\
WHAT IT TESTS: the relationship between linear equations ax + by = c or
y = mx + b, their graphs, and the contexts they model.
TYPICAL WORDING: "A store sells pencils for $0.50 each and pens for $2.00
each. Malia spent exactly $10. Which equation represents this situation?" /
"Line k is defined by y = 3x - 7. Line j is parallel to line k and passes
through (2, 5). Which equation defines line j?" / "What is the x-intercept of
the graph of ...?"
STANDARD-FORM CONTEXTS (price/quantity totals) are the signature item: two
unit-rates and a total, answer choices are four ax + by = c equations with
coefficients permuted or swapped.
DIFFICULTY KNOBS: 1-2 = identify slope/intercept, plug in a point. 3 = model
a context, convert forms. 4-5 = parallel/perpendicular with solving for a
constant, interpret an intercept in context, or reason about a + b given
graph constraints.
DISTRACTOR TRAPS: swapped coefficients (price attached to wrong item),
negative-reciprocal vs reciprocal slope confusion, x- vs y-intercept mixups,
sign of slope read from a decreasing graph.""",
            },
            {
                "name": "Systems of two linear equations in two variables",
                "blurb": "Solve systems and reason about number of solutions.",
                "figures": "occasionally: two lines on a grid",
                "variants": [
                    "solve by elimination/substitution; report x, y, or x + y",
                    "word problem producing a system (two totals: count and value)",
                    "structure: find constant k so the system has no solution / infinitely many solutions",
                    "graphical: solution as intersection point of two graphed lines",
                ],
                "spec": """\
WHAT IT TESTS: solving 2x2 linear systems and understanding solution counts as
statements about slopes/intercepts.
TYPICAL WORDING: "The solution to the given system of equations is (x, y).
What is the value of x + y?" (equations displayed on separate lines with
$$...$$) / "A theater sold 200 tickets... adult tickets cost $12 and child
tickets cost $7... Which system of equations...?" / "In the given system, k is
a constant. If the system has no solution, what is the value of k?"
Display the system as two block equations, one per line.
DIFFICULTY KNOBS: 1-2 = elimination falls out immediately (aligned
coefficients). 3 = multiply one equation first; count/value word problems.
4-5 = asked for a combination like x + y that shortcuts via adding the
equations, no-solution/infinite-solution constants, or a system disguised in
context.
DISTRACTOR TRAPS: reporting x when y is asked, adding instead of subtracting
equations, ratio errors when matching coefficients for no-solution items,
(x, y) swapped in the intersection point.""",
            },
            {
                "name": "Linear inequalities in one or two variables",
                "blurb": "Solve and interpret linear inequalities and their solution regions.",
                "figures": "occasionally: shaded half-plane or number line",
                "variants": [
                    "solve a one-variable inequality (flip on negative division at difficulty 3+)",
                    "model a constraint in context (at least / at most / no more than)",
                    "which point is/is not in the solution set of a two-variable inequality or system of inequalities",
                    "interpret the meaning of a boundary value in context",
                ],
                "spec": """\
WHAT IT TESTS: manipulating inequalities (including the sign flip), and
translating at least/at most language into <=, >=.
TYPICAL WORDING: "Which of the following is the solution to 4 - 2x > 10?" /
"A landscaper has at most $300 to spend on trees ($40 each) and shrubs ($15
each). Which inequality represents ...?" / "Which of the following points
(x, y) is a solution to the given system of inequalities?"
For point-checking items, display the inequality/system in block math and use
four coordinate-pair choices where exactly one satisfies everything.
DIFFICULTY KNOBS: 1-2 = one-step solves, direct translation. 3 = sign flip,
two-constraint contexts. 4-5 = systems of inequalities, greatest/least
integer value satisfying a constraint, interpretation of boundary.
DISTRACTOR TRAPS: forgetting to flip the inequality sign, <= vs <
("at least 5" -> x >= 5 not x > 5), reversed constraint direction, a point on
the boundary line when the inequality is strict.""",
            },
        ],
    },
    {
        "name": "Advanced Math",
        "share": "~35% of the Math section (13-15 questions per test)",
        "skills": [
            {
                "name": "Equivalent expressions",
                "blurb": "Rewrite polynomial, rational, radical, and exponential expressions.",
                "figures": "never",
                "variants": [
                    "polynomial add/subtract/multiply; which expression is equivalent",
                    "factor: GCF, trinomials, difference of squares; find a factor",
                    "exponent & radical rules: rewrite x^(a/b), simplify products/quotients of powers",
                    "rational expressions: simplify, combine over a common denominator, or rewrite improper ones as q + r/(x+k)",
                    "match coefficients: (ax + b)(cx + d) = px^2 + qx + r, find a constant",
                ],
                "spec": """\
WHAT IT TESTS: algebraic fluency — recognizing structure and rewriting
expressions without solving anything.
TYPICAL WORDING: "Which of the following is equivalent to
$(3x^2 - 5x) - (2x^2 + 4x - 1)$?" / "Which of the following is a factor of
...?" / "The expression $x^{\\frac{2}{3}} \\cdot x^{\\frac{1}{2}}$ is
equivalent to $x^{k}$. What is the value of k?" Stems are one sentence; the
expression is displayed in the stem.
DIFFICULTY KNOBS: 1-2 = combine like terms, GCF factoring, product of powers.
3 = trinomial factoring, binomial squares, fractional exponents. 4-5 =
nested/compound manipulations, equivalence with unknown constants solved by
matching coefficients, rational expression rewrites, sneaky difference of
squares like x^4 - 16.
DISTRACTOR TRAPS: sign error distributing a minus, (a+b)^2 = a^2 + b^2,
multiplying exponents where they should add, dropping a factor when
cancelling, matching only the leading coefficient.""",
            },
            {
                "name": "Nonlinear equations in one variable and systems of equations in two variables",
                "blurb": "Solve quadratics/radicals/rationals and linear-nonlinear systems.",
                "figures": "rare",
                "variants": [
                    "solve a quadratic (factoring, square roots, or quadratic formula); sum/product of solutions",
                    "discriminant reasoning: value(s) of a constant giving exactly one / no real solution",
                    "radical or rational equation (check extraneous solutions)",
                    "system of one linear + one quadratic equation; number of intersection points",
                ],
                "spec": """\
WHAT IT TESTS: solving nonlinear equations exactly and reasoning about how
many solutions exist.
TYPICAL WORDING: "What is the positive solution to the equation
$x^2 - 5x - 24 = 0$?" / "In the given equation, c is a constant. The equation
has exactly one real solution. What is the value of c?" / "If (x, y) is a
solution to the system shown, what is one possible value of x?" Systems are
displayed as two block equations.
DIFFICULTY KNOBS: 1-2 = factorable quadratics with integer roots, x^2 = k.
3 = quadratic formula with clean radicands, substitution systems. 4-5 =
discriminant conditions (b^2 - 4ac = 0, > 0, < 0), sum/product of roots via
Vieta, extraneous solutions of radical equations, tangency of line and
parabola.
DISTRACTOR TRAPS: sign of roots from factored form (x - 3 = 0 -> x = 3 not
-3), only finding one of two solutions, including an extraneous root,
b^2 - 4ac sign errors, solving for x but answering y in a system.""",
            },
            {
                "name": "Nonlinear functions",
                "blurb": "Quadratic, exponential, polynomial, and rational functions as graphs and models.",
                "figures": "often: parabolas, exponential curves, function tables",
                "variants": [
                    "quadratic structure: vertex, axis of symmetry, min/max, intercepts; convert standard/vertex/factored form",
                    "exponential growth/decay: build or interpret f(t) = a(b)^t (percent change, doubling/half-life)",
                    "evaluate/interpret from a graph or table; function transformations f(x) + k, f(x - h)",
                    "polynomial end behavior and zeros from factored form; projectile/area quadratic models",
                ],
                "spec": """\
WHAT IT TESTS: properties and modeling behavior of nonlinear function
families — the single broadest SAT math skill, so variant diversity matters
most here.
TYPICAL WORDING: "The function f is defined by f(x) = (x - 3)^2 - 4. What is
the minimum value of f?" / "The population doubles every 12 years... Which
function models the population t years after 2020?" / "The graph of y = f(x)
is shown. For what value of x does f reach its maximum?" / "Which of the
following could define the graph shown?"
GRAPHS: SVG with a smooth parabola or exponential curve on a labeled grid;
mark vertex/intercepts with labeled points. TABLES: KaTeX array showing a
constant ratio (exponential) or symmetric values (quadratic).
DIFFICULTY KNOBS: 1-2 = evaluate f(k), read vertex from vertex form or graph.
3 = build exponential models, x-intercepts from factored form, percent
growth. 4-5 = form conversion to expose a needed feature (complete the
square), b in (1 + r)^t with non-annual compounding periods, transformations
composed with interpretation, symmetry arguments (f(a) = f(b) -> vertex at
midpoint).
DISTRACTOR TRAPS: vertex (h, k) sign error from (x - h), growth factor b vs
percent r confusion (1.04 vs 0.04 vs 4), min value vs the x where it occurs,
decay written as (1 - r) misapplied, y-intercept vs initial value misreads.""",
            },
        ],
    },
    {
        "name": "Problem-Solving and Data Analysis",
        "share": "~15% of the Math section (5-7 questions per test)",
        "skills": [
            {
                "name": "Ratios, rates, proportional relationships, and units",
                "blurb": "Set up proportions, convert units, and work with rates.",
                "figures": "rare; occasional tables",
                "variants": [
                    "direct proportion: scale a ratio (recipes, maps, similar quantities)",
                    "unit conversion, possibly multi-step (include the conversion factor in the stem)",
                    "unit rate comparison or 'at this rate' extrapolation",
                    "density-type rates (population/area, mass/volume)",
                ],
                "spec": """\
WHAT IT TESTS: proportional reasoning in context.
TYPICAL WORDING: "The ratio of x to y is 3 to 8. If x = 21, what is y?" /
"A machine fills 240 bottles in 15 minutes. At this rate, how many bottles
does it fill in 4 hours?" / "1 mile = 1.6 kilometers. A road is 12 miles
long. What is its length in kilometers?" Always state non-obvious conversion
factors in the stem — the SAT never assumes memorized conversions beyond
time.
DIFFICULTY KNOBS: 1-2 = single proportion or single conversion. 3 = two-step
rates (convert then scale), unit rates with decimals. 4-5 = chained
conversions across three units, rates combined with percentages or with
reading a table value first.
DISTRACTOR TRAPS: inverted ratio (dividing the wrong way), converting the
wrong direction (multiply vs divide by 1.6), forgetting one leg of a
multi-step conversion, per-minute vs per-hour slips.""",
            },
            {
                "name": "Percentages",
                "blurb": "Percent of, percent change, and reverse percent problems.",
                "figures": "rare",
                "variants": [
                    "p% of q, or find the whole given a part",
                    "percent increase/decrease applied to a value (tax, discount, growth)",
                    "reverse: the discounted/increased price is given, find the original",
                    "successive percent changes or percent-of-a-percent",
                ],
                "spec": """\
WHAT IT TESTS: fluent translation between percent language and multiplication.
TYPICAL WORDING: "What is 35% of 80?" / "The price of a jacket was reduced by
20% to $48. What was the original price?" / "The value increased by 15% and
then decreased by 15%. The final value is what percent of the original?"
Keep contexts short (prices, populations, measurements).
DIFFICULTY KNOBS: 1-2 = direct percent-of. 3 = percent change, find-the-whole.
4-5 = reverse percent (divide by 1 +/- r), successive changes (not additive!),
expressing one quantity as a percent of another from a table.
DISTRACTOR TRAPS: subtracting percent from the reduced price instead of
dividing by (1 - r), adding successive percents (15% up then 15% down != 0%),
percent vs percentage-point confusion, part/whole inverted.""",
            },
            {
                "name": "One-variable data: distributions and measures of center and spread",
                "blurb": "Mean, median, mode, range, standard deviation, and distribution shape.",
                "figures": "often: dot plots, histograms, frequency tables, box plots",
                "variants": [
                    "compute/compare mean and median from a small data set or frequency table",
                    "effect of adding/removing an outlier on mean vs median",
                    "read a dot plot / histogram / box plot; compare two distributions' centers or spreads",
                    "find a missing value given the mean; compare standard deviations visually (no computation)",
                ],
                "spec": """\
WHAT IT TESTS: summary statistics and how distribution shape affects them.
The SAT NEVER asks students to compute standard deviation — only to compare
spreads qualitatively ("Data set A is more spread out from the mean, so it
has the larger standard deviation").
TYPICAL WORDING: "The dot plot shows the number of ... Which of the following
is true about the mean and median?" / "The mean of 5 numbers is 12. Four of
the numbers are ... What is the fifth?" / "Which statement best compares the
standard deviations of the two data sets shown?"
FIGURES: dot plots as columns of small circles above a labeled number line
(SVG); frequency tables as KaTeX arrays; histograms as SVG bars with axis
labels; box plots as SVG with five-number-summary labels.
DIFFICULTY KNOBS: 1-2 = compute mean/median/range of listed values. 3 = read
from a plot/frequency table, missing-value-given-mean. 4-5 = outlier effects
(mean moves, median resists), medians of grouped/frequency data where the
middle lands inside a bar, combined means of unequal groups.
DISTRACTOR TRAPS: median of unsorted data taken positionally, using n instead
of n+1 midpoint logic, mean vs median swapped, range vs standard deviation
conflated, weighting groups equally in a combined mean.""",
            },
            {
                "name": "Two-variable data: models and scatterplots",
                "blurb": "Scatterplots, lines/curves of best fit, and interpreting model parameters.",
                "figures": "almost always: a scatterplot with a fitted line/curve",
                "variants": [
                    "read the line of best fit: predict y at an x, or slope/intercept interpretation",
                    "residual-style: which point is farthest above/below the line; actual minus predicted",
                    "classify association: positive/negative, linear/nonlinear, strong/weak",
                    "choose the model type (linear vs exponential) from data behavior or equation",
                ],
                "spec": """\
WHAT IT TESTS: connecting bivariate data, fitted models, and context.
TYPICAL WORDING: "The scatterplot shows ... with a line of best fit. Which is
the best interpretation of the slope of the line?" / "For the data point at
x = 6, the actual y-value is how much greater than the value predicted by the
line of best fit?" / "Which of the following best describes the association
shown?"
FIGURES: SVG scatterplot, 8-12 points, labeled axes with realistic context
units, fitted line drawn through; make the trend and any target point
unambiguous (grid lines help).
DIFFICULTY KNOBS: 1-2 = read a predicted value, name the association. 3 =
slope interpretation with units, actual-vs-predicted for a marked point.
4-5 = comparing model fits, extrapolation caveats, interpreting parameters of
a given nonlinear fit equation.
DISTRACTOR TRAPS: actual vs predicted swapped, slope interpreted without its
per-unit meaning, reading the nearest data point instead of the line,
negative association called "no association" because points are scattered.""",
            },
            {
                "name": "Probability and conditional probability",
                "blurb": "Probability from counts, tables, and conditional restriction.",
                "figures": "often: two-way frequency tables",
                "variants": [
                    "simple probability from counts or a stated distribution",
                    "two-way table: joint probability P(A and B)",
                    "two-way table: conditional probability P(A | B) — restrict to a row/column",
                    "complement or 'not' events; expected counts from a probability",
                ],
                "spec": """\
WHAT IT TESTS: probability as favorable/total, especially with two-way tables
where the denominator must be restricted correctly.
TYPICAL WORDING: "The table shows ... If a student is selected at random from
those who chose biology, what is the probability the student is a junior?"
The phrase "from those who / given that" signals the conditional variant.
TABLES: KaTeX array two-way tables (2-3 rows x 2-3 columns plus a Total row
and column) with realistic small counts that don't require a calculator.
Answers are simplified fractions.
DIFFICULTY KNOBS: 1-2 = single-event probability from counts. 3 = joint
probability from a table. 4-5 = conditional probability, reverse conditionals
(P(A|B) vs P(B|A)), missing table cells to fill via totals first, expected
count = n x p.
DISTRACTOR TRAPS: using the grand total as denominator in a conditional,
P(A|B) vs P(B|A) swapped, joint vs conditional confusion, unsimplified or
inverted fractions.""",
            },
            {
                "name": "Inference from sample statistics and margin of error",
                "blurb": "Generalizing from random samples; interpreting margins of error.",
                "figures": "rare",
                "variants": [
                    "interpret a result +/- margin of error as a plausible-values interval",
                    "identify the population a sample result can generalize to (random selection scope)",
                    "effect of sample size on margin of error",
                    "scale a sample proportion to estimate a population count",
                ],
                "spec": """\
WHAT IT TESTS: statistical literacy — no computation beyond scaling a
proportion. Answer choices are usually full sentences; exactly one states a
correct, appropriately hedged conclusion.
TYPICAL WORDING: "A random sample of 400 residents ... 62% support, with a
margin of error of 4%. Which of the following is the most appropriate
conclusion?" Correct answers use careful language ("it is plausible that the
true percentage is between 58% and 66%"); wrong ones overclaim certainty,
apply the interval to the sample instead of the population, or generalize
beyond the sampled population.
DIFFICULTY KNOBS: 2-3 = pick the correct interpretation sentence, scale a
proportion to a population count. 4-5 = subtler scope errors (sample drawn
only from one school -> can't generalize to the city), sample-size vs margin
relationships, comparing two estimates whose intervals overlap.
DISTRACTOR TRAPS: claiming exactly 62% of the population, applying the margin
to individuals, certainty language ("definitely between"), generalizing to a
population that was never sampled.""",
            },
            {
                "name": "Evaluating statistical claims: observational studies and experiments",
                "blurb": "Causation vs association; what design and randomization permit.",
                "figures": "never",
                "variants": [
                    "observational study: which conclusion is appropriate (association only)",
                    "randomized experiment: when a causal conclusion is justified",
                    "identify the design flaw (self-selection, confounding, non-random sample)",
                ],
                "spec": """\
WHAT IT TESTS: whether a study design supports causal claims and to whom
results generalize. Pure reading/reasoning; sentence answer choices.
CORE LOGIC MATRIX (build every item from this): random ASSIGNMENT to
treatments -> causal claims allowed; random SELECTION from a population ->
generalization to that population allowed; neither -> association among the
participants only.
TYPICAL WORDING: "Researchers observed that people who ... also tended to ...
Which of the following is the most appropriate conclusion?" / "Participants
were randomly assigned to two groups ... Which conclusion is best supported?"
DIFFICULTY KNOBS: 2-3 = classic observational-study item where the correct
choice says "there is an association, but cause cannot be determined". 4-5 =
designs with one property but not the other (random assignment among
volunteers), or picking the specific flaw that invalidates a stated claim.
DISTRACTOR TRAPS: causal language for observational data ("watching TV causes
lower scores"), generalizing volunteers to everyone, reversing the direction
of a plausible cause, "no relationship" when an association was observed.""",
            },
        ],
    },
    {
        "name": "Geometry and Trigonometry",
        "share": "~15% of the Math section (5-7 questions per test)",
        "skills": [
            {
                "name": "Area and volume",
                "blurb": "Areas of plane figures and volumes/surface areas of solids.",
                "figures": "often: labeled solids or composite plane figures",
                "variants": [
                    "direct area/volume of a standard figure (formulas for cone/sphere/pyramid may be used; SAT provides them)",
                    "reverse: given area/volume, find a dimension",
                    "composite figures or removed regions",
                    "scaling effects: how area/volume changes when dimensions are multiplied",
                ],
                "spec": """\
WHAT IT TESTS: applying area/volume formulas forward and backward.
The real SAT provides a reference sheet with all standard formulas, so items
never test formula recall alone — they test setup and manipulation. State any
needed unusual formula in the stem if it isn't a common one.
TYPICAL WORDING: "A right circular cylinder has a volume of $96\\pi$ cubic
centimeters and a height of 6 centimeters. What is the radius of its base?" /
"The figure shows a rectangular prism ... What is its surface area?"
FIGURES: clean SVG of the solid or composite region with dimension labels;
omit the figure when the stem fully specifies dimensions.
DIFFICULTY KNOBS: 1-2 = plug into one formula. 3 = solve for a dimension,
composite rectangles. 4-5 = composite solids, ratio/scaling (doubling the
radius quadruples the area, x8 the volume), shared-dimension problems
(cylinder inscribed in ...), unit conversion inside the computation.
DISTRACTOR TRAPS: radius vs diameter, squaring vs cubing scale factors,
forgetting the 1/3 in cone/pyramid volume, area formula used where volume is
asked, dropping pi or doubling where halving is needed.""",
            },
            {
                "name": "Lines, angles, and triangles",
                "blurb": "Angle chasing, triangle properties, congruence and similarity.",
                "figures": "almost always: a labeled diagram",
                "variants": [
                    "parallel lines cut by a transversal; vertical/supplementary angle chains",
                    "triangle angle sum and exterior angle; isosceles/equilateral properties",
                    "similar triangles: set up the proportion for a missing side",
                    "triangle inequality or angle-side ordering",
                ],
                "spec": """\
WHAT IT TESTS: Euclidean angle and triangle reasoning from a diagram.
TYPICAL WORDING: "In the figure, lines l and m are parallel. What is the
value of x?" / "Triangle ABC is similar to triangle DEF, where A corresponds
to D ... What is the length of EF?" Similarity items often skip the figure
and state correspondences in text — do that for half of the similarity items.
FIGURES: SVG with parallel-line arrows, angle arcs with degree labels (use x
for the unknown), tick marks on congruent sides, vertices labeled with
capital letters. Add "Note: Figure not drawn to scale." when measures would
be misleading if measured.
DIFFICULTY KNOBS: 1-2 = one angle relationship. 3 = two-step angle chains,
basic similar-triangle proportions. 4-5 = multi-step chases through several
relationships, similarity ratios producing algebraic equations, overlapping
or nested triangles sharing an angle.
DISTRACTOR TRAPS: supplementary vs equal (co-interior vs alternate angles),
matching wrong corresponding sides in similarity, using 360 instead of 180,
answering an intermediate angle instead of the asked one.""",
            },
            {
                "name": "Right triangles and trigonometry",
                "blurb": "Pythagorean theorem, right-triangle trig ratios, special right triangles.",
                "figures": "often: labeled right triangle",
                "variants": [
                    "Pythagorean theorem: missing side, possibly in context (ladder, diagonal)",
                    "SOH-CAH-TOA: compute a ratio, side, or identify the correct expression",
                    "special right triangles 45-45-90 and 30-60-90",
                    "cofunction identity sin(x) = cos(90 - x); trig ratios of similar triangles",
                ],
                "spec": """\
WHAT IT TESTS: right-triangle metric relationships. Angles in degrees; exact
values only (no calculator-decimal trig answers). Answers with radicals stay
exact: $5\\sqrt{2}$, $\\frac{\\sqrt{3}}{2}$.
TYPICAL WORDING: "In right triangle ABC, the measure of angle C is 90 deg,
AB = 13, and BC = 5. What is the value of tan A?" / "In the triangle shown,
what is the value of x?" / "If sin(x deg) = cos(28 deg) and 0 < x < 90, what
is the value of x?"
FIGURES: SVG right triangle with the right-angle box, side labels, angle
labels; hypotenuse visually longest.
DIFFICULTY KNOBS: 1-2 = Pythagorean triple sides, read a ratio from labeled
sides. 3 = find a side via one trig ratio, special triangles. 4-5 =
cofunction identities, trig of the OTHER acute angle (tan B from data about
A), similar right triangles sharing ratios, radical simplification.
DISTRACTOR TRAPS: opposite/adjacent swapped, using the hypotenuse in tan,
Pythagorean subtraction vs addition (leg vs hypotenuse unknown), sqrt(a^2+b^2)
!= a + b, ratio for the wrong acute angle.""",
            },
            {
                "name": "Circles",
                "blurb": "Circle equations, arcs, sectors, central angles, and tangents.",
                "figures": "often: circle with marked center/points/sector",
                "variants": [
                    "equation of a circle (x-h)^2 + (y-k)^2 = r^2: center/radius, or complete the square",
                    "arc length and sector area as fractions of the circle",
                    "central/inscribed angles; radius-tangent perpendicularity",
                    "circumference/area relationships and radian-degree conversion",
                ],
                "spec": """\
WHAT IT TESTS: metric circle geometry and the standard-form circle equation.
TYPICAL WORDING: "A circle in the xy-plane has equation
$(x + 3)^2 + (y - 1)^2 = 25$. What are the center and radius?" / "In the
circle shown with center O, the measure of central angle AOB is 72 deg and
the radius is 10. What is the length of arc AB?" / "The equation
$x^2 + y^2 - 6x + 4y = 12$ ... What is the radius?"
Arc/sector answers stay exact in terms of pi.
FIGURES: SVG circle with center dot labeled O, radii to labeled boundary
points, the central angle marked; shade sectors lightly (#cbd5e1).
DIFFICULTY KNOBS: 1-2 = read center/radius from standard form, circumference
or area. 3 = arc length / sector area via angle/360, sign traps in (x + h).
4-5 = complete the square to find center/radius, inscribed angle = half the
central angle, tangent-radius right triangles combining skills, points
on/inside/outside a circle by distance.
DISTRACTOR TRAPS: center sign flipped from (x + 3), r^2 reported as r, arc
length vs sector area formulas swapped, using diameter as radius, halving vs
doubling with inscribed angles.""",
            },
        ],
    },
]

# ---------------------------------------------------------------------------
# The English taxonomy: 4 official R&W domains -> 10 official skills. Skill
# names are verbatim the question_type values already used across the site.
# ---------------------------------------------------------------------------

ENGLISH_DOMAINS = [
    {
        "name": "Craft and Structure",
        "share": "~28% of the Reading & Writing section (13-15 questions per test)",
        "skills": [
            {
                "name": "Words in Context",
                "blurb": "Choose the most logical and precise word/phrase for a blank, or gloss a word as used in a text.",
                "figures": "never",
                "variants": [
                    "fill-in-the-blank vocabulary: the passage sets up a logical relationship (contrast, cause, illustration) that exactly one word satisfies",
                    "meaning-in-context: a common word used in a secondary or figurative sense in a literary excerpt",
                    "precision cut: all four words are rough synonyms; connotation, register, or intensity decides",
                    "poetry or older prose where tone determines the word",
                ],
                "spec": """\
WHAT IT TESTS: high-utility academic vocabulary AND precision — the credited
word must satisfy the passage's logic, not merely its topic.
STANDARDIZED STEMS (use verbatim):
- Blank items: "Which choice completes the text with the most logical and
  precise word or phrase?" (blank = _______ in the passage; choices are single
  words or short phrases, same part of speech, all grammatically valid).
- Gloss items: 'As used in the text, what does the word "X" most nearly mean?'
PASSAGE: 25-100 words. Blank items are usually informational (a researcher's
finding, an artist's method) where a signal phrase ("but", "in other words",
"unlike") pins the blank's meaning. Gloss items usually quote literature.
DIFFICULTY BANDS: low = everyday words (persistent, curious) with the signal
adjacent to the blank. Mid = words like corroborate, ambivalent, negligible;
the signal sits a sentence away. High = fine connotation splits (exacting vs
punitive, novel vs anomalous), secondary senses of common words (the "economy"
of a poem's language, to "entertain" a hypothesis), and literary passages
where tone decides between two topically plausible words.
DISTRACTOR TRAPS: right topic but wrong logical direction (the passage signals
contrast, the word continues); near-synonym with the wrong connotation or
intensity; a word that fits the sentence alone but contradicts the passage's
larger claim; the PRIMARY meaning of a word the text uses in a secondary
sense.""",
            },
            {
                "name": "Text Structure and Purpose",
                "blurb": "Analyze what a sentence or whole text does rhetorically — its function, purpose, or overall structure.",
                "figures": "never",
                "variants": [
                    "function of the underlined sentence in the text as a whole (wrap the target in \\underline{...})",
                    "main purpose of the text (informational or literary)",
                    "overall structure of the text (e.g. presents a phenomenon, then evaluates two explanations)",
                    "literary/poetic passages where the function is a rhetorical move (concede, qualify, ironize)",
                ],
                "spec": """\
WHAT IT TESTS: rhetorical analysis — what a sentence or text DOES, as opposed
to what it says. Choices are written in abstract function language ("It
introduces a phenomenon that the rest of the text seeks to explain").
STANDARDIZED STEMS (use verbatim):
- "Which choice best describes the function of the underlined sentence in the
  text as a whole?" (underline exactly one sentence with \\underline{...})
- "Which choice best states the main purpose of the text?"
- "Which choice best describes the overall structure of the text?"
PASSAGE: 50-150 words with a genuine internal architecture (claim + evidence,
phenomenon + explanation, expectation + reversal) so functions are real.
DIFFICULTY BANDS: low = simple expository passage where the underlined
sentence plainly defines, exemplifies, or states the finding. Mid = the
function is relative to an argument (concedes a limitation, qualifies the
previous claim, pivots to a rival account). High = literary or poetic
passages with moves like ironic undercutting or reframing, and four choices
that ALL use plausible rhetorical vocabulary, differing only in the verb or
in what the move operates on.
DISTRACTOR TRAPS: describes the sentence's CONTENT rather than its function;
correctly describes a DIFFERENT sentence's function; right function verb aimed
at the wrong object ("criticizes the methodology" vs "criticizes the
conclusion"); whole-text purpose offered for a single sentence (or vice
versa); function that overstates ("proves", "refutes") what the text merely
suggests.""",
            },
            {
                "name": "Cross-Text Connections",
                "blurb": "Relate two short texts on the same topic: how one author would respond to the other.",
                "figures": "never",
                "variants": [
                    "how would the author of Text 2 most likely respond to a specific claim in Text 1",
                    "what both authors would agree on, despite differing emphases",
                    "how Text 2 relates to Text 1 (narrows, challenges, reframes, provides a mechanism for it)",
                    "scientist vs scientist over an interpretation; critic vs critic over a work",
                ],
                "spec": """\
WHAT IT TESTS: holding two viewpoints at once and mapping their exact
relationship — full disagreement is rare; the SAT prefers PARTIAL alignment
(accepts the finding, disputes the interpretation; agrees but narrows scope).
FORMAT: two labeled passages in the stem, each 40-90 words:
Text 1\\n<passage>\\n\\nText 2\\n<passage>\\n\\n<question>
STANDARDIZED STEMS (use verbatim):
- "Based on the texts, how would the author of Text 2 most likely respond to
  the [claim/argument/conclusion] in Text 1?"
- "Based on the texts, both authors would most likely agree with which
  statement?"
DIFFICULTY BANDS: low = plainly opposed positions with explicit stance
language. Mid = same evidence, different emphasis or confidence; the response
is a qualified "yes, but". High = subtle relations — Text 2 accepts Text 1's
data while disputing what it shows, or endorses the conclusion for a
different reason; the best distractor flips WHICH author holds which view or
overstates a mild reservation into rejection.
DISTRACTOR TRAPS: extreme response (total rejection/endorsement) where the
real relation is qualified; attributing Text 1's position to Text 2;
agreement on a point neither text actually addresses; right attitude but
wrong reason for it.""",
            },
        ],
    },
    {
        "name": "Information and Ideas",
        "share": "~26% of the Reading & Writing section (12-14 questions per test)",
        "skills": [
            {
                "name": "Central Ideas and Details",
                "blurb": "State the main idea of a text or retrieve what it directly says.",
                "figures": "never",
                "variants": [
                    "main idea of an informational passage",
                    "main idea of a literary excerpt or poem (assembled from figurative language)",
                    "detail retrieval: 'According to the text, why/what/how ...?'",
                    "'Based on the text, which statement is true about X?'",
                ],
                "spec": """\
WHAT IT TESTS: literal comprehension — the credited answer restates what the
text says, requiring no leap beyond the page.
STANDARDIZED STEMS (use verbatim):
- "Which choice best states the main idea of the text?"
- "According to the text, [why/what/how] ...?"
- "Based on the text, which choice best describes ...?"
PASSAGE: 50-150 words. For main-idea items the passage needs one governing
idea plus supporting material, so that "detail as main idea" is a live trap.
DIFFICULTY BANDS: low = the answer is nearly verbatim in one sentence of a
plain passage. Mid = the main idea must be assembled by paraphrasing across
two or three sentences; literary passages with mild figuration. High = older
literary prose or verse where the governing idea hides behind figurative
statements and syntax (inversions, long periodic sentences), or a detail
question whose answer sits inside a dense appositive a skimmer jumps over;
the best distractor is a TRUE detail from the text that is not the main
idea, or a near-paraphrase that silently drops a qualifier.
DISTRACTOR TRAPS: a supporting detail promoted to main idea; a claim broader
than the text supports; a paraphrase that contradicts a hedge ("some",
"often", "in early trials"); an appealing fact the text never states
(outside-knowledge bait).""",
            },
            {
                "name": "Command of Evidence",
                "blurb": "Pick the finding, quotation, or data point that best supports, illustrates, or weakens a claim.",
                "figures": "often: a data table (KaTeX array) or a bar/line graph (SVG) — REQUIRED for quantitative variants",
                "variants": [
                    "textual — support: a hypothesis or claim, then 'Which finding, if true, would most directly support ...?'",
                    "textual — weaken: same frame, 'most directly weaken/undermine' the claim",
                    "textual — illustrate: a scholar's claim about a (real or invented) literary work, then 'Which quotation most effectively illustrates the claim?' with four quotation choices",
                    "quantitative — TABLE: passage describes a study, a KaTeX array table carries the data, a concluding statement ends in a blank",
                    "quantitative — GRAPH: same structure with a labeled SVG bar or line chart instead of a table",
                ],
                "spec": """\
WHAT IT TESTS: evaluating the LINK between evidence and claim — the hardest
wrong answers are accurate statements or correct data readings that simply do
not bear on the claim.
STANDARDIZED STEMS (use verbatim):
- Textual: "Which finding, if true, would most directly support [the
  researchers' hypothesis / the author's claim]?" (or "...weaken...")
- Quotation: "Which quotation from [work] most effectively illustrates the
  claim?"
- Quantitative: "Which choice most effectively uses data from the [table/
  graph] to complete the statement?" — the passage's final sentence ends in
  _______ and the four choices each cite specific values.
QUANTITATIVE ITEMS — YOU MUST GENERATE THE DATA YOURSELF: invent a small,
realistic dataset and render it as a KaTeX array table or a fully labeled SVG
bar/line chart per the formatting rules (roughly half of the batch's items
should be quantitative). The displayed data must contain the exact values the
correct choice cites, AND values that make each distractor checkable-but-wrong
(a misread row, a true-but-irrelevant comparison). Keep numbers clean enough
to compare by eye — the R&W section allows no calculator.
DIFFICULTY BANDS: low = the support link is direct and the data read is a
single cell or bar. Mid = weaken items; comparisons across two rows or a
trend; quotation items where two quotes mention the right subject but only
one exhibits the claimed quality. High = the credited choice must combine two
cells or a trend AND match the claim's exact scope; the best distractor is a
PERFECTLY ACCURATE data reading that fails to address the claim — the classic
College Board killer — or a finding that supports a related-but-different
hypothesis.
DISTRACTOR TRAPS: true/accurate but irrelevant to the claim; misread rows,
columns, or axes; evidence that supports when the item asks for weakening;
a quotation that mentions the topic without exhibiting the claimed
relationship; data cited with the wrong magnitude or year.""",
            },
            {
                "name": "Inferences",
                "blurb": "Complete a passage's final blank with the conclusion its logic demands.",
                "figures": "never",
                "variants": [
                    "research chain: findings plus a complication, blank draws the warranted conclusion",
                    "two-position setup: scholars disagree, new evidence arrives, blank states what it suggests",
                    "historical or arts argument whose premises converge on the blank",
                    "premises include a qualifier or exception the completion must respect",
                ],
                "spec": """\
WHAT IT TESTS: drawing the one conclusion the premises license — no more, no
less. The passage builds an argument and stops one step short.
STANDARDIZED STEM (use verbatim): "Which choice most logically completes the
text?" — the passage's last sentence ends with _______ (often after
"suggesting that" / "which indicates that" / "therefore,").
PASSAGE: 70-150 words of tight reasoning. Every premise must matter; the
credited completion should follow from the premises the way a syllogism's
conclusion does, hedged to exactly the strength the premises support.
DIFFICULTY BANDS: low = two adjacent premises, conclusion nearly stated
already. Mid = combine findings from two sentences; respect one hedge. High =
premises carry a qualifier or an exception the completion must thread (a
finding true only "in mature forests", a method that rules out one
explanation but not another); the best distractor is what a careless reader
EXPECTS a study like this to conclude, or the credited idea stated one notch
too strongly.
DISTRACTOR TRAPS: too strong (premises support "may", the choice says
"will"); reverses cause and effect or direction of the relationship; a
plausible real-world claim the premises never touch (outside-knowledge bait);
merely restates a premise instead of concluding from it.""",
            },
        ],
    },
    {
        "name": "Standard English Conventions",
        "share": "~26% of the Reading & Writing section (11-15 questions per test)",
        "skills": [
            {
                "name": "Boundaries",
                "blurb": "Punctuate clause and sentence boundaries: joins, separations, and supplements.",
                "figures": "never",
                "variants": [
                    "two independent clauses: period / semicolon / comma + conjunction vs the comma splice",
                    "colon or dash introducing an explanation, list, or amplification",
                    "nonessential supplement set off by paired commas, dashes, or parentheses",
                    "NO punctuation needed: reject choices that splice a comma between subject and verb or before a restrictive phrase",
                ],
                "spec": """\
WHAT IT TESTS: sentence boundaries and supplements — where one clause ends,
another begins, and what may or must separate them. Choices differ ONLY in
punctuation (and any accompanying conjunction); the words are identical.
STANDARDIZED STEM (use verbatim): "Which choice completes the text so that it
conforms to the conventions of Standard English?" — the passage contains
_______ at the boundary in question.
PASSAGE: 40-100 words, informational, on a real-feeling scholarly topic (the
SAT sets conventions items in genuinely interesting material — keep that).
Build the sentence so its grammar is decidable purely from structure.
DIFFICULTY BANDS: low = two short, clearly independent clauses; one choice
punctuates legally, the others obviously splice or fuse. Mid = longer clauses
whose subjects hide mid-sentence; one nonessential phrase near the boundary.
High = stack hazards so every rule is needed at once: a long subject with an
interrupting nonessential phrase, a quotation or parenthetical abutting the
boundary, choices where EACH wrong option violates a DIFFERENT rule
(semicolon before a fragment; colon after a non-independent lead-in; single
comma where a pair is required; comma splice dressed up with a conjunctive
adverb like "however").
DISTRACTOR TRAPS: comma splice; fused sentence; semicolon before a dependent
clause or fragment; colon not preceded by an independent clause; mixing a
dash with a comma to close one supplement; a lone comma between subject and
verb.""",
            },
            {
                "name": "Form, Structure, and Sense",
                "blurb": "Choose the word form that fits: agreement, tense, pronouns, modifiers, possessives, parallelism.",
                "figures": "never",
                "variants": [
                    "subject-verb agreement across an interrupting phrase or inverted structure",
                    "verb tense/aspect consistent with the passage's time frame",
                    "pronoun-antecedent agreement (and its/it's, whose/who's, their/there)",
                    "dangling or misplaced modifier: the opener must describe the subject that follows",
                    "plural vs possessive forms (species', researchers', the Joneses') and parallel structure in lists or comparisons",
                ],
                "spec": """\
WHAT IT TESTS: within-sentence grammar — the choices differ in word FORM
(verb inflection, pronoun, possessive, modifier placement), not punctuation.
STANDARDIZED STEM (use verbatim): "Which choice completes the text so that it
conforms to the conventions of Standard English?" — with _______ at the
tested spot.
PASSAGE: 40-100 words, informational register, real-feeling topic. Engineer
the syntax so exactly one form is correct and the distractor forms are
genuinely tempting in context.
DIFFICULTY BANDS: low = subject sits next to its verb; the wrong forms sound
wrong out loud. Mid = subject separated from verb by a prepositional phrase
or appositive ("the collection of manuscripts _______"); simple tense-frame
consistency. High = agreement across a relative clause, inverted or delayed
subjects ("crucial to the theory _______ two assumptions"), quantifier
subjects ("each of the studies"), stacked possessives on plural nouns ending
in s, and participial openers where the nearest plausible noun is NOT the
doer — the classic dangling-modifier trap that reads smoothly aloud.
DISTRACTOR TRAPS: verb agreeing with the nearest noun instead of the true
subject; tense shifted away from the passage's established frame; pronoun
matching the wrong (or a missing) antecedent; opener modifying the wrong
noun; plural where the possessive is needed and vice versa; broken
parallelism in the final list slot.""",
            },
        ],
    },
    {
        "name": "Expression of Ideas",
        "share": "~20% of the Reading & Writing section (8-12 questions per test)",
        "skills": [
            {
                "name": "Rhetorical Synthesis",
                "blurb": "Use a student's bulleted research notes to accomplish a stated rhetorical goal.",
                "figures": "never (the notes render as *** bullet lines)",
                "variants": [
                    "emphasize a similarity or a difference between two things in the notes",
                    "introduce the subject to an audience unfamiliar with it",
                    "stress the aim, method, or result of a study",
                    "present a sequence or cause-and-effect relationship from the notes",
                    "make and support a recommendation or generalization the notes justify",
                ],
                "spec": """\
WHAT IT TESTS: matching a sentence to a rhetorical GOAL — every choice is
factually consistent with the notes; only one accomplishes the stated goal.
FIXED FRAME (use verbatim, in this order):
"While researching a topic, a student has taken the following notes:"
then 4-6 bullet notes, EACH on its own line starting with *** (renderer
bullet syntax), then:
"The student wants to [GOAL]. Which choice most effectively uses relevant
information from the notes to accomplish this goal?"
Choices are single complete sentences assembled from the notes.
NOTES DESIGN: notes are short declarative facts (who/what/when/finding), and
must contain BOTH the material the goal needs AND plausible material it does
not, so relevance selection is real work.
DIFFICULTY BANDS: low = the goal names one thing and one note-pair delivers
it. Mid = the goal requires combining two notes and ignoring two others. High
= a TWO-PART goal ("emphasize the similarity in method AND the difference in
result") where the best distractor satisfies exactly one part, or two choices
that both touch the goal but only one addresses BOTH named subjects; goals
whose key verb ("contrast", "introduce", "justify") each distractor honors
in letter but not in function.
DISTRACTOR TRAPS: factually accurate sentence aimed at the wrong goal;
answers half of a two-part goal; emphasizes the opposite element (a
difference when similarity is asked); assumes audience familiarity when the
goal says "unfamiliar"; smuggles in a claim that appears nowhere in the
notes.""",
            },
            {
                "name": "Transitions",
                "blurb": "Pick the transition word or phrase that expresses the true logical relationship.",
                "figures": "never",
                "variants": [
                    "contrast vs continuation (however / in addition / likewise)",
                    "cause or consequence (therefore / as a result / consequently)",
                    "illustration or specification (for example / specifically / in particular)",
                    "concession, reinforcement, or sequence (granted / indeed / subsequently / finally)",
                ],
                "spec": """\
WHAT IT TESTS: the logical relationship between ideas — the four choices are
transitions from DIFFERENT logical classes, so the item is solved by
classifying the relationship, not by ear.
STANDARDIZED STEM (use verbatim): "Which choice completes the text with the
most logical transition?" — the blank _______ opens a sentence (usually the
last), followed by a comma.
PASSAGE: 40-100 words, informational. The sentences before and after the
blank must pin the relationship unambiguously.
DIFFICULTY BANDS: low = a blunt two-sentence relationship (plain contrast or
plain result) with clearly distinct choices. Mid = the relationship spans
more than the adjacent sentence — the blank's sentence contrasts with an idea
TWO sentences back while continuing the one just before it, so proximity
matching fails. High = neighboring logical classes that students conflate:
concession ("granted") vs contrast ("however"), reinforcement ("indeed") vs
specification ("specifically"), result ("consequently") vs sequence
("subsequently"); passages that continue a TOPIC while pivoting in LOGIC, so
the tempting continuation transition is wrong.
DISTRACTOR TRAPS: matches the adjacent sentence but not the paragraph's true
pivot; same general class but wrong precision or strength; mistakes topic
continuity for logical continuity; a sequence word where the relationship is
causal (or vice versa).""",
            },
        ],
    },
]

DOMAINS = MATH_DOMAINS + ENGLISH_DOMAINS

ENGLISH_SKILL_NAMES = {
    skill["name"] for domain in ENGLISH_DOMAINS for skill in domain["skills"]
}

MATH_SKILL_NAMES = {
    skill["name"] for domain in MATH_DOMAINS for skill in domain["skills"]
}

SKILL_INDEX = {
    skill["name"]: (domain, skill)
    for domain in DOMAINS
    for skill in domain["skills"]
}


def subject_of_type(question_type):
    """Which subject a question_type belongs to. Unknown types read as english,
    matching the practice lanes' default."""
    return 'math' if question_type in MATH_SKILL_NAMES else 'english'


def build_prompt(skill_name, difficulty, count):
    """Assemble the full generation prompt for one skill/difficulty batch.

    Always mixed: the batch draws from all of the skill's sub-topics for variety
    (there is no single-sub-variant mode)."""
    domain, skill = SKILL_INDEX[skill_name]
    variants = "\n".join("- %s" % v for v in skill.get("variants", []))
    variant_clause = (
        "SUB-TOPICS to mix across this batch for variety (rotate freely; do not "
        "stick to one, and feel free to invent fresh angles beyond this list):\n"
        "%s\n" % variants if variants else ""
    )
    english = skill_name in ENGLISH_SKILL_NAMES
    return (ENGLISH_BASE_PROMPT if english else BASE_PROMPT).format(
        format_rules=ENGLISH_FORMAT_RULES if english else FORMAT_RULES,
        difficulty_rubric=ENGLISH_DIFFICULTY_RUBRIC if english else DIFFICULTY_RUBRIC,
        domain="%s (%s)" % (domain["name"], domain["share"]),
        skill=skill_name,
        spec=skill["spec"],
        variant_clause=variant_clause,
        count=count,
        difficulty=difficulty,
    )


# ---------------------------------------------------------------------------
# LLM calls. Keys come from env; if none configured the admin UI falls back to
# a copy-the-prompt / paste-the-output workflow (works with claude.ai/ChatGPT
# web subscriptions, no API billing needed).
# ---------------------------------------------------------------------------

def api_status():
    return {
        "anthropic": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "openai": bool(os.environ.get("OPENAI_API_KEY")),
    }


def call_llm(prompt):
    """Return raw model text, or None when no API key is configured."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        import anthropic
        client = anthropic.Anthropic()
        with client.messages.stream(
            model=os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-8"),
            max_tokens=32000,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            message = stream.get_final_message()
        return "".join(b.text for b in message.content if b.type == "text")

    if os.environ.get("OPENAI_API_KEY"):
        import requests
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": "Bearer %s" % os.environ["OPENAI_API_KEY"]},
            json={
                "model": os.environ.get("OPENAI_MODEL", "gpt-4o"),
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 16000,
            },
            timeout=300,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    return None


def parse_questions(raw):
    """Extract the JSON question array from model output (tolerates fences/prose)."""
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    else:
        start, end = text.find("["), text.rfind("]")
        if start == -1 or end <= start:
            raise ValueError("No JSON array found in model output")
        text = text[start:end + 1]
    questions = json.loads(text)
    if not isinstance(questions, list):
        raise ValueError("Model output is not a JSON array")
    required = {"question", "choice_a", "choice_b", "choice_c", "choice_d",
                "answer", "difficulty", "question_type", "explanation"}
    for q in questions:
        missing = required - set(q)
        if missing:
            raise ValueError("Question missing fields: %s" % ", ".join(sorted(missing)))
        if str(q["answer"]).upper() not in ("A", "B", "C", "D"):
            raise ValueError("Invalid answer letter: %r" % q["answer"])
        q["answer"] = str(q["answer"]).upper()
        q["difficulty"] = max(1, min(5, int(q["difficulty"])))
    return questions
