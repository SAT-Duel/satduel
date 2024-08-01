import random
from django.utils import timezone
from django.contrib.auth.models import User
from django.db import models


class Question(models.Model):
    question = models.TextField(null=False, blank=False)
    choice_a = models.CharField(max_length=1000)
    choice_b = models.CharField(max_length=1000)
    choice_c = models.CharField(max_length=1000)
    choice_d = models.CharField(max_length=1000)
    answer = models.CharField(max_length=1, choices=[('A', 'A'), ('B', 'B'), ('C', 'C'), ('D', 'D')])
    difficulty = models.IntegerField(choices=[(i, str(i)) for i in range(1, 6)])
    question_type = models.CharField(max_length=1000, null=True, blank=True)
    explanation = models.TextField(null=True, blank=True)

    def __str__(self):
        return self.question

    @property
    def answer_text(self):
        """Returns the text of the correct answer."""
        choices = {
            'A': self.choice_a,
            'B': self.choice_b,
            'C': self.choice_c,
            'D': self.choice_d,
        }
        return choices.get(self.answer, "Unknown choice")

    @classmethod
    def get_random_questions(self, num_questions):
        questions = list(self.objects.all())
        if num_questions > len(questions):
            num_questions = len(questions)
        return random.sample(questions, num_questions)


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    biography = models.TextField(blank=True, null=True)
    grade = models.CharField(max_length=3,
                             choices=[(str(i), str(i)) for i in range(1, 12)] + [('<1', '<1'), ('>12', '>12')],
                             default='11')
    friends = models.ManyToManyField(User, related_name='friends', blank=True)
    elo_rating = models.IntegerField(default=1500)  # Starting ELO rating
    problems_solved = models.IntegerField(default=0)
    country = models.CharField(max_length=2, default='US')
    max_streak = models.IntegerField(default=0)
    def update_elo(self, opponent_elo, result):
        k = 32  # K-factor for ELO calculation
        expected_score = 1 / (1 + 10 ** ((opponent_elo - self.elo_rating) / 400))
        new_elo = self.elo_rating + k * (result - expected_score)
        self.elo_rating = int(new_elo)
        self.save()
    def increment_problems_solved(self):
        self.problems_solved += 1
        self.save()


    def __str__(self):
        return f"{self.user.username}'s Profile"

class Ranking(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    rank = models.PositiveIntegerField(unique=True)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['rank']

    def __str__(self):
        return f"{self.user.username} - Rank {self.rank}"

    @classmethod
    def update_rankings(cls):
        profiles = Profile.objects.all().order_by('-elo_rating', '-problems_solved')
        for index, profile in enumerate(profiles, start=1):
            ranking, created = cls.objects.get_or_create(user=profile.user)
            ranking.rank = index
            ranking.save()

class Room(models.Model):
    user1 = models.ForeignKey(User, related_name='room_user1', on_delete=models.CASCADE)
    user2 = models.ForeignKey(User, related_name='room_user2', on_delete=models.CASCADE, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    questions = models.ManyToManyField(Question, blank=True)
    status = models.CharField(max_length=10,
                              choices=[('Searching', 'Searching'), ('Battling', 'Battling'), ('Ended', 'Ended')])
    battle_start_time = models.DateTimeField(null=True, blank=True)
    battle_duration = models.IntegerField(default=20)  # Duration in seconds, default 5 minutes
    winner = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    user1_score = models.IntegerField(default=0)
    user2_score = models.IntegerField(default=0)

    def is_full(self):
        return self.user2 is not None

    def is_battle_ended(self):
        if self.battle_start_time and self.status == 'Battling':
            return timezone.now() > self.battle_start_time + timezone.timedelta(seconds=self.battle_duration)
        return False

    def __str__(self):
        return f"Room {self.id} by {self.user1.username} and {self.user2.username if self.user2 else 'empty'}"

    def end_battle(self):
        if self.user1_score > self.user2_score:
            self.winner = self.user1
            result_user1, result_user2 = 1, 0
        elif self.user2_score > self.user1_score:
            self.winner = self.user2
            result_user1, result_user2 = 0, 1
        else:
            self.winner = None
            result_user1 = result_user2 = 0.5

        self.status = 'Ended'
        self.save()

        # Update ELO ratings
        user1_profile = self.user1.profile
        user2_profile = self.user2.profile
        user1_profile.update_elo(user2_profile.elo_rating, result_user1)
        user2_profile.update_elo(user1_profile.elo_rating, result_user2)

        # Update problems solved
        user1_profile.problems_solved += self.questions.count()
        user2_profile.problems_solved += self.questions.count()
        user1_profile.save()
        user2_profile.save()

        # Update global rankings
        # Ranking.update_rankings()
    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.status == 'Ended' and not hasattr(self, '_battle_ended'):
            self._battle_ended = True
            self.end_battle()
        if not self.questions.exists() and self.user1 and self.user2:
            self.questions.set(Question.get_random_questions(10))
            for question in self.questions.all():
                TrackedQuestion.objects.create(
                    user=self.user1,
                    room=self,
                    question=question,
                    status="Blank"
                )
                TrackedQuestion.objects.create(
                    user=self.user2,
                    room=self,
                    question=question,
                    status="Blank"
                )


class TrackedQuestion(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    room = models.ForeignKey(Room, on_delete=models.CASCADE)
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    status = models.CharField(max_length=10,
                              choices=[('Correct', 'Correct'), ('Incorrect', 'Incorrect'), ('Blank', 'Blank')])
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.question.question} - {self.status}"


class FriendRequest(models.Model):
    from_user = models.ForeignKey(User, related_name='sent_friend_requests', on_delete=models.CASCADE)
    to_user = models.ForeignKey(User, related_name='received_friend_requests', on_delete=models.CASCADE)
    timestamp = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10,
                              choices=[('pending', 'Pending'), ('accepted', 'Accepted'), ('rejected', 'Rejected')],
                              default='pending')

    def __str__(self):
        return f"Friend request from {self.from_user} to {self.to_user}"

    def accept(self):
        self.status = 'accepted'
        self.save()
        self.from_user.profile.friends.add(self.to_user)
        self.to_user.profile.friends.add(self.from_user)

    def reject(self):
        self.status = 'rejected'
        self.save()


class InfiniteQuestionStatistics(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    correct_number = models.IntegerField(default=0)
    incorrect_number = models.IntegerField(default=0)
    current_streak = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.user.username} - {self.correct_number}/{self.correct_number + self.incorrect_number}"


class PowerSprintStatistics(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    bullet_record = models.IntegerField(default=0)
    blitz_record = models.IntegerField(default=0)
    rapid_record = models.IntegerField(default=0)
    marathon_record = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.user.username} - {self.bullet_record}/{self.blitz_record}/{self.rapid_record}/{self.marathon_record}"


class SurvivalStatistics(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    record = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.user.username} - {self.record}"


class Tournament(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField()
    start_time = models.DateTimeField()
    end_time = models.DateTimeField(null=True)
    duration = models.DurationField(default=timezone.timedelta(minutes=30))
    questions = models.ManyToManyField(Question)
    private = models.BooleanField(default=False)

    def __str__(self):
        return self.name

    @property
    def questionNumber(self):
        return self.questions.count()

    @property
    def participantNumber(self):
        return self.tournamentparticipation_set.count()

    def save(self, *args, **kwargs):
        if self.start_time and self.duration:
            self.end_time = self.start_time + self.duration
        super(Tournament, self).save(*args, **kwargs)


class TournamentParticipation(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE)
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)
    score = models.IntegerField(default=0)
    last_correct_submission = models.DurationField(null=True, blank=True)

    def __str__(self):
        return f"{self.user.username} in {self.tournament.name}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)


class TournamentQuestion(models.Model):
    participation = models.ForeignKey(TournamentParticipation, on_delete=models.CASCADE)
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    status = models.CharField(max_length=10,
                              choices=[('Correct', 'Correct'), ('Incorrect', 'Incorrect'), ('Blank', 'Blank')])
    time_taken = models.DurationField(blank=True, null=True)  # Time taken to answer from start of participation

    def __str__(self):
        return f"{self.participation.user.username} - Q{self.question.id} - {self.status} - {self.time_taken}"
