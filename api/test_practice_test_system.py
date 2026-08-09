from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.urls import reverse
from rest_framework.test import APITestCase

from api.models import PracticeTest, PracticeTestAttempt, PracticeTestModule
from api.practice_test_scoring import estimate_ability, select_second_module


def question(answer='A', difficulty=3, pretest=False, order=1):
    return {
        'order': order,
        'response_type': 'multiple_choice',
        'question': f'Question {order}',
        'choice_a': 'A choice',
        'choice_b': 'B choice',
        'choice_c': 'C choice',
        'choice_d': 'D choice',
        'answer': answer,
        'difficulty': difficulty,
        'question_type': 'Test skill',
        'explanation': 'Worked explanation',
        'is_pretest': pretest,
    }


def create_modules(user, suffix='1'):
    modules = {}
    for subject in ('english', 'math'):
        for route in ('A', 'B', 'C'):
            modules[f'{subject}_{route.lower()}'] = PracticeTestModule.objects.create(
                name=f'{subject}-{route}-{suffix}',
                subject=subject,
                route=route,
                questions=[question()],
                created_by=user,
            )
    return modules


def create_test(user, suffix='1'):
    return PracticeTest.objects.create(
        name=f'Practice Test {suffix}',
        created_by=user,
        **create_modules(user, suffix),
    )


class FixedScoringTests(APITestCase):
    def test_difficulty_changes_evidence_in_the_expected_direction(self):
        easy = question(difficulty=1)
        hard = question(difficulty=5)
        hard_correct = estimate_ability([(hard, 'A')])
        easy_correct = estimate_ability([(easy, 'A')])
        easy_wrong = estimate_ability([(easy, 'B')])
        hard_wrong = estimate_ability([(hard, 'B')])
        self.assertGreater(hard_correct['theta'], easy_correct['theta'])
        self.assertLess(easy_wrong['theta'], hard_wrong['theta'])

    def test_zero_boundary_routes_to_harder_module(self):
        correct = [(question(), 'A')]
        incorrect = [(question(), 'B')]
        self.assertEqual(select_second_module(correct), 'C')
        self.assertEqual(select_second_module(incorrect), 'B')

    def test_pretest_items_do_not_affect_score_or_counts(self):
        operational = question()
        pretest = question(pretest=True, order=2)
        without_pretest = estimate_ability([(operational, 'A')])
        with_pretest = estimate_ability([(operational, 'A'), (pretest, 'B')])
        self.assertEqual(with_pretest, without_pretest)


class PracticeTestCreatorTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin', 'admin@example.com', 'password')
        self.client.force_authenticate(self.admin)

    def test_modules_cannot_be_assigned_to_two_tests(self):
        modules = create_modules(self.admin)
        payload = {'name': 'Form One', **{field: module.id for field, module in modules.items()}}
        response = self.client.post(reverse('admin_practice_tests'), payload, format='json')
        self.assertEqual(response.status_code, 201)

        response = self.client.post(
            reverse('admin_practice_tests'),
            {**payload, 'name': 'Form Two'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(PracticeTest.objects.count(), 1)

    def test_model_rejects_a_module_in_the_wrong_slot(self):
        modules = create_modules(self.admin, suffix='wrong-slot')
        modules['math_a'] = modules['english_a']
        with self.assertRaises(ValidationError):
            PracticeTest.objects.create(name='Invalid form', created_by=self.admin, **modules)


class PracticeTestAttemptTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user('student', password='password')
        self.test = create_test(self.user)
        self.client.force_authenticate(self.user)

    def start(self):
        return self.client.post(reverse('adaptive_test_start', args=[self.test.id]), {}, format='json')

    def finish(self, attempt_id, answer='A'):
        return self.client.post(
            reverse('adaptive_test_finish_module', args=[attempt_id]),
            {'answers': {'1': answer}, 'remaining_seconds': 100, 'current_question': 2},
            format='json',
        )

    def complete_sitting(self):
        start = self.start()
        attempt_id = start.data['attempt_id']
        first = self.finish(attempt_id, 'A')
        self.assertEqual(first.data['phase'], 'english_c')
        self.finish(attempt_id, 'A')
        third = self.finish(attempt_id, 'B')
        self.assertEqual(third.data['phase'], 'math_b')
        final = self.finish(attempt_id, 'A')
        self.assertTrue(final.data['completed'])
        return PracticeTestAttempt.objects.get(id=attempt_id)

    def test_progress_can_be_saved_resumed_and_restarted(self):
        start = self.start()
        attempt_id = start.data['attempt_id']
        saved = self.client.patch(
            reverse('adaptive_test_progress', args=[attempt_id]),
            {
                'answers': {'1': 'C'},
                'remaining_seconds': 777,
                'current_question': 2,
                'review_questions': [1],
            },
            format='json',
        )
        self.assertEqual(saved.data['answers'], {'1': 'C'})
        self.assertEqual(saved.data['remaining_seconds'], 777)

        resumed = self.start()
        self.assertEqual(resumed.data['attempt_id'], attempt_id)
        self.assertEqual(resumed.data['review_questions'], [1])

        restarted = self.client.post(reverse('adaptive_test_restart', args=[attempt_id]), {}, format='json')
        self.assertNotEqual(restarted.data['attempt_id'], attempt_id)
        self.assertFalse(PracticeTestAttempt.objects.filter(id=attempt_id).exists())
        self.assertEqual(restarted.data['answers'], {})

    def test_only_first_completed_sitting_contributes_to_calibration(self):
        first = self.complete_sitting()
        self.assertTrue(first.contributes_to_calibration)
        self.assertEqual(first.score_details['total'], 4)

        second = self.complete_sitting()
        self.assertFalse(second.contributes_to_calibration)
        self.assertEqual(
            PracticeTestAttempt.objects.filter(
                user=self.user,
                practice_test=self.test,
                contributes_to_calibration=True,
            ).count(),
            1,
        )

    def test_answer_keys_are_hidden_until_completion(self):
        state = self.start().data
        self.assertNotIn('answer', state['questions'][0])
        self.assertNotIn('difficulty', state['questions'][0])
        attempt = self.complete_sitting()
        result = self.client.get(reverse('adaptive_test_result', args=[attempt.id]))
        self.assertEqual(result.status_code, 200)
        self.assertIn('answer', result.data['questions'][0])
