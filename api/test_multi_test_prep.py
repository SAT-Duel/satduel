from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from api.models import (
    PracticeStats,
    Profile,
    Question,
    TestPrep,
    TestPrepUserStats,
    TestSection,
)


def question_data(**overrides):
    data = {
        'question': 'What follows?',
        'choice_a': 'A',
        'choice_b': 'B',
        'choice_c': 'C',
        'choice_d': 'D',
        'answer': 'A',
        'difficulty': 2,
        'question_type': 'Inferences',
    }
    data.update(overrides)
    return data


class MultiTestPrepSchemaTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='multi_test_student')
        self.profile = Profile.objects.create(user=self.user)

    def test_seeded_catalog_includes_expandable_sections(self):
        self.assertTrue(TestPrep.objects.get(code='sat').active)
        self.assertEqual(
            list(TestSection.objects.filter(test_prep_id='act').values_list('code', flat=True)),
            ['english', 'math', 'reading', 'science'],
        )
        self.assertTrue(TestSection.objects.filter(test_prep_id='gre', code='quantitative').exists())

    def test_same_subject_stats_are_isolated_by_test_prep(self):
        sat = PracticeStats.objects.create(
            user=self.user, test_prep_id='sat', subject='math', elo=1400,
        )
        act = PracticeStats.objects.create(
            user=self.user, test_prep_id='act', subject='math', elo=900,
        )

        self.assertNotEqual(sat.pk, act.pk)
        with self.assertRaises(IntegrityError), transaction.atomic():
            PracticeStats.objects.create(
                user=self.user, test_prep_id='act', subject='math', elo=1500,
            )

    def test_current_sat_question_list_never_leaks_act_questions(self):
        sat = Question.objects.create(**question_data(question='SAT question'))
        Question.objects.create(
            **question_data(
                question='ACT question', test_prep_id='act', subject='english',
                source=Question.SOURCE_OFFICIAL_QUESTION_BANK,
            )
        )

        response = self.client.get(reverse('list_questions'), {'type': 'Inferences'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual([row['id'] for row in response.data['questions']], [sat.id])

    def test_duel_elo_is_independent_and_sat_keeps_legacy_mirror(self):
        act = TestPrepUserStats.for_user(self.user, 'act')
        act.update_elo(1500, 1)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.elo_rating, 1500)
        self.assertGreater(act.duel_elo, 1500)

        sat = TestPrepUserStats.for_user(self.user, 'sat')
        sat.update_elo(1500, 1)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.elo_rating, sat.duel_elo)

    def test_legacy_sat_math_questions_are_classified_on_save(self):
        question = Question.objects.create(**question_data(
            question_type='Linear equations in one variable',
        ))
        self.assertEqual(question.test_prep_id, 'sat')
        self.assertEqual(question.subject, 'math')
