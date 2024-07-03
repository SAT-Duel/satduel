from django.contrib.auth.models import User
from rest_framework import serializers
from api.models import Question, Profile, Room, TrackedQuestion


class QuestionSerializer(serializers.ModelSerializer):
    choices = serializers.SerializerMethodField()

    class Meta:
        model = Question
        fields = ['id', 'question', 'choices', 'difficulty']

    def get_choices(self, obj):
        return [obj.choice_a, obj.choice_b, obj.choice_c, obj.choice_d]


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['username', 'email']


class ProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer()

    class Meta:
        model = Profile
        fields = ['user', 'biography', 'grade']
        depth = 1


class ProfileBiographySerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = ['biography']


class RoomSerializer(serializers.ModelSerializer):
    class Meta:
        model = Room
        fields = '__all__'


class TrackedQuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = TrackedQuestion
        fields = '__all__'
