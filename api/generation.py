"""AI question generation: SAT Math taxonomy, prompt engineering, and LLM calls.

The taxonomy mirrors the College Board Digital SAT question bank exactly
(4 content domains, 19 skills). Each skill carries a detailed spec that is
spliced into a shared base prompt. English (Reading & Writing) domains can be
added later as new entries in DOMAINS — everything downstream is domain-agnostic.

Rendering contract with the frontend (RenderWithMath.jsx):
  - Inline math:  $...$          (KaTeX)
  - Block math:   $$...$$        (KaTeX; tables use \\begin{array}{|c|c|} inside)
  - Figures:      [svg]<svg ...>...</svg>[/svg]  (sanitized inline SVG)
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

ANSWER-KEY BALANCE (IMPORTANT — do not default to one letter):
- Spread the correct answers across A, B, C, and D. Across a batch aim for a
  roughly even split; do NOT let any letter dominate and do NOT habitually put
  the answer at C (or B). For each single question the correct choice should be
  equally likely to sit in any of the four slots — choose its position at random.
- Before finalizing, scan your batch's answer key. If one letter appears much
  more than the others, REORDER the choices of some questions to rebalance it.

EXPLANATION:
- Show the efficient solution path step by step in KaTeX (use \\n between steps,
  and $$...$$ for a key line). For difficulty 4-5, first name the KEY INSIGHT
  that unlocks the problem, then the steps.
- End with one short line per wrong choice naming the mistake that produces it,
  e.g. "Choice B results from ...".

OUTPUT CONTRACT (strict):
Return ONLY a JSON array — no markdown fences, no commentary. Each element:
{
  "question": "stem text with $KaTeX$ and optional [svg]...[/svg] / $$array$$ blocks",
  "choice_a": "...", "choice_b": "...", "choice_c": "...", "choice_d": "...",
  "answer": "A" | "B" | "C" | "D",
  "difficulty": <int 1-5>,
  "question_type": "<the skill name given below, verbatim>",
  "explanation": "worked solution + distractor notes"
}
JSON strings must escape backslashes (write \\\\frac in the JSON source so the
parsed value is \\frac) and must not contain raw newlines — use \\n.
"""

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
# The taxonomy: 4 official domains -> 19 official skills, each with a
# hand-engineered spec. Variants break broad skills into sub-types while
# keeping the official skill as the stored question_type.
# ---------------------------------------------------------------------------

DOMAINS = [
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

SKILL_INDEX = {
    skill["name"]: (domain, skill)
    for domain in DOMAINS
    for skill in domain["skills"]
}


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
    return BASE_PROMPT.format(
        format_rules=FORMAT_RULES,
        difficulty_rubric=DIFFICULTY_RUBRIC,
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
