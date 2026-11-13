from datetime import timedelta

from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APITestCase

from api.models import (
    DuelChallenge, DuelChallengeAttempt, Profile, Question, Room, TestPrepUserStats, TrackedQuestion,
)


class DuelChallengeTests(APITestCase):
    """A finished duel becomes a link; friends play the same ten against the creator's score."""

    def setUp(self):
        self.creator = self._user('creator')
        self.rival = self._user('rival')
        self.friend = self._user('friend')
        self.questions = [
            Question.objects.create(
                question=f'Challenge Q{i}?', choice_a='a', choice_b='b', choice_c='c', choice_d='d',
                answer='B', difficulty=3, question_type='Transitions', explanation=f'Because {i}.',
            )
            for i in range(10)
        ]
        self.room = self._finished_room(creator_correct=7)

    def _user(self, username):
        user = User.objects.create_user(username=username, email=f'{username}@e.com')
        Profile.objects.create(user=user, elo_rating=1500)
        return user

    def _finished_room(self, creator_correct):
        room = Room.objects.create(user1=self.creator, user2=self.rival, status='Battling')
        tracked = list(TrackedQuestion.objects.filter(room=room, user=self.creator).order_by('id'))
        for index, entry in enumerate(tracked):
            entry.status = 'Correct' if index < creator_correct else 'Incorrect'
            entry.save(update_fields=['status'])
        TrackedQuestion.objects.filter(room=room, user=self.rival).update(status='Incorrect')
        room.user1_score = creator_correct
        room.status = 'Ended'
        room.save()
        return room

    def _create(self, user=None, room=None):
        self.client.force_authenticate(user=user or self.creator)
        return self.client.post('/api/challenges/create/', {'room_id': (room or self.room).id}, format='json')

    def _code(self):
        return self._create().data['code']

    def _start(self, code, user=None):
        self.client.force_authenticate(user=user or self.friend)
        return self.client.post(f'/api/challenges/{code}/start/', format='json')

    def _answer(self, code, question_id, choice, user=None):
        self.client.force_authenticate(user=user or self.friend)
        return self.client.post(
            f'/api/challenges/{code}/answer/',
            {'question_id': question_id, 'selected_choice': choice}, format='json',
        )

    def _play(self, code, user, correct):
        """Answer every question, getting the first `correct` of them right."""
        order = DuelChallenge.objects.get(code=code).question_ids
        self._start(code, user)
        last = None
        for index, question_id in enumerate(order):
            last = self._answer(code, question_id, 'b' if index < correct else 'a', user)
        return last

    # --- creating -----------------------------------------------------------

    def test_create_snapshots_the_creators_score_and_question_order(self):
        response = self._create()

        self.assertEqual(response.status_code, 201)
        challenge = DuelChallenge.objects.get(code=response.data['code'])
        tracked = TrackedQuestion.objects.filter(room=self.room, user=self.creator).order_by('id')
        self.assertEqual(challenge.question_ids, [entry.question_id for entry in tracked])
        self.assertEqual(challenge.creator_results, ['Correct'] * 7 + ['Incorrect'] * 3)
        self.assertEqual(challenge.creator_score, 7)
        self.assertEqual(response.data['creator_score'], 7)
        self.assertEqual(response.data['question_count'], 10)
        self.assertTrue(response.data['viewer']['is_creator'])

    def test_create_twice_returns_the_same_link(self):
        first = self._create()
        second = self._create()

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data['code'], second.data['code'])
        self.assertEqual(DuelChallenge.objects.count(), 1)

    def test_both_duelists_get_their_own_link_for_the_same_duel(self):
        mine = self._create(self.creator)
        theirs = self._create(self.rival)

        self.assertNotEqual(mine.data['code'], theirs.data['code'])
        self.assertEqual(theirs.data['creator_score'], 0)

    def test_create_requires_a_finished_duel(self):
        live = Room.objects.create(user1=self.creator, user2=self.rival, status='Battling')

        response = self._create(room=live)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(DuelChallenge.objects.count(), 0)

    def test_only_a_player_in_the_duel_can_challenge_with_it(self):
        response = self._create(user=self.friend)

        self.assertEqual(response.status_code, 404)

    def test_create_requires_login(self):
        self.client.force_authenticate(user=None)

        response = self.client.post('/api/challenges/create/', {'room_id': self.room.id}, format='json')

        self.assertEqual(response.status_code, 401)

    def test_sharing_again_after_expiry_reopens_the_same_link(self):
        code = self._code()
        DuelChallenge.objects.filter(code=code).update(expires_at=timezone.now() - timedelta(hours=1))

        response = self._create()

        self.assertEqual(response.data['code'], code)
        self.assertFalse(response.data['expired'])

    # --- the link, before playing --------------------------------------------

    def test_signed_out_visitor_sees_the_invite_but_no_per_question_results(self):
        code = self._code()
        self.client.force_authenticate(user=None)

        response = self.client.get(f'/api/challenges/{code}/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['creator']['username'], 'creator')
        self.assertEqual(response.data['creator_score'], 7)
        self.assertFalse(response.data['viewer']['authenticated'])
        self.assertEqual(response.data['viewer']['status'], 'none')
        self.assertNotIn('scoreboard', response.data)
        self.assertNotIn('email', response.data['creator'])

    def test_code_lookup_ignores_case(self):
        code = self._code()

        response = self.client.get(f'/api/challenges/{code.lower()}/')

        self.assertEqual(response.status_code, 200)

    def test_unknown_code_is_a_404(self):
        response = self.client.get('/api/challenges/NOPE2345/')

        self.assertEqual(response.status_code, 404)

    def test_creator_sees_the_scoreboard_straight_away(self):
        code = self._code()

        response = self.client.get(f'/api/challenges/{code}/')

        self.assertEqual(len(response.data['scoreboard']), 1)
        self.assertTrue(response.data['scoreboard'][0]['is_creator'])

    # --- playing --------------------------------------------------------------

    def test_start_hands_over_the_same_questions_without_answers(self):
        code = self._code()

        response = self._start(code)

        self.assertEqual(response.status_code, 200)
        challenge = DuelChallenge.objects.get(code=code)
        self.assertEqual([int(q['id']) for q in response.data['questions']], challenge.question_ids)
        for question in response.data['questions']:
            self.assertNotIn('answer', question)
            self.assertNotIn('explanation', question)
        self.assertEqual(set(response.data['results'].values()), {'Blank'})
        self.assertEqual(response.data['duration_seconds'], 300)

    def test_start_twice_resumes_the_same_run(self):
        code = self._code()
        first = self._start(code)
        question_id = DuelChallenge.objects.get(code=code).question_ids[0]
        self._answer(code, question_id, 'b')

        second = self._start(code)

        self.assertEqual(DuelChallengeAttempt.objects.count(), 1)
        self.assertEqual(first.data['ends_at'], second.data['ends_at'])
        self.assertEqual(second.data['results'][str(question_id)], 'Correct')

    def test_creator_cannot_play_their_own_challenge(self):
        code = self._code()

        response = self._start(code, self.creator)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(DuelChallengeAttempt.objects.count(), 0)

    def test_start_requires_login(self):
        code = self._code()
        self.client.force_authenticate(user=None)

        response = self.client.post(f'/api/challenges/{code}/start/', format='json')

        self.assertEqual(response.status_code, 401)

    def test_answers_are_graded_on_the_server(self):
        code = self._code()
        self._start(code)
        first, second = DuelChallenge.objects.get(code=code).question_ids[:2]

        right = self._answer(code, first, 'b')
        wrong = self._answer(code, second, 'a')

        self.assertEqual(right.data['result'], 'correct')
        self.assertEqual(wrong.data['result'], 'incorrect')
        self.assertFalse(wrong.data['finished'])

    def test_a_question_can_only_be_answered_once(self):
        code = self._code()
        self._start(code)
        question_id = DuelChallenge.objects.get(code=code).question_ids[0]
        self._answer(code, question_id, 'a')

        retry = self._answer(code, question_id, 'b')

        self.assertEqual(retry.status_code, 409)
        attempt = DuelChallengeAttempt.objects.get()
        self.assertFalse(attempt.answers[str(question_id)]['correct'])

    def test_a_question_from_outside_the_challenge_is_rejected(self):
        code = self._code()
        self._start(code)
        stray = Question.objects.create(
            question='Stray?', choice_a='a', choice_b='b', choice_c='c', choice_d='d',
            answer='B', difficulty=3, question_type='Transitions',
        )

        response = self._answer(code, stray.id, 'b')

        self.assertEqual(response.status_code, 400)

    def test_answering_without_starting_is_a_404(self):
        code = self._code()
        question_id = DuelChallenge.objects.get(code=code).question_ids[0]

        response = self._answer(code, question_id, 'b')

        self.assertEqual(response.status_code, 404)

    # --- finishing ------------------------------------------------------------

    def test_last_answer_finishes_the_run_and_opens_the_scoreboard(self):
        code = self._code()

        last = self._play(code, self.friend, correct=8)

        self.assertTrue(last.data['finished'])
        detail = self.client.get(f'/api/challenges/{code}/')
        self.assertEqual(detail.data['viewer']['status'], 'finished')
        self.assertEqual(detail.data['viewer']['score'], 8)
        board = detail.data['scoreboard']
        self.assertEqual([row['username'] for row in board], ['friend', 'creator'])
        self.assertEqual(board[0]['results'], ['Correct'] * 8 + ['Incorrect'] * 2)
        self.assertTrue(board[0]['is_viewer'])
        self.assertTrue(board[1]['is_creator'])

    def test_a_finished_run_cannot_be_replayed(self):
        code = self._code()
        self._play(code, self.friend, correct=3)

        again = self._start(code)

        self.assertEqual(again.status_code, 409)
        self.assertEqual(DuelChallengeAttempt.objects.get().score, 3)

    def test_scoreboard_ranks_several_friends_by_score(self):
        code = self._code()
        other = self._user('other')
        self._play(code, self.friend, correct=5)
        self._play(code, other, correct=9)

        self.client.force_authenticate(user=self.creator)
        board = self.client.get(f'/api/challenges/{code}/').data['scoreboard']

        self.assertEqual([(row['username'], row['score']) for row in board],
                         [('other', 9), ('creator', 7), ('friend', 5)])

    def test_a_run_in_progress_is_not_on_the_scoreboard(self):
        code = self._code()
        self._start(code)

        self.client.force_authenticate(user=self.creator)
        board = self.client.get(f'/api/challenges/{code}/').data['scoreboard']

        self.assertEqual([row['username'] for row in board], ['creator'])

    def test_stopping_early_counts_the_rest_as_blank(self):
        code = self._code()
        self._start(code)
        order = DuelChallenge.objects.get(code=code).question_ids
        self._answer(code, order[0], 'b')
        self._answer(code, order[1], 'b')

        response = self.client.post(f'/api/challenges/{code}/finish/', format='json')

        self.assertEqual(response.data['viewer']['status'], 'finished')
        self.assertEqual(response.data['viewer']['score'], 2)
        mine = next(row for row in response.data['scoreboard'] if row['is_viewer'])
        self.assertEqual(mine['results'], ['Correct', 'Correct'] + ['Blank'] * 8)

    # --- the clock ------------------------------------------------------------

    def _run_out_the_clock(self):
        DuelChallengeAttempt.objects.update(started_at=timezone.now() - timedelta(seconds=400))

    def test_an_answer_after_the_clock_is_refused_and_the_run_closes(self):
        code = self._code()
        self._start(code)
        order = DuelChallenge.objects.get(code=code).question_ids
        self._answer(code, order[0], 'b')
        self._run_out_the_clock()

        late = self._answer(code, order[1], 'b')

        self.assertEqual(late.status_code, 409)
        attempt = DuelChallengeAttempt.objects.get()
        self.assertTrue(attempt.is_finished)
        self.assertEqual(attempt.score, 1)
        # Stamped with the deadline, not with whenever the late request arrived.
        self.assertEqual(attempt.finished_at, attempt.deadline)

    def test_an_abandoned_run_is_settled_when_anyone_looks(self):
        code = self._code()
        self._start(code)
        self._run_out_the_clock()

        self.client.force_authenticate(user=self.creator)
        board = self.client.get(f'/api/challenges/{code}/').data['scoreboard']

        self.assertEqual([(row['username'], row['score']) for row in board], [('creator', 7), ('friend', 0)])

    def test_an_expired_challenge_cannot_be_started(self):
        code = self._code()
        DuelChallenge.objects.filter(code=code).update(expires_at=timezone.now() - timedelta(minutes=1))

        response = self._start(code)

        self.assertEqual(response.status_code, 410)
        self.assertEqual(DuelChallengeAttempt.objects.count(), 0)

    def test_a_run_started_before_expiry_can_still_be_finished(self):
        code = self._code()
        self._start(code)
        DuelChallenge.objects.filter(code=code).update(expires_at=timezone.now() - timedelta(minutes=1))
        question_id = DuelChallenge.objects.get(code=code).question_ids[0]

        response = self._answer(code, question_id, 'b')

        self.assertEqual(response.status_code, 200)

    # --- integrity ------------------------------------------------------------

    def test_answers_stay_hidden_until_the_question_is_answered(self):
        code = self._code()
        self._start(code)
        first, second = DuelChallenge.objects.get(code=code).question_ids[:2]
        self._answer(code, first, 'a')

        answered = self.client.post('/api/get_answer/', {'question_id': first}, format='json')
        unanswered = self.client.post('/api/get_answer/', {'question_id': second}, format='json')

        self.assertEqual(answered.status_code, 200)
        self.assertEqual(unanswered.status_code, 403)

    def test_answers_open_up_once_the_run_is_over(self):
        code = self._code()
        self._start(code)
        question_id = DuelChallenge.objects.get(code=code).question_ids[5]
        self.client.post(f'/api/challenges/{code}/finish/', format='json')

        response = self.client.post('/api/get_answer/', {'question_id': question_id}, format='json')

        self.assertEqual(response.status_code, 200)

    def test_an_abandoned_run_does_not_lock_its_questions_forever(self):
        code = self._code()
        self._start(code)
        question_id = DuelChallenge.objects.get(code=code).question_ids[5]
        self._run_out_the_clock()

        response = self.client.post('/api/get_answer/', {'question_id': question_id}, format='json')

        self.assertEqual(response.status_code, 200)

    def test_a_challenge_never_moves_duel_elo(self):
        before = {
            user.id: TestPrepUserStats.for_user(user, 'sat').duel_elo
            for user in (self.creator, self.friend)
        }
        code = self._code()

        self._play(code, self.friend, correct=10)

        for user in (self.creator, self.friend):
            self.assertEqual(TestPrepUserStats.for_user(user, 'sat').duel_elo, before[user.id])

    # --- "my challenges" ------------------------------------------------------

    def test_my_challenges_lists_what_i_sent_and_what_i_played(self):
        code = self._code()
        self._play(code, self.friend, correct=9)

        self.client.force_authenticate(user=self.creator)
        mine = self.client.get('/api/challenges/mine/').data
        self.client.force_authenticate(user=self.friend)
        theirs = self.client.get('/api/challenges/mine/').data

        self.assertEqual(len(mine['sent']), 1)
        self.assertEqual(mine['sent'][0]['code'], code)
        self.assertEqual(mine['sent'][0]['players'], 1)
        self.assertEqual(mine['sent'][0]['best']['username'], 'friend')
        self.assertEqual(mine['sent'][0]['best']['score'], 9)
        self.assertEqual(mine['played'], [])
        self.assertEqual(theirs['sent'], [])
        self.assertEqual(theirs['played'][0]['your_score'], 9)
        self.assertEqual(theirs['played'][0]['creator_score'], 7)
        self.assertEqual(theirs['played'][0]['creator']['username'], 'creator')
