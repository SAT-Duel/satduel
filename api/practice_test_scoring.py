"""Fixed-parameter IRT scoring for generated adaptive practice tests.

The editorial difficulty is the stable item parameter until SAT Duel has
enough first-sitting completions to calibrate items empirically.
"""

import math
import re
from fractions import Fraction


DIFFICULTY_LOCATION = {1: -1.5, 2: -0.75, 3: 0.0, 4: 0.75, 5: 1.5}
THETA_GRID = tuple(-4.0 + index * 0.01 for index in range(801))
PRIOR_SD = 1.5
ROUTING_THRESHOLD = 0.0
SCORING_VERSION = 'fixed-irt-v1'
STUDENT_RESPONSE_PATTERN = re.compile(
    r'-?(?:(?:0|[1-9]\d*)(?:\.\d*)?|\.\d+|(?:0|[1-9]\d*)/(?:[1-9]\d*))'
)


def _numeric(value):
    text = str(value or '').strip().replace('−', '-')
    if not text:
        return None
    try:
        return Fraction(text)
    except (ValueError, ZeroDivisionError):
        return None


def student_response_is_valid(value):
    text = str(value or '').strip().replace('−', '-')
    limit = 6 if text.startswith('-') else 5
    return bool(text) and len(text) <= limit and STUDENT_RESPONSE_PATTERN.fullmatch(text) is not None


def _uses_repeating_decimal(value):
    denominator = value.denominator
    for factor in (2, 5):
        while denominator % factor == 0:
            denominator //= factor
    return denominator != 1


def _valid_rounded_entry(expected, submitted_text, submitted_number):
    if '.' not in submitted_text or not _uses_repeating_decimal(expected):
        return False
    limit = 6 if submitted_text.startswith('-') else 5
    if len(submitted_text) != limit:
        return False
    precision = len(submitted_text.rsplit('.', 1)[1])
    if precision < 1:
        return False

    scale = 10 ** precision
    quotient, remainder = divmod(abs(expected.numerator) * scale, expected.denominator)
    sign = -1 if expected < 0 else 1
    truncated = Fraction(sign * quotient, scale)
    rounded = Fraction(sign * (quotient + (2 * remainder >= expected.denominator)), scale)
    return submitted_number in {truncated, rounded}


def answer_is_correct(question, response):
    expected = str(question.get('answer', '')).strip()
    submitted = str(response or '').strip()
    if question.get('response_type') != 'student_produced':
        return bool(submitted) and submitted.upper() == expected.upper()

    if not student_response_is_valid(submitted):
        return False
    submitted_number = _numeric(submitted)
    if submitted_number is None:
        return False
    # Semicolons represent mathematically distinct credited answers, not merely alternate notation.
    accepted = [item.strip() for item in expected.split(';') if item.strip()]
    for item in accepted:
        expected_number = _numeric(item)
        if expected_number is not None and (
            expected_number == submitted_number
            or _valid_rounded_entry(expected_number, submitted, submitted_number)
        ):
            return True
    return False


def _probability(theta, question):
    difficulty = int(question.get('difficulty', 3))
    location = DIFFICULTY_LOCATION.get(difficulty, 0.0)
    guessing = 0.0 if question.get('response_type') == 'student_produced' else 0.25
    logistic = 1.0 / (1.0 + math.exp(-(theta - location)))
    return guessing + (1.0 - guessing) * logistic


def estimate_ability(question_responses):
    """Return a Bayesian EAP theta and central 68% credible interval."""
    scored = list(question_responses)
    log_weights = []
    for theta in THETA_GRID:
        log_likelihood = -0.5 * (theta / PRIOR_SD) ** 2
        for question, response in scored:
            probability = min(max(_probability(theta, question), 1e-9), 1 - 1e-9)
            likelihood = probability if answer_is_correct(question, response) else 1.0 - probability
            log_likelihood += math.log(max(likelihood, 1e-12))
        log_weights.append(log_likelihood)

    peak = max(log_weights)
    weights = [math.exp(value - peak) for value in log_weights]
    total = sum(weights)
    weights = [weight / total for weight in weights]
    mean = sum(theta * weight for theta, weight in zip(THETA_GRID, weights))

    def quantile(target):
        cumulative = 0.0
        for theta, weight in zip(THETA_GRID, weights):
            cumulative += weight
            if cumulative >= target:
                return theta
        return THETA_GRID[-1]

    return {
        'theta': round(mean, 4),
        'theta_low': round(quantile(0.16), 4),
        'theta_high': round(quantile(0.84), 4),
        'correct': sum(answer_is_correct(question, response) for question, response in scored),
        'total': len(scored),
    }


def theta_to_section_score(theta):
    raw = min(800, max(200, 500 + 100 * theta))
    return int(math.floor(raw / 10.0 + 0.5) * 10)


def score_section(question_responses):
    estimate = estimate_ability(question_responses)
    return {
        **estimate,
        'score': theta_to_section_score(estimate['theta']),
        'score_low': theta_to_section_score(estimate['theta_low']),
        'score_high': theta_to_section_score(estimate['theta_high']),
    }


def select_second_module(question_responses):
    """Route estimates at zero or above to the harder second module."""
    return 'C' if estimate_ability(question_responses)['theta'] >= ROUTING_THRESHOLD else 'B'
