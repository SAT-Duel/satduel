from django.db import models
from django.conf import settings
from api.models import Question
import string
import random


def generate_class_code():
    length = 6
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))
        if not Class.objects.filter(code=code).exists():
            return code


class Class(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    code = models.CharField(max_length=6, default=generate_class_code, unique=True)
    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='taught_classes')
    max_students = models.PositiveIntegerField(default=30)
    created_at = models.DateTimeField(auto_now_add=True)


class ClassParticipation(models.Model):
    ROLE_CHOICES = [
        ('TEACHER', 'Teacher'),
        ('STUDENT', 'Student'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    classroom = models.ForeignKey(Class, on_delete=models.CASCADE)
    role = models.CharField(max_length=7, choices=ROLE_CHOICES)
    joined_at = models.DateTimeField(auto_now_add=True)


class ProblemSet(models.Model):
    classroom = models.ForeignKey(Class, on_delete=models.CASCADE, related_name='problem_sets')
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    questions = models.ManyToManyField(Question)
    created_at = models.DateTimeField(auto_now_add=True)
    due_date = models.DateTimeField(null=True, blank=True)
