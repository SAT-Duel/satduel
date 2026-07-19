from django.contrib.auth.models import User
from django.db import models, transaction
from django.utils import timezone
import random
import pytz


DUEL_EMOJIS = (
    '👍', '🔥', '😂', '😮', '🎉', '💀', '👀', '🧠', '💪', '😎',
    '🤔', '😭', '🫡', '🚀', '⚡', '🎯', '🏆', '🤝', '😅', '🙃',
    '😤', '🥳', '🤯', '👏', '✨', '😈', '🐐', '✅', '❌', '🫠',
)


def default_duel_emotes():
    return list(DUEL_EMOJIS[:4])


# =========================================================
# Core Learning Models
# =========================================================

class Question(models.Model):
    """Model representing a learning question with multiple choice answers."""
    question = models.TextField(null=False, blank=False)
    choice_a = models.CharField(max_length=1000)
    choice_b = models.CharField(max_length=1000)
    choice_c = models.CharField(max_length=1000)
    choice_d = models.CharField(max_length=1000)
    answer = models.CharField(max_length=1, choices=[('A', 'A'), ('B', 'B'), ('C', 'C'), ('D', 'D')])
    difficulty = models.IntegerField(choices=[(i, str(i)) for i in range(1, 6)], db_index=True)
    question_type = models.CharField(max_length=1000, null=True, blank=True, db_index=True)
    explanation = models.TextField(null=True, blank=True)
    sp_elo_rating = models.IntegerField(default=0)

    class Meta:
        indexes = [
            # list_questions filters on type and difficulty together
            models.Index(fields=['question_type', 'difficulty']),
        ]

    def __str__(self):
        return self.question

    def save(self, *args, **kwargs):
        # If this is a newly created object with no Elo yet, initialize based on difficulty
        if self.pk is None and self.sp_elo_rating == 0:
            if self.difficulty == 1:
                self.sp_elo_rating = 600
            elif self.difficulty == 2:
                self.sp_elo_rating = 800
            elif self.difficulty == 3:
                self.sp_elo_rating = 1200
            elif self.difficulty == 4:
                self.sp_elo_rating = 1600
            elif self.difficulty == 5:
                self.sp_elo_rating = 2000

        super().save(*args, **kwargs)

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


class QuestionReport(models.Model):
    REASON_CHOICES = [
        ('incorrect_statement', 'Incorrect problem statement'),
        ('no_correct_choice', 'No correct answer choice'),
        ('incorrect_answer', 'Incorrect marked answer'),
        ('bad_explanation', 'Bad or unclear explanation'),
        ('other', 'Other issue'),
    ]

    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='reports')
    reporter = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='question_reports')
    reason = models.CharField(max_length=32, choices=REASON_CHOICES)
    details = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Q{self.question_id}: {self.get_reason_display()}"


# =========================================================
# Customization and Virtual Space Models
# =========================================================

class Pet(models.Model):
    """Represents collectible pets with benefits."""
    name = models.CharField(max_length=255)
    price = models.IntegerField()
    animation_data = models.JSONField()
    coin_multipliers = models.JSONField(default=dict)

    def __str__(self):
        return self.name


# =========================================================
# User Profile and Statistics Models
# =========================================================

class SATExamDate(models.Model):
    """Weekend SAT dates shown during onboarding, maintained in Django admin."""
    date = models.DateField(unique=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['date']

    def __str__(self):
        return f'{self.date:%B} {self.date.day}, {self.date.year}'


class Profile(models.Model):
    """Extended user profile with additional attributes and game statistics."""
    AVATAR_CHOICES = [
        ('violet', 'Violet'),
        ('sky', 'Sky'),
        ('emerald', 'Emerald'),
        ('amber', 'Amber'),
        ('rose', 'Rose'),
        ('slate', 'Slate'),
    ]
    AVATAR_ICON_CHOICES = [
        ('initial', 'Initial'),
        ('nova-quill', 'Nova Quill'),
        ('ember-abacus', 'Ember Abacus'),
        ('cipher-lantern', 'Cipher Lantern'),
        ('prism-page', 'Prism Page'),
        ('orbit-scout', 'Orbit Scout'),
        ('inkcap-alchemist', 'Inkcap Alchemist'),
        ('bloom-circuit', 'Bloom Circuit'),
        ('echo-fencer', 'Echo Fencer'),
        ('slate-sentinel', 'Slate Sentinel'),
        ('mira-mnemonic', 'Mira Mnemonic'),
        ('pixel-pathfinder', 'Pixel Pathfinder'),
        ('margin-warden', 'Margin Warden'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    biography = models.TextField(blank=True, null=True)
    grade = models.CharField(
        max_length=3,
        choices=[(str(i), str(i)) for i in range(1, 13)] + [('<1', '<1'), ('>12', '>12')],
        default='11'
    )
    role = models.CharField(
        max_length=7,
        choices=[('STUDENT', 'Student'), ('TEACHER', 'Teacher')],
        default='STUDENT'
    )
    
    friends = models.ManyToManyField(User, related_name='friends', blank=True)
    elo_rating = models.IntegerField(default=1500)  # Duel ELO rating
    country = models.CharField(max_length=2, default='US')
    avatar = models.CharField(max_length=32, choices=AVATAR_CHOICES, default='violet')
    avatar_icon = models.CharField(max_length=32, choices=AVATAR_ICON_CHOICES, default='initial')
    # Bot profiles use normal User rows so they work with rooms, Elo, avatars,
    # and history. Email/notification jobs must always exclude this flag.
    is_bot = models.BooleanField(default=False, db_index=True)
    duel_emotes = models.JSONField(default=default_duel_emotes)
    max_streak = models.IntegerField(default=0)
    pets = models.ManyToManyField('api.Pet', related_name='owners', blank=True)
    goal = models.CharField(max_length=255,
                            choices=[('beginner', 'Beginner Path'), ('intermediate', 'Steady Learner'),
                                     ('advanced', 'Advanced Track'), ('expert', 'Expert Challenge')],
                            default='beginner')
    my_tournaments = models.ManyToManyField('api.Tournament', related_name='my_tournaments', blank=True)
    timezone = models.CharField(
        max_length=50,
        default='UTC',
        choices=[(tz, tz) for tz in pytz.all_timezones]
    )
    # Premium tier: flag + optional expiry. A null premium_until means
    # "until manually revoked" (e.g. lifetime or admin-granted).
    is_premium = models.BooleanField(default=False)
    premium_until = models.DateTimeField(null=True, blank=True)
    stripe_customer_id = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    stripe_subscription_id = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    stripe_price_id = models.CharField(max_length=255, blank=True, null=True)
    username_changed_at = models.DateTimeField(null=True, blank=True)

    # Account setup and communication preferences. `sat_exam_date_selected`
    # distinguishes "I don't know yet" from an existing account that has not
    # answered the question.
    sat_exam_date = models.DateField(null=True, blank=True)
    sat_exam_date_selected = models.BooleanField(default=False)
    marketing_opt_in = models.BooleanField(null=True, blank=True, default=None)
    terms_accepted_at = models.DateTimeField(null=True, blank=True)

    # Day streak: completing the daily practice goal (DAILY_PRACTICE_GOAL
    # answers in the user's local day) extends it. Evaluated lazily — a missed
    # day reads as 0 without any scheduled job (see practice_views).
    practice_streak = models.IntegerField(default=0)
    longest_practice_streak = models.IntegerField(default=0)
    last_practice_completed = models.DateField(null=True, blank=True)

    @property
    def has_premium(self):
        if not self.is_premium:
            return False
        return self.premium_until is None or self.premium_until > timezone.now()

    @property
    def onboarding_required(self):
        return (
            not self.sat_exam_date_selected
            or self.marketing_opt_in is None
            or self.terms_accepted_at is None
        )

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
        elo2 = opponent_elo  # Player 2's initial rating
        kappa = 1  # Default draw adjustment parameter
        k = 16  # K-factor - adjust for how much it fluctuates after a result

        new_elo1, new_elo2 = self.f(result, elo1, elo2, kappa, k)
        self.elo_rating = int(new_elo1)
        self.save()

    def __str__(self):
        return f"{self.user.username}'s Profile"


class PracticeStats(models.Model):
    """Per-user, per-subject practice state: rating and lifetime counters.
    One row per (user, subject), so adding a new subject is a data change,
    not a schema change. Accuracy is derived (correct / answered), never
    stored, so it can't drift. In-progress questions live in
    PracticeActiveQuestion (one per lane, not per subject)."""
    SUBJECT_CHOICES = [('english', 'English'), ('math', 'Math')]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='practice_stats')
    subject = models.CharField(max_length=10, choices=SUBJECT_CHOICES)
    elo = models.IntegerField(default=1200)
    answered = models.IntegerField(default=0)
    correct = models.IntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'subject'], name='unique_practice_stats_per_subject'),
        ]

    @property
    def accuracy(self):
        return self.correct / self.answered if self.answered else None

    def __str__(self):
        return f"{self.user.username} {self.subject}: elo {self.elo}, {self.correct}/{self.answered}"


class PracticeTypeStats(models.Model):
    """Per-user, per-question-type progress through the question bank.
    `solved` counts DISTINCT questions attempted (practice never re-serves an
    attempted question, so attempted == progress toward finishing the type);
    `correct` counts how many of those were answered right. Derived from
    PracticeAttempt: the backfill migration rebuilds both from the attempt
    log, so pre-log legacy activity intentionally starts at zero here."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='practice_type_stats')
    question_type = models.CharField(max_length=1000)
    solved = models.IntegerField(default=0)
    correct = models.IntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'question_type'], name='unique_practice_type_stats'),
        ]

    def __str__(self):
        return f"{self.user.username} [{self.question_type}]: {self.correct}/{self.solved}"


class PracticeActiveQuestion(models.Model):
    """The in-progress practice question, one per lane. A lane is either a
    subject's random mix ('english:any' / 'math:any') or a specific question
    type for premium topic drills, so switching lanes and back resumes the
    same question instead of letting it be skipped. Rows are deleted when the
    question is answered, so the table only holds open questions."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='practice_active_questions')
    lane = models.CharField(max_length=128)
    question = models.ForeignKey('api.Question', on_delete=models.CASCADE, related_name='+')

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'lane'], name='unique_active_question_per_lane'),
        ]

    def __str__(self):
        return f"{self.user.username} [{self.lane}] -> Q{self.question_id}"


class UserStatistics(models.Model):
    """Shop economy state: coins and pet multipliers.

    Practice counters used to live here too; they moved to PracticeStats
    (per-subject), and duplicate rows were merged when this became OneToOne.
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='infinitequestionstatistics')
    coins = models.IntegerField(default=0)
    normal_multiplier = models.FloatField(default=1.00)
    user_pet_levels = models.JSONField(default=dict)

    def __str__(self):
        return f"{self.user.username} - {self.coins} coins"

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



class PowerSprintStatistics(models.Model):
    """Tracks user's performance in different game modes."""
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    bullet_record = models.IntegerField(default=0)
    blitz_record = models.IntegerField(default=0)
    rapid_record = models.IntegerField(default=0)
    marathon_record = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.user.username} - {self.bullet_record}/{self.blitz_record}/{self.rapid_record}/{self.marathon_record}"


class SurvivalStatistics(models.Model):
    """Tracks user's survival mode performance."""
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    record = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.user.username} - {self.record}"


# =========================================================
# Game Mechanics Models
# =========================================================

class Tournament(models.Model):
    """Represents a tournament event with multiple participants."""
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
    """Tracks user participation in tournaments."""
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


class Room(models.Model):
    """Represents a battle room between two users."""
    user1 = models.ForeignKey(User, related_name='room_user1', on_delete=models.CASCADE)
    user2 = models.ForeignKey(User, related_name='room_user2', on_delete=models.CASCADE, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    questions = models.ManyToManyField(Question, blank=True)
    status = models.CharField(max_length=10, db_index=True,
                              choices=[('Searching', 'Searching'), ('Battling', 'Battling'), ('Ended', 'Ended')])
    battle_start_time = models.DateTimeField(null=True, blank=True)
    battle_duration = models.IntegerField(default=300)  # Duration in seconds, default 5 minutes
    winner = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    user1_score = models.IntegerField(default=0)
    user2_score = models.IntegerField(default=0)
    user1_elo_before = models.IntegerField(null=True, blank=True)
    user1_elo_after = models.IntegerField(null=True, blank=True)
    user2_elo_before = models.IntegerField(null=True, blank=True)
    user2_elo_after = models.IntegerField(null=True, blank=True)

    def is_full(self):
        return self.user2 is not None

    def is_battle_ended(self):
        if self.battle_start_time and self.status == 'Battling':
            return timezone.now() > self.battle_start_time + timezone.timedelta(seconds=self.battle_duration)
        return False

    def __str__(self):
        return f"Room {self.id} by {self.user1.username} and {self.user2.username if self.user2 else 'empty'}"

    def end_battle(self):
        if not self.user2:
            return

        if self.user1_score > self.user2_score:
            self.winner = self.user1
            result_user1, result_user2 = 1, 0
        elif self.user2_score > self.user1_score:
            self.winner = self.user2
            result_user1, result_user2 = 0, 1
        else:
            self.winner = None
            result_user1 = result_user2 = 0.5

        user1_profile = self.user1.profile
        user2_profile = self.user2.profile
        user1_start = user1_profile.elo_rating
        user2_start = user2_profile.elo_rating
        self.user1_elo_before = user1_start
        self.user2_elo_before = user2_start
        self.status = 'Ended'
        self.save()

        user1_profile.update_elo(user2_start, result_user1)
        user2_profile.update_elo(user1_start, result_user2)
        for profile in (user1_profile, user2_profile):
            if profile.is_bot and profile.elo_rating > 1799:
                profile.elo_rating = 1799
                profile.save(update_fields=['elo_rating'])
        self.user1_elo_after = user1_profile.elo_rating
        self.user2_elo_after = user2_profile.elo_rating
        Room.objects.filter(pk=self.pk).update(
            user1_elo_after=self.user1_elo_after,
            user2_elo_after=self.user2_elo_after,
        )

    def save(self, *args, **kwargs):
        previous_status = None
        if self.pk:
            previous_status = Room.objects.filter(pk=self.pk).values_list('status', flat=True).first()

        super().save(*args, **kwargs)
        if self.status == 'Ended' and previous_status != 'Ended':
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
    """Tracks individual question attempts in rooms."""
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    room = models.ForeignKey(Room, on_delete=models.CASCADE)
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    status = models.CharField(max_length=10,
                              choices=[('Correct', 'Correct'), ('Incorrect', 'Incorrect'), ('Blank', 'Blank')])
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.question.question} - {self.status}"


class DuelEmote(models.Model):
    """A lightweight in-duel reaction, including delayed bot reactions."""
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='emotes')
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='duel_emotes')
    emoji = models.CharField(max_length=8)
    created_at = models.DateTimeField(auto_now_add=True)
    visible_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['visible_at', 'id']

    def __str__(self):
        return f"{self.sender.username} {self.emoji} in room {self.room_id}"


class FriendRequest(models.Model):
    """Handles friend connections between users."""
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


class Ranking(models.Model):
    """Global user rankings based on performance."""
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    rank = models.PositiveIntegerField(unique=True)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['rank']

    def __str__(self):
        return f"{self.user.username} - Rank {self.rank}"

    @classmethod
    def update_rankings(cls):
        """Recompute every user's rank in bulk (was 2 queries per user)."""
        profiles = list(
            Profile.objects.order_by('-elo_rating', 'user_id')
            .values_list('user_id', flat=True)
        )
        existing = {r.user_id: r for r in cls.objects.all()}

        # Assign to a temporary offset first so the unique `rank` constraint
        # doesn't collide while rows are being renumbered.
        offset = len(profiles) + 1
        to_update = []
        to_create = []
        for index, user_id in enumerate(profiles, start=1):
            ranking = existing.get(user_id)
            if ranking is None:
                to_create.append(cls(user_id=user_id, rank=index + offset))
            else:
                ranking.rank = index + offset
                to_update.append(ranking)

        with transaction.atomic():
            cls.objects.bulk_update(to_update, ['rank'])
            cls.objects.bulk_create(to_create)
            # Second pass: shift everyone down to their real rank.
            all_rankings = list(cls.objects.order_by('rank'))
            for real_rank, ranking in enumerate(all_rankings, start=1):
                ranking.rank = real_rank
            cls.objects.bulk_update(all_rankings, ['rank'])


# =========================================================
# Tracking and Progress Models
# =========================================================

class OnlineUser(models.Model):
    """Tracks user online status."""
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    last_seen = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return self.user.username


class PracticeAttempt(models.Model):
    """One infinite-practice answer submission.

    The source of truth for the daily free-tier quota and for "only the first
    attempt at a question moves Elo".
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='practice_attempts')
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='practice_attempts')
    subject = models.CharField(
        max_length=10,
        choices=[('english', 'English'), ('math', 'Math')],
        default='english',
        db_index=True,
    )
    correct = models.BooleanField()
    # Keep the answer text submitted at the time of the attempt. Older rows
    # predate answer-history, so they intentionally remain blank.
    selected_choice = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['user', 'created_at']),   # daily quota lookups
            models.Index(fields=['user', 'question']),      # first-attempt checks
            models.Index(fields=['user', 'subject']),       # profile + leaderboard splits
        ]

    def __str__(self):
        return f"{self.user.username} - Q{self.question_id} - {'✓' if self.correct else '✗'}"


class SavedQuestion(models.Model):
    """A question the user marked for review from practice.

    `subject` is denormalized off the question's type the same way
    PracticeAttempt does it, so the saved list splits by subject without
    re-deriving the taxonomy on every read.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='saved_questions')
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='saved_by')
    subject = models.CharField(
        max_length=10,
        choices=[('english', 'English'), ('math', 'Math')],
        default='english',
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        constraints = [
            models.UniqueConstraint(fields=['user', 'question'], name='unique_saved_question_per_user'),
        ]
        indexes = [
            models.Index(fields=['user', 'subject']),      # saved list, split by subject
            models.Index(fields=['user', 'created_at']),   # newest-first paging
        ]

    def __str__(self):
        return f"{self.user.username} saved Q{self.question_id}"


# =========================================================
# Party Mode (Kahoot-style live rooms)
# =========================================================

PARTY_COUNTDOWN_SECONDS = 5
# Players polling within this window count as present; "everyone answered"
# ignores ghosts who closed the tab so one dropout can't stall the room.
PARTY_ACTIVE_WINDOW_SECONDS = 12
# A player who hasn't polled for this long has left (closed the tab, swiped
# back). Long enough to survive a refresh or brief app switch.
PARTY_PRESENCE_TIMEOUT_SECONDS = 30

PARTY_MAX_TEAMS = 4
PARTY_DEFAULT_TEAM_NAMES = ('Team A', 'Team B', 'Team C', 'Team D')
# How long players get to place a Final Jeopardy bet before the last question.
PARTY_WAGER_SECONDS = 30


class PartyRoom(models.Model):
    """A live Kahoot-style quiz room.

    Clients poll the state endpoint; `advance()` derives phase transitions
    from timestamps on every read, so there is no background worker.
    """
    STATUSES = ('lobby', 'countdown', 'question', 'wager', 'leaderboard', 'finished')
    MODES = ('classic', 'teams', 'survival', 'jeopardy')

    host = models.ForeignKey(User, related_name='hosted_parties', on_delete=models.CASCADE)
    code = models.CharField(max_length=6, db_index=True)
    status = models.CharField(max_length=12, default='lobby',
                              choices=[(s, s) for s in STATUSES])
    mode = models.CharField(max_length=10, default='classic',
                            choices=[(m, m) for m in MODES])
    # Teams mode only. `team_names` is index-aligned with PartyPlayer.team.
    num_teams = models.IntegerField(default=2)
    random_teams = models.BooleanField(default=True)
    team_names = models.JSONField(default=list)
    max_players = models.IntegerField(default=6)
    num_questions = models.IntegerField(default=10)
    seconds_per_question = models.IntegerField(default=90)
    subject = models.CharField(max_length=8, default='mixed',
                               choices=[(s, s) for s in ('math', 'english', 'mixed')])
    difficulty = models.CharField(max_length=6, default='medium',
                                  choices=[(d, d) for d in ('easy', 'medium', 'hard')])
    question_ids = models.JSONField(default=list)  # ordered; index = question number - 1
    current_index = models.IntegerField(default=0)
    phase_started_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Party {self.code} by {self.host.username} ({self.status})"

    def current_question_id(self):
        if 0 <= self.current_index < len(self.question_ids):
            return self.question_ids[self.current_index]
        return None

    def question_deadline(self):
        return self.phase_started_at + timezone.timedelta(seconds=self.seconds_per_question)

    def wager_deadline(self):
        return self.phase_started_at + timezone.timedelta(seconds=PARTY_WAGER_SECONDS)

    def is_final_question(self):
        return self.current_index + 1 >= len(self.question_ids)

    def is_wager_question(self):
        """True while the room is on the Final Jeopardy betting question."""
        return self.mode == 'jeopardy' and self.is_final_question()

    def settle_unplayed_wagers(self):
        """Charge bets to anyone who let the final question time out.

        Without this, sitting the question out would be strictly safer than
        answering it, which defeats the whole point of betting.
        """
        key = str(self.current_index)
        for player in self.players.all():
            if key in player.answers or not player.wager:
                continue
            player.answers[key] = {
                'choice': None, 'correct': False,
                'points': -player.wager, 'wager': player.wager,
            }
            player.score -= player.wager
            player.save(update_fields=['answers', 'score'])

    def team_label(self, index):
        names = self.team_names or []
        if 0 <= index < len(names) and str(names[index]).strip():
            return str(names[index])
        return PARTY_DEFAULT_TEAM_NAMES[index % PARTY_MAX_TEAMS]

    def assign_missing_teams(self):
        """Seat every teamless player on the smallest team.

        Covers both random assignment at kickoff and anyone the host left
        unsorted when they hit start, so nobody plays without a team.
        """
        counts = {i: 0 for i in range(self.num_teams)}
        unassigned = []
        for player in self.players.order_by('id'):
            if player.team is not None and 0 <= player.team < self.num_teams:
                counts[player.team] += 1
            else:
                unassigned.append(player)
        random.shuffle(unassigned)
        for player in unassigned:
            target = min(counts, key=lambda i: (counts[i], i))
            player.team = target
            counts[target] += 1
            player.save(update_fields=['team'])

    def sync_presence(self):
        """Reconcile the room with players who left without saying goodbye.

        Polling is our only presence signal, so this runs on every state read:
        stale lobby seats are freed, a vanished host hands the room to the
        longest-seated active player, and a room with nobody left is closed so
        its join code stops matching.
        """
        if self.status == 'finished':
            return
        cutoff = timezone.now() - timezone.timedelta(seconds=PARTY_PRESENCE_TIMEOUT_SECONDS)
        players = list(self.players.order_by('id'))
        active = [p for p in players if p.last_seen >= cutoff]
        if not active:
            self.status = 'finished'
            self.save(update_fields=['status'])
            return
        if self.status == 'lobby':
            # Mid-game seats survive a dropout (scores may still podium);
            # lobby seats don't, so the player count stays honest.
            self.players.filter(last_seen__lt=cutoff).delete()
        if all(p.user_id != self.host_id for p in active):
            self.host = active[0].user
            self.save(update_fields=['host'])

    def advance(self):
        """Move the room forward when the current phase has expired."""
        self.sync_presence()
        now = timezone.now()
        if self.status == 'countdown':
            ends = self.phase_started_at + timezone.timedelta(seconds=PARTY_COUNTDOWN_SECONDS)
            if now >= ends:
                self.status = 'question'
                self.phase_started_at = ends
                self.save(update_fields=['status', 'phase_started_at'])
        if self.status == 'wager':
            cutoff = now - timezone.timedelta(seconds=PARTY_ACTIVE_WINDOW_SECONDS)
            players = list(self.players.all())
            active = [p for p in players if p.last_seen >= cutoff] or players
            # A player with nothing to bet has nothing to decide, so they never block.
            if now >= self.wager_deadline() or all(p.wager_locked or p.score <= 0 for p in active):
                self.status = 'question'
                self.phase_started_at = now
                self.save(update_fields=['status', 'phase_started_at'])

        if self.status == 'question':
            key = str(self.current_index)
            cutoff = now - timezone.timedelta(seconds=PARTY_ACTIVE_WINDOW_SECONDS)
            players = list(self.players.all())
            active = [p for p in players if p.last_seen >= cutoff] or players
            if now >= self.question_deadline() or all(key in p.answers for p in active):
                if self.is_wager_question():
                    self.settle_unplayed_wagers()
                self.status = 'leaderboard'
                self.phase_started_at = now
                self.save(update_fields=['status', 'phase_started_at'])


class PartyPlayer(models.Model):
    """A user's seat (and running score) in a party room. The host has one too."""
    room = models.ForeignKey(PartyRoom, related_name='players', on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    score = models.IntegerField(default=0)
    team = models.IntegerField(null=True, blank=True)  # teams mode; index into room.team_names
    # Final Jeopardy bet. `wager_locked` distinguishes a deliberate bet of 0
    # from a player who simply hasn't decided yet.
    wager = models.IntegerField(default=0)
    wager_locked = models.BooleanField(default=False)
    # question index (str) -> {'choice': 'A', 'correct': bool, 'points': int}
    answers = models.JSONField(default=dict)
    last_seen = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['id']
        constraints = [
            models.UniqueConstraint(fields=['room', 'user'], name='unique_party_player'),
        ]

    def __str__(self):
        return f"{self.user.username} in party {self.room.code} ({self.score})"
