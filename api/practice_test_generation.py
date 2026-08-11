"""Prompt building and validation for manually generated SAT test modules."""

from collections import Counter

from api import generation
from api.practice_test_scoring import student_response_is_valid


QUESTION_COUNTS = {'english': 27, 'math': 22}
DOMAIN_RANGES = {
    'english': {
        'Craft and Structure': (7, 8),
        'Information and Ideas': (6, 7),
        'Standard English Conventions': (6, 7),
        'Expression of Ideas': (5, 6),
    },
    'math': {
        'Algebra': (7, 8),
        'Advanced Math': (7, 8),
        'Problem-Solving and Data Analysis': (3, 4),
        'Geometry and Trigonometry': (3, 4),
    },
}
ENGLISH_DOMAIN_ORDER = list(DOMAIN_RANGES['english'])
ENGLISH_SKILL_RANK = {
    'Words in Context': 0,
    'Text Structure and Purpose': 1,
    'Cross-Text Connections': 2,
    'Central Ideas and Details': 3,
    'Command of Evidence': 4,
    'Inferences': 5,
    # College Board groups types within each domain except Standard English
    # Conventions, so these two skills may be interleaved.
    'Boundaries': 6,
    'Form, Structure, and Sense': 6,
    'Transitions': 7,
    'Rhetorical Synthesis': 8,
}
ROUTE_GUIDANCE = {
    'A': (
        'Module 1 (routing): use a broad, centered mix of easy, medium, and hard '
        'questions. Target an average difficulty from 2.5 through 3.5, include '
        'questions at both difficulty 1-2 and difficulty 4-5, and do not let one '
        'difficulty dominate.'
    ),
    'B': (
        'Module 2 (lower-difficulty route): keep a genuine mix, but shift the '
        'average lower. Target an average from 1.8 through 2.8; most items should '
        'be difficulty 1-3, with a small number of difficulty 4 items so this is '
        'not an all-easy worksheet.'
    ),
    'C': (
        'Module 2 (higher-difficulty route): keep a genuine mix, but shift the '
        'average higher. Target an average from 3.2 through 4.4; most items should '
        'be difficulty 3-5. Follow the subject-specific calibration below for '
        'the exact distribution. Hard means subtle SAT reasoning, never tedious '
        'or out of scope.'
    ),
}
SUBJECT_ROUTE_CALIBRATION = {
    ('english', 'A'): (
        'Reading and Writing calibration: keep the average at or below 3.0. '
        'This routing module should feel centered rather than punishing: use '
        'mostly difficulty 2-3 items, a smaller number of difficulty 1 items, '
        'and only a few carefully chosen difficulty 4-5 items.'
    ),
    ('english', 'B'): (
        'Reading and Writing quantitative-evidence calibration: every Command '
        'of Evidence item that uses a graph must be difficulty 3, 4, or 5. Do '
        'not make it a one-step lookup; require the student to connect an exact '
        'visual trend or comparison to the passage claim while keeping the '
        'lower-route module average in range.'
    ),
    ('english', 'C'): (
        'Reading and Writing quantitative-evidence calibration: every Command '
        'of Evidence item that uses a graph must be difficulty 3, 4, or 5. Do '
        'not make it a one-step lookup; require the student to connect an exact '
        'visual trend or comparison to the passage claim. Across multiple graph '
        'items, vary levels 3-5 rather than assigning them all one level. Retain '
        'a few accessible difficulty 1-2 items elsewhere in the module.'
    ),
    ('math', 'C'): (
        'Math calibration: questions 1-15 must each be difficulty 3 or 4, '
        'providing a sustained authentic medium-hard baseline. Continue rising '
        'after question 15 and reserve difficulty 5 for the final four '
        'positions (19-22), with at least two difficulty-5 questions there. '
        'The hardest items should require a hidden modeling or algebraic insight, '
        'not long computation or out-of-scope content.'
    ),
}


def _domains(subject):
    return generation.ENGLISH_DOMAINS if subject == 'english' else generation.MATH_DOMAINS


def _renderer_rules(subject):
    rules = generation.ENGLISH_FORMAT_RULES if subject == 'english' else generation.FORMAT_RULES
    return rules.split('\nANSWER-KEY BALANCE', 1)[0].rstrip()


def _skill_guide(subject):
    sections = []
    for domain in _domains(subject):
        skills = []
        for skill in domain['skills']:
            variants = '\n'.join('  - %s' % item for item in skill.get('variants', []))
            skills.append(
                'SKILL: %s\n%s%s' % (
                    skill['name'], skill['spec'],
                    ('\nUSE A VARIED MIX OF THESE SUB-TOPICS:\n%s' % variants) if variants else '',
                )
            )
        sections.append(
            '============================================================\n'
            'DOMAIN: %s (%s of the full section)\n'
            '============================================================\n%s' % (
                domain['name'], domain['share'], '\n\n'.join(skills),
            )
        )
    return '\n\n'.join(sections)


def build_module_prompt(subject, route):
    if subject not in QUESTION_COUNTS or route not in ROUTE_GUIDANCE:
        raise ValueError('Choose a valid subject and module route')

    count = QUESTION_COUNTS[subject]
    if subject == 'english':
        composition = """\
Generate exactly 27 scored questions. Every question counts toward the score.
Choose a fresh valid domain count vector:
- Craft and Structure: 7-8
- Information and Ideas: 6-7
- Standard English Conventions: 6-7
- Expression of Ideas: 5-6
The four counts MUST sum to 27.

Skill bounds and realistic order:
1. Craft and Structure first: begin the module with exactly 3-4 consecutive
   Words in Context questions, then use Text Structure and Purpose and
   Cross-Text Connections. Keep each skill grouped and move from easier to
   harder questions within the group.
2. Information and Ideas next: vary Central Ideas and Details, Command of
   Evidence (including both textual and quantitative), and Inferences. Use
   roughly 2-3 of each, adjusted to the chosen domain total.
3. Standard English Conventions next: use 3-4 Boundaries and 3-4 Form,
   Structure, and Sense questions, adjusted to the chosen domain total.
   Treat the precise convention being tested as the unit of variety: no single
   grammar point may appear more than twice in the module. For example, do not
   test the same comma boundary, colon/semicolon distinction, agreement rule,
   modifier placement, possessive form, or verb-form distinction more than
   twice, even if the surrounding passages differ.
4. Expression of Ideas last: use 2-3 Transitions followed by 2-3 Rhetorical
   Synthesis questions, adjusted to the chosen domain total. Every Rhetorical
   Synthesis (student-notes) question MUST come after every Transitions question
   and MUST occupy the final positions in the module.

Every item is four-option multiple choice. Use one passage or passage pair of
25-150 words per question. Across the module, deliberately mix literature,
history/social studies, humanities, and science. Do not copy released SAT
items or copyrighted passages; write original text or use properly attributed
public-domain literature. Similar skills are grouped, and difficulty rises
within each group, just as on the digital SAT."""
    else:
        composition = """\
Generate exactly 22 scored questions. Every question counts toward the score.
Choose a fresh valid domain count vector:
- Algebra: 7-8
- Advanced Math: 7-8
- Problem-Solving and Data Analysis: 3-4
- Geometry and Trigonometry: 3-4
The four counts MUST sum to 22.

Use all four domains and vary the specific skills inside them. Across the
module, include 16-18 multiple-choice questions and 4-6 student-produced
response questions. Make 6-7 questions contextual word problems (about 30%),
using accessible science, social-science, or real-world settings that require
no outside knowledge. Arrange the ENTIRE module from easiest to hardest,
regardless of domain or response format. Calculator use is allowed throughout.
Stay strictly within SAT scope: difficulty 5 is the hardest authentic SAT item,
not AMC/AIME material. Never copy or lightly reskin a released item.

Student-produced response answer rules:
- The response must be numeric and must fit the Bluebook entry space: at most
  5 characters for a positive answer or 6 including a negative sign.
- Use an integer, terminating decimal, or improper fraction as the exact answer.
  Never use a mixed number, percent sign, comma, currency symbol, or plus sign.
- If more than one mathematically distinct value is correct, put every credited
  exact value in "answer", separated by semicolons (example: "2;3"). The
  student may enter any one of them.
- Do not enumerate equivalent spellings such as "3.5;3.50;7/2". SAT Duel grades
  equivalent fractions and decimals automatically. It also accepts a repeating
  decimal truncated or rounded using every available entry character (for
  example, 2/3 accepts .6666, .6667, 0.666, or 0.667).
- Design the problem so at least one exact fraction/decimal or permitted rounded
  decimal fits the entry space."""

    return f"""\
You are the lead assessment designer for a high-quality original digital SAT
practice test. Build ONE complete {'Reading and Writing' if subject == 'english' else 'Math'}
module that can be pasted into SAT Duel. This is a manual workflow: return the
finished JSON only; do not call APIs or describe your process. Browse only when
needed to verify a real source, attribution, quotation, or factual claim.

OFFICIAL STRUCTURE TO MIMIC
- This module has {count} questions and is timed for {'32' if subject == 'english' else '35'} minutes.
- Every question in this SAT Duel module is scored. Do not include or label any
  question as a pretest, experimental, or unscored item.
- The first module is a broad difficulty mix. The second module is still mixed,
  but has a lower or higher average based on routing performance.
- All questions must be original, self-contained, unambiguous, solvable, and
  have one unambiguous credited answer set.

SELECTED ADAPTIVE ROUTE
{ROUTE_GUIDANCE[route]}
{SUBJECT_ROUTE_CALIBRATION.get((subject, route), '')}

DIFFICULTY SCALE FOR THIS PRACTICE TEST
1 = easy authentic SAT; direct but not trivial.
2 = medium-low; one clear reasoning step and plausible distractors.
3 = central SAT difficulty; multi-step or moderately subtle.
4 = hard authentic SAT; strong distractors and a non-obvious reasoning step.
5 = hardest authentic SAT; discriminates top scorers while remaining fully in
scope, concise, fair, and hand-solvable. Never use contest-only knowledge.

COMPOSITION AND ORDER
{composition}

RANDOMIZATION WITHOUT DRIFT
- Choose counts inside the stated ranges; do not reuse one fixed blueprint for
  every module. Vary neighboring skill counts, subject matter, representations,
  and correct-answer positions.
- Do not repeat a setup, passage topic, equation template, named researcher, or
  distractor pattern within this module.
- Design this as one half of a full test whose other module may cover the same
  broad skills. Use a wide range of precise test points and representations,
  and avoid stock stem, passage, grammar, equation, and distractor structures
  that would make two independently generated modules feel repetitive.
- Balance multiple-choice keys A/B/C/D so the largest and smallest counts differ
  by no more than 2. Never use the same key more than 3 times consecutively.

SOURCE INTEGRITY
- Any named author, title, publication, researcher, study, institution, date,
  quotation, or factual source attribution MUST be real, accurate, and
  independently verifiable. Never invent a source, citation, or quotation.
- If a passage says it is adapted from a work, use a real public-domain work
  with accurate attribution and faithful wording. Do not copy released SAT
  questions or copyrighted modern passages.
- If browsing or reference tools are available, use them only to verify source
  facts before drafting. If verification is unavailable, write an original,
  unattributed passage and remove claims that imply a real source.
- Rhetorical Synthesis notes that name people, studies, works, institutions, or
  statistics must likewise use accurate, verifiable facts.

{_renderer_rules(subject)}

OUTPUT CONTRACT
Return ONLY one Markdown code block labeled json containing a JSON array of
exactly {count} objects in presentation order. No prose before or after it.
Every object must contain:
{{
  "order": 1,
  "response_type": "multiple_choice" or "student_produced",
  "question": "complete rendered stem",
  "choice_a": "...", "choice_b": "...", "choice_c": "...", "choice_d": "...",
  "answer": "A" | "B" | "C" | "D" for multiple choice, or exact numeric answer value(s) separated by semicolons for student-produced response,
  "difficulty": 1 | 2 | 3 | 4 | 5,
  "question_type": "one exact skill name from the guide below",
  "explanation": "worked proof of the answer plus why each distractor fails"
}}
For student-produced response, set all four choice fields to empty strings and
follow every student-response answer rule above. Reading and Writing may not
use student-produced response. Order values must be consecutive 1 through
{count}. JSON strings must escape backslashes and may not contain raw newlines.

FINAL QUALITY CONTROL BEFORE YOU ANSWER
1. Solve every question independently; confirm the key is unique and accurate.
2. Verify exact question count, domain/skill bounds, route difficulty average,
   response-format count, and presentation order. Confirm every item is scored.
3. Verify every question_type exactly matches a skill heading below.
4. Scan for accidental copied phrasing, repeated templates, ambiguous choices,
   broken markup, fake factual claims, and answer-key imbalance; repair all.

AUTHORITATIVE SKILL-WRITING GUIDE
{_skill_guide(subject)}
"""


def validate_module_questions(questions, subject, route):
    if subject not in QUESTION_COUNTS or route not in ROUTE_GUIDANCE:
        raise ValueError('Choose a valid subject and module route')
    expected = QUESTION_COUNTS[subject]
    if not isinstance(questions, list) or len(questions) != expected:
        raise ValueError(f'{subject.title()} modules require exactly {expected} questions')

    normalized = []
    for index, raw in enumerate(questions, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f'Question {index} must be an object')
        question_type = generation.normalize_question_type(raw.get('question_type'))
        valid_types = generation.ENGLISH_SKILL_NAMES if subject == 'english' else generation.MATH_SKILL_NAMES
        if question_type not in valid_types:
            raise ValueError(f'Question {index} has an invalid {subject} question type')
        try:
            difficulty = int(raw.get('difficulty'))
        except (TypeError, ValueError):
            difficulty = 0
        if difficulty not in range(1, 6):
            raise ValueError(f'Question {index} difficulty must be 1 through 5')
        response_type = raw.get('response_type', 'multiple_choice')
        if response_type not in {'multiple_choice', 'student_produced'}:
            raise ValueError(f'Question {index} has an invalid response type')
        if subject == 'english' and response_type != 'multiple_choice':
            raise ValueError('Reading and Writing questions must be multiple choice')
        if raw.get('is_pretest') is True:
            raise ValueError('Pretest questions are not supported; every question is scored')

        text = str(raw.get('question', '')).strip()
        explanation = str(raw.get('explanation', '')).strip()
        answer = str(raw.get('answer', '')).strip()
        if not text or not explanation or not answer:
            raise ValueError(f'Question {index} needs a question, answer, and explanation')
        choices = [str(raw.get(f'choice_{letter}', '')).strip() for letter in 'abcd']
        if response_type == 'multiple_choice':
            answer = answer.upper()
            if not all(choices) or answer not in 'ABCD' or len(answer) != 1:
                raise ValueError(f'Question {index} needs four choices and an A-D answer')
        elif any(choices):
            raise ValueError(f'Question {index} student-produced response choices must be blank')
        else:
            accepted = [item.strip() for item in answer.split(';') if item.strip()]
            if not accepted or len(accepted) > 10 or any(not student_response_is_valid(item) for item in accepted):
                raise ValueError(
                    f'Question {index} student-produced answers must use valid Bluebook numeric entry formats'
                )
            answer = ';'.join(accepted)

        normalized.append({
            'order': index,
            'response_type': response_type,
            'question': text,
            **{f'choice_{letter}': choices[position] for position, letter in enumerate('abcd')},
            'answer': answer,
            'difficulty': difficulty,
            'question_type': question_type,
            'explanation': explanation,
            'is_pretest': False,
        })

    if len({q['question'] for q in normalized}) != expected:
        raise ValueError('Every question in the module must be unique')
    domain_counts = Counter(generation.SKILL_INDEX[q['question_type']][0]['name'] for q in normalized)
    for domain, (minimum, maximum) in DOMAIN_RANGES[subject].items():
        if not minimum <= domain_counts[domain] <= maximum:
            raise ValueError(f'{domain} requires {minimum}-{maximum} questions')

    difficulties = [q['difficulty'] for q in normalized]
    average = sum(difficulties) / expected
    if subject == 'english' and route == 'A':
        lower, upper = (2.5, 3.0)
    else:
        lower, upper = {'A': (2.5, 3.5), 'B': (1.8, 2.8), 'C': (3.2, 4.4)}[route]
    if not lower <= average <= upper:
        raise ValueError(f'Module {route} average difficulty must be {lower}-{upper}')
    if route == 'A' and (min(difficulties) > 2 or max(difficulties) < 4):
        raise ValueError('Module A must include both accessible and hard questions')
    if route == 'B' and (min(difficulties) > 2 or max(difficulties) < 3):
        raise ValueError('Module B must remain a mix of lower and medium difficulty questions')
    if route == 'C' and subject == 'english' and (min(difficulties) > 2 or max(difficulties) < 4):
        raise ValueError('Module C must retain accessible questions alongside hard questions')

    if subject == 'math':
        if difficulties != sorted(difficulties):
            raise ValueError('Math questions must be ordered from easiest to hardest')
        if route == 'C':
            if any(difficulty not in (3, 4) for difficulty in difficulties[:15]):
                raise ValueError('Math Module C questions 1-15 must be difficulty 3-4')
            if any(difficulty == 5 for difficulty in difficulties[:18]):
                raise ValueError('Math Module C must reserve difficulty 5 for questions 19-22')
            if sum(difficulty == 5 for difficulty in difficulties[18:]) < 2:
                raise ValueError('Math Module C requires at least two difficulty-5 questions in positions 19-22')
        spr_count = sum(q['response_type'] == 'student_produced' for q in normalized)
        if not 4 <= spr_count <= 6:
            raise ValueError('Math modules require 4-6 student-produced response questions')
    else:
        domain_order = [ENGLISH_DOMAIN_ORDER.index(generation.SKILL_INDEX[q['question_type']][0]['name']) for q in normalized]
        if domain_order != sorted(domain_order):
            raise ValueError('Reading and Writing questions must follow the official domain order')
        vocab_count = sum(q['question_type'] == 'Words in Context' for q in normalized)
        if vocab_count not in (3, 4) or any(q['question_type'] != 'Words in Context' for q in normalized[:vocab_count]):
            raise ValueError('Reading and Writing modules must begin with 3-4 Words in Context questions')
        skill_order = [ENGLISH_SKILL_RANK[q['question_type']] for q in normalized]
        if skill_order != sorted(skill_order):
            raise ValueError(
                'Reading and Writing skills must follow official grouped order, with '
                'Transitions before final Rhetorical Synthesis questions'
            )

    key_counts = Counter(q['answer'] for q in normalized if q['response_type'] == 'multiple_choice')
    counts = [key_counts[letter] for letter in 'ABCD']
    if max(counts) - min(counts) > 2:
        raise ValueError('Multiple-choice answer keys must be balanced across A-D')
    return normalized
