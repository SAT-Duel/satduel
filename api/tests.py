from unittest.mock import patch

from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APITestCase

from allauth.account.models import EmailAddress
from api.models import Profile, Ranking


class PasswordLoginTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='alice', email='alice@example.com', password='Secret123',
        )
        Profile.objects.create(user=self.user)

    def test_login_requires_verified_email(self):
        resp = self.client.post(reverse('auth_login'), {
            'username': 'alice', 'password': 'Secret123',
        }, format='json')
        self.assertEqual(resp.status_code, 401)
        self.assertIn('verify', resp.data['error'].lower())

    def test_login_success_returns_tokens_and_user(self):
        EmailAddress.objects.create(
            user=self.user, email=self.user.email, verified=True, primary=True,
        )
        resp = self.client.post(reverse('auth_login'), {
            'username': 'alice', 'password': 'Secret123',
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('access', resp.data)
        self.assertIn('refresh', resp.data)
        self.assertEqual(resp.data['user']['username'], 'alice')
        self.assertTrue(resp.data['user']['is_first_login'])

    def test_login_by_email(self):
        EmailAddress.objects.create(
            user=self.user, email=self.user.email, verified=True, primary=True,
        )
        resp = self.client.post(reverse('auth_login'), {
            'username': 'alice@example.com', 'password': 'Secret123',
        }, format='json')
        self.assertEqual(resp.status_code, 200)

    def test_login_bad_password(self):
        EmailAddress.objects.create(
            user=self.user, email=self.user.email, verified=True, primary=True,
        )
        resp = self.client.post(reverse('auth_login'), {
            'username': 'alice', 'password': 'wrong',
        }, format='json')
        self.assertEqual(resp.status_code, 401)


def _fake_idinfo(email='bob@example.com', verified=True, sub='google-uid-123'):
    return {
        'email': email,
        'email_verified': verified,
        'given_name': 'Bob',
        'family_name': 'Jones',
        'sub': sub,
    }


class GoogleLoginTests(APITestCase):
    @patch('api.views.auth_views.google_id_token.verify_oauth2_token')
    def test_new_google_user_is_created(self, mock_verify):
        mock_verify.return_value = _fake_idinfo()
        resp = self.client.post(reverse('auth_google'), {
            'credential': 'fake-token',
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data['user']['is_new_user'])
        user = User.objects.get(email='bob@example.com')
        self.assertTrue(Profile.objects.filter(user=user).exists())
        self.assertTrue(EmailAddress.objects.filter(user=user, verified=True).exists())
        self.assertFalse(user.has_usable_password())

    @patch('api.views.auth_views.google_id_token.verify_oauth2_token')
    def test_google_records_social_account(self, mock_verify):
        from allauth.socialaccount.models import SocialAccount
        mock_verify.return_value = _fake_idinfo(sub='uid-abc')
        self.client.post(reverse('auth_google'), {'credential': 'fake'}, format='json')
        sa = SocialAccount.objects.get(provider='google', uid='uid-abc')
        self.assertEqual(sa.user.email, 'bob@example.com')

    @patch('api.views.auth_views.google_id_token.verify_oauth2_token')
    def test_google_repeat_login_no_duplicate_social(self, mock_verify):
        from allauth.socialaccount.models import SocialAccount
        mock_verify.return_value = _fake_idinfo(sub='uid-xyz')
        self.client.post(reverse('auth_google'), {'credential': 'fake'}, format='json')
        self.client.post(reverse('auth_google'), {'credential': 'fake'}, format='json')
        self.assertEqual(SocialAccount.objects.filter(uid='uid-xyz').count(), 1)

    @patch('api.views.auth_views.google_id_token.verify_oauth2_token')
    def test_google_links_to_existing_verified_account(self, mock_verify):
        existing = User.objects.create_user(
            username='bob', email='bob@example.com', password='Secret123',
        )
        Profile.objects.create(user=existing)
        EmailAddress.objects.create(
            user=existing, email='bob@example.com', verified=True, primary=True,
        )
        mock_verify.return_value = _fake_idinfo()
        resp = self.client.post(reverse('auth_google'), {
            'credential': 'fake-token',
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data['user']['is_new_user'])
        self.assertEqual(resp.data['user']['id'], existing.id)
        self.assertEqual(User.objects.filter(email='bob@example.com').count(), 1)

    @patch('api.views.auth_views.google_id_token.verify_oauth2_token')
    def test_google_rejects_unverified_email(self, mock_verify):
        mock_verify.return_value = _fake_idinfo(verified=False)
        resp = self.client.post(reverse('auth_google'), {
            'credential': 'fake-token',
        }, format='json')
        self.assertEqual(resp.status_code, 401)

    @patch('api.views.auth_views.google_id_token.verify_oauth2_token')
    def test_google_invalid_token(self, mock_verify):
        mock_verify.side_effect = ValueError('bad token')
        resp = self.client.post(reverse('auth_google'), {
            'credential': 'fake-token',
        }, format='json')
        self.assertEqual(resp.status_code, 401)

    def test_google_missing_credential(self):
        resp = self.client.post(reverse('auth_google'), {}, format='json')
        self.assertEqual(resp.status_code, 400)

    @patch('api.views.auth_views.google_id_token.verify_oauth2_token')
    def test_google_duplicate_emails_picks_verified(self, mock_verify):
        # Two legacy accounts share an email; only one is verified.
        u1 = User.objects.create_user(username='dup1', email='dup@example.com')
        u2 = User.objects.create_user(username='dup2', email='dup@example.com')
        Profile.objects.create(user=u1)
        Profile.objects.create(user=u2)
        EmailAddress.objects.create(user=u2, email='dup@example.com', verified=True, primary=True)
        mock_verify.return_value = _fake_idinfo(email='dup@example.com')
        resp = self.client.post(reverse('auth_google'), {
            'credential': 'fake-token',
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['user']['id'], u2.id)


class CompleteProfileTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='carol', email='c@example.com')
        Profile.objects.create(user=self.user)
        EmailAddress.objects.create(user=self.user, email='c@example.com', verified=True, primary=True)
        self.client.force_authenticate(user=self.user)

    def test_set_grade(self):
        resp = self.client.post(reverse('auth_complete_profile'), {'grade': '10'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.grade, '10')

    def test_invalid_grade_rejected(self):
        resp = self.client.post(reverse('auth_complete_profile'), {'grade': '99'}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_requires_auth(self):
        self.client.force_authenticate(user=None)
        resp = self.client.post(reverse('auth_complete_profile'), {'grade': '10'}, format='json')
        self.assertEqual(resp.status_code, 401)


class RankingUpdateTests(APITestCase):
    def test_rankings_ordered_by_elo(self):
        users = []
        for i, elo in enumerate([1200, 1800, 1500]):
            u = User.objects.create_user(username=f'u{i}', email=f'u{i}@e.com')
            Profile.objects.create(user=u, elo_rating=elo)
            users.append(u)
        Ranking.update_rankings()
        ranks = {r.user.username: r.rank for r in Ranking.objects.all()}
        # u1 has highest elo (1800) -> rank 1
        self.assertEqual(ranks['u1'], 1)
        self.assertEqual(ranks['u2'], 2)  # 1500
        self.assertEqual(ranks['u0'], 3)  # 1200
        # ranks are unique and contiguous
        self.assertEqual(sorted(ranks.values()), [1, 2, 3])

    def test_rankings_idempotent(self):
        u = User.objects.create_user(username='solo', email='s@e.com')
        Profile.objects.create(user=u, elo_rating=1500)
        Ranking.update_rankings()
        Ranking.update_rankings()  # second run must not blow up on unique constraint
        self.assertEqual(Ranking.objects.get(user=u).rank, 1)


class CleanupUnverifiedUsersTests(APITestCase):
    def setUp(self):
        from django.utils import timezone
        from datetime import timedelta
        old = timezone.now() - timedelta(days=45)

        # stale: unverified, never logged in, old -> should be deleted
        self.stale = User.objects.create_user(username='stale', email='stale@e.com')
        User.objects.filter(pk=self.stale.pk).update(date_joined=old)

        # recent unverified -> kept
        self.recent = User.objects.create_user(username='recent', email='recent@e.com')

        # verified old -> kept
        self.verified = User.objects.create_user(username='verified', email='v@e.com')
        User.objects.filter(pk=self.verified.pk).update(date_joined=old)
        EmailAddress.objects.create(user=self.verified, email='v@e.com', verified=True, primary=True)

        # staff, unverified, old -> kept (never touch staff)
        self.staff = User.objects.create_user(username='staff', email='s@e.com', is_staff=True)
        User.objects.filter(pk=self.staff.pk).update(date_joined=old)

    def test_dry_run_deletes_nothing(self):
        from django.core.management import call_command
        call_command('cleanup_unverified_users')
        self.assertTrue(User.objects.filter(username='stale').exists())

    def test_delete_only_removes_stale(self):
        from django.core.management import call_command
        call_command('cleanup_unverified_users', '--delete')
        self.assertFalse(User.objects.filter(username='stale').exists())
        self.assertTrue(User.objects.filter(username='recent').exists())
        self.assertTrue(User.objects.filter(username='verified').exists())
        self.assertTrue(User.objects.filter(username='staff').exists())


class PracticeTierTests(APITestCase):
    """Free-vs-premium quota, topic gating, and the revised Elo rules."""

    def setUp(self):
        from api.models import Question
        self.user = User.objects.create_user(username='practicer', email='p@e.com')
        self.profile = Profile.objects.create(user=self.user)
        self.client.force_authenticate(user=self.user)
        self.questions = [
            Question.objects.create(
                question=f'Q{i}?', choice_a='a', choice_b='b', choice_c='c', choice_d='d',
                answer='B', difficulty=3, question_type='Transitions',
            )
            for i in range(5)
        ]

    def _answer(self, q, choice='b', mode='practice'):
        return self.client.post('/api/check_answer/', {
            'question_id': q.id, 'selected_choice': choice, 'mode': mode,
        }, format='json')

    def test_next_question_returns_question_and_quota(self):
        resp = self.client.get('/api/practice/next/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('question', resp.data)
        self.assertEqual(resp.data['quota']['limit'], 25)
        self.assertFalse(resp.data['quota']['is_premium'])

    def test_topic_selection_requires_premium(self):
        resp = self.client.get('/api/practice/next/', {'type': 'Transitions'})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.data['error'], 'premium_required')

    def test_premium_can_select_topic(self):
        self.profile.is_premium = True
        self.profile.save()
        resp = self.client.get('/api/practice/next/', {'type': 'Transitions'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['question']['question_type'], 'Transitions')
        self.assertIsNone(resp.data['quota']['limit'])

    def test_expired_premium_is_free_tier(self):
        from django.utils import timezone
        from datetime import timedelta
        self.profile.is_premium = True
        self.profile.premium_until = timezone.now() - timedelta(days=1)
        self.profile.save()
        resp = self.client.get('/api/practice/next/', {'type': 'Transitions'})
        self.assertEqual(resp.status_code, 403)

    def test_daily_limit_blocks_after_quota(self):
        from api.models import PracticeAttempt
        # Simulate having used the full quota today
        for i in range(25):
            PracticeAttempt.objects.create(
                user=self.user, question=self.questions[i % 5], correct=True,
            )
        next_resp = self.client.get('/api/practice/next/')
        self.assertEqual(next_resp.status_code, 429)
        answer_resp = self._answer(self.questions[0])
        self.assertEqual(answer_resp.status_code, 429)
        self.assertEqual(answer_resp.data['error'], 'daily_limit')

    def test_practice_answer_records_attempt_and_updates_elo(self):
        before = self.profile.sp_elo_rating
        resp = self._answer(self.questions[0], 'b')  # correct
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data['rated'])
        self.assertEqual(resp.data['quota']['used'], 1)
        self.profile.refresh_from_db()
        self.assertGreater(self.profile.sp_elo_rating, before)

    def test_repeat_attempt_does_not_move_elo(self):
        self._answer(self.questions[0], 'b')
        self.profile.refresh_from_db()
        rating_after_first = self.profile.sp_elo_rating
        resp = self._answer(self.questions[0], 'b')
        self.assertFalse(resp.data['rated'])
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.sp_elo_rating, rating_after_first)

    def test_non_practice_mode_does_not_move_elo_or_quota(self):
        before = self.profile.sp_elo_rating
        resp = self._answer(self.questions[0], 'b', mode='')
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('rated', resp.data)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.sp_elo_rating, before)
        from api.models import PracticeAttempt
        self.assertEqual(PracticeAttempt.objects.count(), 0)

    def test_wrong_answer_lowers_rating(self):
        before = self.profile.sp_elo_rating
        self._answer(self.questions[0], 'a')  # incorrect
        self.profile.refresh_from_db()
        self.assertLess(self.profile.sp_elo_rating, before)

    def test_next_prefers_unattempted_questions(self):
        from api.models import PracticeAttempt
        for q in self.questions[:4]:
            PracticeAttempt.objects.create(user=self.user, question=q, correct=True)
        resp = self.client.get('/api/practice/next/')
        self.assertEqual(resp.data['question']['id'], self.questions[4].id)


class TournamentHistoryTests(APITestCase):
    def setUp(self):
        from api.models import Tournament, TournamentParticipation, Question
        from django.utils import timezone
        self.user = User.objects.create_user(username='hist', email='h@e.com')
        Profile.objects.create(user=self.user)
        self.client.force_authenticate(user=self.user)
        q = Question.objects.create(
            question='Q?', choice_a='a', choice_b='b', choice_c='c', choice_d='d',
            answer='A', difficulty=2, question_type='Transitions',
        )
        for i in range(15):
            t = Tournament.objects.create(
                name=f'T{i}', description='d', start_time=timezone.now(),
            )
            t.questions.add(q)
            TournamentParticipation.objects.create(
                user=self.user, tournament=t, status='Completed',
                start_time=timezone.now(), score=i,
            )

    def test_history_is_paginated(self):
        resp = self.client.get('/api/tournaments/get_history/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 10)  # default page size
        self.assertEqual(resp['X-Total-Count'], '15')
        page2 = self.client.get('/api/tournaments/get_history/', {'page': 2})
        self.assertEqual(len(page2.data), 5)

    def test_history_shape_is_backward_compatible(self):
        resp = self.client.get('/api/tournaments/get_history/')
        entry = resp.data[0]
        self.assertIn('tournament', entry)
        self.assertIn('participantNumber', entry['tournament'])
        self.assertIn('questionNumber', entry['tournament'])
        self.assertEqual(entry['tournament']['participantNumber'], 1)

    def test_history_query_count_is_constant(self):
        from django.test.utils import CaptureQueriesContext
        from django.db import connection
        with CaptureQueriesContext(connection) as ctx:
            self.client.get('/api/tournaments/get_history/')
        # Must not grow with the number of participations (was 2N+1).
        self.assertLess(len(ctx), 10)


class QuestionAnswerLeakTests(APITestCase):
    def setUp(self):
        from api.models import Question
        self.q = Question.objects.create(
            question='Q?', choice_a='a', choice_b='b', choice_c='c', choice_d='d',
            answer='B', difficulty=3, question_type='Transitions', explanation='because',
        )

    def test_public_list_has_no_answer(self):
        resp = self.client.get('/api/questions/?num=1')
        self.assertEqual(resp.status_code, 200)
        if resp.data:
            self.assertNotIn('answer', resp.data[0])
            self.assertNotIn('explanation', resp.data[0])


class GetAnswerLockdownTests(APITestCase):
    def setUp(self):
        from api.models import Question
        self.q = Question.objects.create(
            question='Q?', choice_a='a', choice_b='b', choice_c='c', choice_d='d',
            answer='B', difficulty=3, question_type='Transitions', explanation='why',
        )
        self.user = User.objects.create_user(username='dave', email='d@e.com')
        Profile.objects.create(user=self.user)

    def test_anonymous_denied(self):
        resp = self.client.post('/api/get_answer/', {'question_id': self.q.id}, format='json')
        self.assertEqual(resp.status_code, 401)

    def test_authenticated_allowed(self):
        self.client.force_authenticate(user=self.user)
        resp = self.client.post('/api/get_answer/', {'question_id': self.q.id}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['answer_choice'], 'B')

    def test_blocked_during_active_tournament(self):
        from api.models import Tournament, TournamentParticipation
        from django.utils import timezone
        t = Tournament.objects.create(
            name='T', description='d', start_time=timezone.now(),
        )
        t.questions.add(self.q)
        TournamentParticipation.objects.create(user=self.user, tournament=t, status='Active')
        self.client.force_authenticate(user=self.user)
        resp = self.client.post('/api/get_answer/', {'question_id': self.q.id}, format='json')
        self.assertEqual(resp.status_code, 403)

    def test_allowed_after_tournament_finished(self):
        from api.models import Tournament, TournamentParticipation
        from django.utils import timezone
        t = Tournament.objects.create(
            name='T', description='d', start_time=timezone.now(),
        )
        t.questions.add(self.q)
        TournamentParticipation.objects.create(user=self.user, tournament=t, status='Completed')
        self.client.force_authenticate(user=self.user)
        resp = self.client.post('/api/get_answer/', {'question_id': self.q.id}, format='json')
        self.assertEqual(resp.status_code, 200)
