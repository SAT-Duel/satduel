import random
from django.utils import timezone
from django.contrib.auth.models import User
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver


class Question(models.Model):
    question = models.TextField(null=False, blank=False)
    choice_a = models.CharField(max_length=1000)
    choice_b = models.CharField(max_length=1000)
    choice_c = models.CharField(max_length=1000)
    choice_d = models.CharField(max_length=1000)
    answer = models.CharField(max_length=1, choices=[('A', 'A'), ('B', 'B'), ('C', 'C'), ('D', 'D')])
    difficulty = models.IntegerField(choices=[(i, str(i)) for i in range(1, 6)])
    question_type = models.CharField(max_length=1000, null=True, blankd=True)
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
        default_question_types = [
            'Cross-Text Connections', 'Text Structure and Purpose', 'Words in Context',
            'Rhetorical Synthesis', 'Transitions', 'Central Ideas and Details',
            'Command of Evidence', 'Inferences', 'Boundaries', 'Form, Structure, and Sense'
        ]
        questions = list(self.objects.filter(question_type__in=default_question_types))
        if num_questions > len(questions):
            num_questions = len(questions)
        return random.sample(questions, num_questions)


class Pet(models.Model):
    name = models.CharField(max_length=255)
    price = models.IntegerField()
    animation_data = models.JSONField()  # Assuming you store animation data as JSON

    # pet perks (pet benefit)
    coin_multipliers = models.JSONField(default=dict)  # Using JSONField instead of ArrayField

    def __str__(self):
        return self.name


class Tournament(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField()
    start_time = models.DateTimeField()
    end_time = models.DateTimeField(null=True)
    duration = models.DurationField(default=timezone.timedelta(minutes=30))
    questions = models.ManyToManyField(Question)
    private = models.BooleanField(default=False)
    join_code = models.CharField(max_length=10, blank=True, null=True)

    def __str__(self):
        return self.name

    @property
    def questionNumber(self):
        return self.questions.count()

    @property
    def participantNumber(self):
        return self.tournamentparticipation_set.count()


class TournamentParticipation(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE)
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)
    score = models.IntegerField(default=0)
    last_correct_submission = models.DurationField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=[('Active', 'Active'), ('Completed', 'Completed')])

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
    pets = models.ManyToManyField(Pet, related_name='owners', blank=True)
    my_tournaments = models.ManyToManyField(Tournament, related_name='my_tournaments', blank=True)

    def sigma(self, r, kappa, s=400):
        """
        Calculate the sigma function used in the Elo-Davidson model.
        """
        exponent = 10 ** (r / s)
        return exponent / (10 ** (-r / s) + kappa + exponent)

    def g_function(self, r, kappa, s=400):
        """
        Calculate the g(r; kappa) function.
        """
        exponent = 10 ** (r / s)
        return (exponent + kappa / 2) / (10 ** (-r / s) + kappa + exponent)

    def f(self, result, elo1, elo2, kappa=1, k=32):
        """
        Update Elo ratings based on the result using the Elo-Davidson model.

        Parameters:
        result (float): 1 for win, 0.5 for draw, 0 for loss (Player 1's perspective).
        elo1 (float): Player 1's Elo rating before the game.
        elo2 (float): Player 2's Elo rating before the game.
        kappa (float): Parameter controlling draw probability. Default is 1.
        k (float): Learning rate or K-factor. Default is 32.

        Returns:
        new_elo1 (float): Player 1's updated Elo rating.
        new_elo2 (float): Player 2's updated Elo rating.
        """
        # Rating difference
        r_ab = elo1 - elo2

        # Expected score for player 1
        E1 = self.g_function(r_ab, kappa)
        E2 = 1 - E1  # Expected score for player 2

        # Update ratings
        new_elo1 = elo1 + k * (result - E1)
        new_elo2 = elo2 + k * ((1 - result) - E2)

        return new_elo1, new_elo2

    def update_elo(self, opponent_elo, result):
        # k = 32  # K-factor for ELO calculation
        # expected_score = 1 / (1 + 10 ** ((opponent_elo - self.elo_rating) / 400))
        # new_elo = self.elo_rating + k * (result - expected_score)
        # self.elo_rating = int(new_elo)
        # self.save()
        result = result  # Draw
        elo1 = self.elo_rating  # Player 1's initial rating
        elo2 = opponent_elo # Player 2's initial rating
        kappa = 1  # Default draw adjustment parameter
        k = 16  # K-factor - adjust for how much it fluctuates after a result

        new_elo1, new_elo2 = self.f(result, elo1, elo2, kappa, k)
        self.elo_rating = int(new_elo1)
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
    battle_duration = models.IntegerField(default=300)  # Duration in seconds, default 5 minutes
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


class Game(models.Model):
    host = models.ForeignKey(User, related_name='host', on_delete=models.CASCADE)
    players = models.ManyToManyField(User, related_name='players', blank=True)
    max_players = models.IntegerField(default=2)
    questions = models.ManyToManyField(Question, blank=True)
    question_number = models.IntegerField(default=10)
    status = models.CharField(max_length=10,
                              choices=[('Waiting', 'Waiting'), ('Battling', 'Battling'), ('Ended', 'Ended')])
    battle_start_time = models.DateTimeField(null=True, blank=True)
    battle_duration = models.IntegerField(default=600)  # Duration in seconds, default 10 minutes
    created_at = models.DateTimeField(auto_now_add=True)
    password = models.CharField(max_length=255, blank=True, null=True)
    has_password = models.BooleanField(default=False)

    def assign_questions(self):
        # If questions already exist, return without doing anything
        if self.questions.exists():
            return

        # Assign random questions to the game
        random_questions = Question.get_random_questions(self.question_number)
        self.questions.set(random_questions)
        self.save()

        # Initialize GameQuestion entries for each player
        questions_status = {index: {'status': 'blank', 'duration': None} for index in
                            self.questions.all().order_by('id')}
        for player in self.players.all():
            game_question = GameQuestion(user=player, game=self, questions_status=questions_status)
            game_question.save()
        game_question = GameQuestion(user=self.host, game=self, questions_status=questions_status)
        game_question.save()


class GameQuestion(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    game = models.ForeignKey(Game, on_delete=models.CASCADE)
    questions_status = models.JSONField(default=dict)


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


class UserStatistics(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='infinitequestionstatistics')
    login_streak = models.IntegerField(default=0)
    last_login_date = models.DateField(null=True, blank=True)
    correct_number = models.IntegerField(default=0)
    incorrect_number = models.IntegerField(default=0)
    current_streak = models.IntegerField(default=0)
    xp = models.IntegerField(default=0)
    level = models.IntegerField(default=0)
    coins = models.IntegerField(default=0)
    normal_multiplier = models.FloatField(default=1.00)
    user_pet_levels = models.JSONField(default=dict)

    def __str__(self):
        return f"{self.user.username} - {self.correct_number}/{self.correct_number + self.incorrect_number}"

    def total_multiplier(self):  # normal multiplier + pet multipliers
        total_multiplier = self.normal_multiplier
        for pet_id, level in self.user_pet_levels.items():
            try:
                pet = Pet.objects.get(id=pet_id)
                # Get coin multipliers for the pet
                multipliers = pet.coin_multipliers

                # If the current level does not exist, default to the highest level
                if str(level) in multipliers:
                    total_multiplier *= multipliers[str(level)]
                else:
                    # Default to the highest level multiplier available
                    highest_level = max(map(int, multipliers.keys()))  # Convert keys to integers to find the max level
                    total_multiplier *= multipliers[str(highest_level)]
            except Pet.DoesNotExist:
                continue  # If the pet doesn't exist, skip it

        return round(total_multiplier, 2)  # Return the total multiplier rounded to 2 decimal places

    def increment_login_streak(self):
        today = timezone.now().date()
        if self.last_login_date == today:
            return  # Streak already updated for today

        if self.last_login_date == today - timezone.timedelta(days=1):
            self.login_streak += 1  # Continue streak
        else:
            self.login_streak = 1  # Reset streak

        self.last_login_date = today
        self.save()


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


class House(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=255, default="My House")


class Area(models.Model):
    house = models.ForeignKey(House, related_name='areas', on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    is_unlocked = models.BooleanField(default=True)  # Automatically unlocked for now
    position_x = models.IntegerField()  # Position on the map
    position_y = models.IntegerField()
    width = models.IntegerField()  # Size of the area
    height = models.IntegerField()

    def __str__(self):
        return self.name


@receiver(post_save, sender=User)
def create_house(sender, instance, created, **kwargs):
    if created:
        House.objects.create(user=instance)


class OnlineUser(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    last_seen = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return self.user.username


class Quest(models.Model):
    QUEST_TYPE_CHOICES = [
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('one_time', 'One-Time'),
    ]

    name = models.CharField(max_length=255)
    description = models.TextField()
    target = models.IntegerField()
    reward_xp = models.IntegerField(default=0)
    reward_coins = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    quest_type = models.CharField(max_length=10, choices=QUEST_TYPE_CHOICES, default='daily')
    # Add any additional fields as needed

    def __str__(self):
        return self.name


class UserQuest(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    quest = models.ForeignKey(Quest, on_delete=models.CASCADE)
    progress = models.IntegerField(default=0)
    is_completed = models.BooleanField(default=False)
    is_reward_claimed = models.BooleanField(default=False)
    last_completed = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.user.username} - {self.quest.name}"

