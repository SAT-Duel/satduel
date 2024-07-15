from django.contrib.auth.models import User
from api.models import Question, Profile, Room, TrackedQuestion, FriendRequest
from rest_framework import serializers
from allauth.account.adapter import get_adapter
from allauth.account.utils import setup_user_email
from dj_rest_auth.registration.serializers import RegisterSerializer

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
        fields = ['id', 'username', 'email']


class ProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer()

    class Meta:
        model = Profile
        fields = ['id', 'user', 'biography', 'grade']
        depth = 1


class ProfileBiographySerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = ['id', 'biography']


class RoomSerializer(serializers.ModelSerializer):
    user1 = UserSerializer()
    user2 = UserSerializer()
    class Meta:
        model = Room
        fields = ['id', 'user1', 'user2', 'created_at', 'status', 'questions', 'winner', 'battle_start_time', 'user1_score', 'user2_score']


class TrackedQuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = TrackedQuestion
        fields = '__all__'

class TrackedQuestionResultSerializer(serializers.ModelSerializer):
    user = UserSerializer()
    class Meta:
        model = TrackedQuestion
        fields = ['id', 'user', 'question', 'status']

class FriendRequestSerializer(serializers.ModelSerializer):
    from_user = UserSerializer()
    to_user = UserSerializer()

    class Meta:
        model = FriendRequest
        fields = ['id', 'from_user', 'to_user', 'timestamp', 'status']

class CustomRegisterSerializer(RegisterSerializer):
    first_name = serializers.CharField(required=True, write_only=True)
    last_name = serializers.CharField(required=True, write_only=True)
    grade = serializers.IntegerField(required=True, write_only=True)

    def get_cleaned_data(self):
        data_dict = super().get_cleaned_data()
        data_dict['first_name'] = self.validated_data.get('first_name', '')
        data_dict['last_name'] = self.validated_data.get('last_name', '')
        data_dict['grade'] = self.validated_data.get('grade')
        print("Cleaned data:", data_dict)
        return data_dict

    def save(self, request):
        adapter = get_adapter()
        user = adapter.new_user(request)
        self.cleaned_data = self.get_cleaned_data()
        adapter.save_user(request, user, self)
        setup_user_email(request, user, [])
        user.save()
        profile = Profile.objects.create(
            user=user,
            biography='This user is lazy, he did not write anything yet',
            grade=self.cleaned_data.get('grade')
        )
        print("Created profile:", profile)
        return user

    def validate(self, data):
        print("Received data in validate:", data)
        return super().validate(data)