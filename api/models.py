import random
from django.contrib.auth.models import User
from django.db import models


class Question(models.Model):
    question = models.TextField(null=False, blank=False)
    choice_a = models.CharField(max_length=200)
    choice_b = models.CharField(max_length=200)
    choice_c = models.CharField(max_length=200)
    choice_d = models.CharField(max_length=200)
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

    # Add more fields as necessary

    def __str__(self):
        return f"{self.user.username}'s Profile"


class Room(models.Model):
    user1 = models.ForeignKey(User, related_name='room_user1', on_delete=models.CASCADE)
    user2 = models.ForeignKey(User, related_name='room_user2', on_delete=models.CASCADE, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    questions = models.ManyToManyField(Question, blank=True)

    def is_full(self):
        return self.user2 is not None

    def __str__(self):
        return f"Room {self.id} by {self.user1.username} and {self.user2.username if self.user2 else 'empty'}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.questions.exists():
            self.questions.set(Question.get_random_questions(10))
        if self.user1 and self.user2:
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
    status = models.CharField(max_length=10, choices=[('pending', 'Pending'), ('accepted', 'Accepted'), ('rejected', 'Rejected')], default='pending')

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