from django.contrib.auth.models import User
from api.models import Question, Profile, Room, TrackedQuestion, FriendRequest, InfiniteQuestionStatistics, \
    PowerSprintStatistics, SurvivalStatistics, Tournament, TournamentParticipation, TournamentQuestion
from rest_framework import serializers
from allauth.account.adapter import get_adapter
from allauth.account.utils import setup_user_email
from dj_rest_auth.registration.serializers import RegisterSerializer


class QuestionSerializer(serializers.ModelSerializer):
    choices = serializers.SerializerMethodField()

    class Meta:
        model = Question
        fields = ['id', 'question', 'choices', 'difficulty', 'question_type']

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
        fields = ['id', 'user', 'biography', 'grade', 'max_streak', 'elo_rating', 'country']
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
        fields = ['id', 'user1', 'user2', 'created_at', 'status', 'questions', 'winner', 'battle_start_time',
                  'user1_score', 'user2_score']


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


class InfiniteQuestionStatisticsSerializer(serializers.ModelSerializer):
    class Meta:
        model = InfiniteQuestionStatistics
        fields = '__all__'


class PowerSprintStatisticsSerializer(serializers.ModelSerializer):
    class Meta:
        model = PowerSprintStatistics
        fields = '__all__'


class SurvivalStatisticsSerializer(serializers.ModelSerializer):
    class Meta:
        model = SurvivalStatistics
        fields = '__all__'


class CustomRegisterSerializer(RegisterSerializer):
    first_name = serializers.CharField(required=True, write_only=True)
    last_name = serializers.CharField(required=True, write_only=True)
    grade = serializers.IntegerField(required=True, write_only=True)

    def get_cleaned_data(self):
        data_dict = super().get_cleaned_data()
        data_dict['first_name'] = self.validated_data.get('first_name', '')
        data_dict['last_name'] = self.validated_data.get('last_name', '')
        data_dict['grade'] = self.validated_data.get('grade')
        return data_dict

    def save(self, request):
        adapter = get_adapter()
        user = adapter.new_user(request)
        self.cleaned_data = self.get_cleaned_data()
        adapter.save_user(request, user, self)
        setup_user_email(request, user, [])
        user.save()
        Profile.objects.create(
            user=user,
            biography='This user is lazy, he did not write anything yet',
            grade=self.cleaned_data.get('grade')
        )
        return user

    def validate(self, data):
        print("Received data in validate:", data)
        return super().validate(data)


class TournamentSerializer(serializers.ModelSerializer):
    participantNumber = serializers.IntegerField(read_only=True)
    questionNumber = serializers.IntegerField(read_only=True)

    class Meta:
        model = Tournament
        fields = ['id', 'name', 'description', 'duration', 'start_time', 'end_time', 'participantNumber', 'questionNumber']


class TournamentParticipationSerializer(serializers.ModelSerializer):
    tournament = TournamentSerializer()

    class Meta:
        model = TournamentParticipation
        fields = ['id', 'user', 'tournament', 'start_time', 'end_time', 'score', 'last_correct_submission', 'status']


class TournamentQuestionSerializer(serializers.ModelSerializer):
    question = QuestionSerializer()

    class Meta:
        model = TournamentQuestion
        fields = ['id', 'participation', 'question', 'status', 'time_taken']


class TPSubmitAnswerSerializer(serializers.ModelSerializer):
    tournament_questions = serializers.SerializerMethodField()
    user = UserSerializer()
    class Meta:
        model = TournamentParticipation
        fields = ['id', 'user', 'score', 'last_correct_submission', 'tournament_questions']

    def get_tournament_questions(self, obj):
        # Retrieve and order the questions by ID
        questions = obj.tournamentquestion_set.all().order_by('id')
        return TournamentQuestionSerializer(questions, many=True).data
