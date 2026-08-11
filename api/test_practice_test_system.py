from unittest import mock

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.urls import reverse
from rest_framework.test import APITestCase

from api.models import PracticeTest, PracticeTestAttempt, PracticeTestModule
from api.practice_test_scoring import answer_is_correct, estimate_ability, select_second_module
from api.views.practice_test_views import _attempt_queryset


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


def create_subject_test(user, subject, suffix):
    modules = create_modules(user, suffix)
    return PracticeTest.objects.create(
        name=f'{subject.title()} Practice Test {suffix}',
        test_type=subject,
        created_by=user,
        **{field: module for field, module in modules.items() if field.startswith(subject)},
    )


class FixedScoringTests(APITestCase):
    def test_student_responses_follow_bluebook_entry_rules(self):
        produced = {**question(), 'response_type': 'student_produced', 'answer': '2/3'}
        for accepted in ('2/3', '4/6', '.6666', '.6667', '0.666', '0.667'):
            self.assertTrue(answer_is_correct(produced, accepted), accepted)
        for rejected in ('.66', '.67', '0.66', '0.67', '66%', '0,667'):
            self.assertFalse(answer_is_correct(produced, rejected), rejected)

        produced['answer'] = '-1/3'
        for accepted in ('-1/3', '-.3333', '-0.333'):
            self.assertTrue(answer_is_correct(produced, accepted), accepted)
        for rejected in ('-.33', '-0.33'):
            self.assertFalse(answer_is_correct(produced, rejected), rejected)

        produced['answer'] = '3.5'
        for accepted in ('3.5', '3.50', '7/2'):
            self.assertTrue(answer_is_correct(produced, accepted), accepted)
        for rejected in ('31/2', '3 1/2'):
            self.assertFalse(answer_is_correct(produced, rejected), rejected)

    def test_student_response_can_have_multiple_distinct_answers(self):
        produced = {**question(), 'response_type': 'student_produced', 'answer': '2;3'}
        self.assertTrue(answer_is_correct(produced, '2'))
        self.assertTrue(answer_is_correct(produced, '3.0'))
        self.assertFalse(answer_is_correct(produced, '4'))

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

    def test_every_item_counts_even_with_a_legacy_pretest_flag(self):
        first = question()
        legacy_flagged = question(pretest=True, order=2)
        result = estimate_ability([(first, 'A'), (legacy_flagged, 'B')])
        self.assertEqual(result['correct'], 1)
        self.assertEqual(result['total'], 2)


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

    def test_admin_can_create_an_english_only_test(self):
        modules = create_modules(self.admin, suffix='english-only')
        response = self.client.post(reverse('admin_practice_tests'), {
            'name': 'English Form',
            'test_type': 'english',
            **{field: module.id for field, module in modules.items() if field.startswith('english')},
        }, format='json')

        self.assertEqual(response.status_code, 201, response.data)
        test = PracticeTest.objects.get(name='English Form')
        self.assertEqual(test.test_type, PracticeTest.TYPE_ENGLISH)
        self.assertIsNone(test.math_a)
        self.assertEqual(response.data['test']['maximum_score'], 800)
        self.assertEqual(response.data['test']['question_count'], 2)


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
        break_state = self.finish(attempt_id, 'A')
        self.assertTrue(break_state.data['break'])
        resumed = self.client.post(
            reverse('adaptive_test_resume_after_break', args=[attempt_id]), {}, format='json',
        )
        self.assertEqual(resumed.data['phase'], 'math_a')
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
                'annotations': {
                    '1': {
                        'marks': [{
                            'id': 'mark-1', 'field': 'passage', 'start': 0, 'end': 8,
                            'color': 'yellow', 'underline': 'solid',
                        }],
                        'crossed_out': ['B', 'D'],
                    },
                },
            },
            format='json',
        )
        self.assertEqual(saved.data['answers'], {'1': 'C'})
        self.assertEqual(saved.data['remaining_seconds'], 777)
        self.assertEqual(saved.data['annotations']['1']['marks'][0]['underline'], 'solid')
        self.assertEqual(saved.data['annotations']['1']['crossed_out'], ['B', 'D'])

        resumed = self.start()
        self.assertEqual(resumed.data['attempt_id'], attempt_id)
        self.assertEqual(resumed.data['review_questions'], [1])
        self.assertEqual(resumed.data['annotations'], saved.data['annotations'])

        restarted = self.client.post(reverse('adaptive_test_restart', args=[attempt_id]), {}, format='json')
        self.assertNotEqual(restarted.data['attempt_id'], attempt_id)
        self.assertFalse(PracticeTestAttempt.objects.filter(id=attempt_id).exists())
        self.assertEqual(restarted.data['answers'], {})
        self.assertEqual(restarted.data['annotations'], {})

    def test_annotations_are_validated_before_storage(self):
        start = self.start()
        response = self.client.patch(
            reverse('adaptive_test_progress', args=[start.data['attempt_id']]),
            {
                'phase': 'english_a',
                'annotations': {
                    '1': {
                        'marks': [
                            {'id': 'ok', 'field': 'prompt', 'start': 0, 'end': 4, 'color': 'pink', 'underline': 'dotted'},
                            {'id': 'bad-color', 'field': 'prompt', 'start': 0, 'end': 4, 'color': 'green'},
                            {'id': 'bad-range', 'field': 'passage', 'start': 9, 'end': 2, 'color': 'yellow'},
                        ],
                        'crossed_out': ['A', 'Z', 3],
                    },
                    '99': {'marks': [], 'crossed_out': ['B']},
                },
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['annotations'], {
            '1': {
                'marks': [{'id': 'ok', 'field': 'prompt', 'start': 0, 'end': 4, 'color': 'pink', 'underline': 'dotted'}],
                'crossed_out': ['A'],
            },
        })

    def test_full_test_stops_for_a_persistent_break_between_sections(self):
        start = self.start()
        attempt_id = start.data['attempt_id']
        self.finish(attempt_id)
        break_state = self.finish(attempt_id)

        self.assertTrue(break_state.data['break'])
        self.assertLessEqual(break_state.data['break_remaining_seconds'], 600)
        self.assertTrue(self.start().data['break'])

        resumed = self.client.post(
            reverse('adaptive_test_resume_after_break', args=[attempt_id]), {}, format='json',
        )
        self.assertEqual(resumed.status_code, 200)
        self.assertEqual(resumed.data['phase'], 'math_a')
        self.assertEqual(resumed.data['section_number'], 2)

    def test_blank_modules_submit_and_count_every_question_as_incorrect(self):
        test = create_subject_test(self.user, 'english', 'blank')
        start = self.client.post(reverse('adaptive_test_start', args=[test.id]), {}, format='json')
        first = self.client.post(
            reverse('adaptive_test_finish_module', args=[start.data['attempt_id']]),
            {
                'answers': {'1': None},
                'remaining_seconds': 100,
                'current_question': 2,
            },
            format='json',
        )

        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(first.data['phase'], 'english_b')
        self.assertEqual(first.data['subject'], 'english')
        final = self.client.post(
            reverse('adaptive_test_finish_module', args=[start.data['attempt_id']]),
            {'answers': {}, 'remaining_seconds': 100, 'current_question': 2},
            format='json',
        )
        self.assertTrue(final.data['completed'])
        attempt = PracticeTestAttempt.objects.get(id=start.data['attempt_id'])
        self.assertEqual(attempt.answers['english_a'], {})
        self.assertEqual(attempt.score_details['correct'], 0)
        self.assertEqual(attempt.score_details['total'], 2)

    def test_locking_an_attempt_leaves_the_nullable_module_joins_unlocked(self):
        """PostgreSQL rejects FOR UPDATE against the nullable side of an outer join.

        Every module slot is nullable, so select_related() reaches the modules
        through LEFT OUTER JOINs and a bare FOR UPDATE makes finish-module and
        restart fail in production. SQLite drops the clause entirely, so this
        has to inspect the SQL a locking backend would receive.
        """
        query = _attempt_queryset(self.user, 1, lock=True)
        with mock.patch.object(connection.features, 'has_select_for_update', True), \
                mock.patch.object(connection.features, 'has_select_for_update_of', True), \
                transaction.atomic():
            sql, _ = query.query.get_compiler(using='default').as_sql()

        self.assertIn('LEFT OUTER JOIN', sql)
        self.assertEqual(sql[sql.index('FOR UPDATE'):], 'FOR UPDATE OF "api_practicetestattempt"')

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

    def test_math_only_test_starts_with_math_and_scores_out_of_800(self):
        test = create_subject_test(self.user, 'math', 'math-only')
        start = self.client.post(reverse('adaptive_test_start', args=[test.id]), {}, format='json')
        self.assertEqual(start.data['phase'], 'math_a')

        second = self.finish(start.data['attempt_id'], 'A')
        self.assertEqual(second.data['phase'], 'math_c')
        final = self.finish(start.data['attempt_id'], 'A')
        self.assertTrue(final.data['completed'])

        attempt = PracticeTestAttempt.objects.get(id=start.data['attempt_id'])
        self.assertIsNone(attempt.reading_writing_score)
        self.assertEqual(attempt.total_score, attempt.math_score)
        self.assertEqual(attempt.score_details['total'], 2)
        result = self.client.get(reverse('adaptive_test_result', args=[attempt.id]))
        self.assertEqual(result.data['test_type'], 'math')
        self.assertEqual(result.data['maximum_score'], 800)
        self.assertEqual(len(result.data['questions']), 2)
        self.assertEqual(result.data['selected_routes'], {'math': 'C'})
        listing = self.client.get(reverse('adaptive_practice_tests'))
        test_summary = next(item for item in listing.data['tests'] if item['id'] == test.id)
        self.assertEqual(test_summary['question_count'], 2)
        self.assertEqual(test_summary['maximum_score'], 800)
        self.assertEqual(listing.data['history']['results'][0]['test_type'], 'math')
        self.assertNotIn('average_score', listing.data['history'])

    def test_english_only_test_completes_after_its_second_module(self):
        test = create_subject_test(self.user, 'english', 'english-only')
        start = self.client.post(reverse('adaptive_test_start', args=[test.id]), {}, format='json')
        second = self.finish(start.data['attempt_id'], 'A')
        self.assertEqual(second.data['phase'], 'english_c')
        final = self.finish(start.data['attempt_id'], 'A')
        self.assertTrue(final.data['completed'])

        attempt = PracticeTestAttempt.objects.get(id=start.data['attempt_id'])
        self.assertIsNone(attempt.math_score)
        self.assertEqual(attempt.total_score, attempt.reading_writing_score)
