from api.models import Game
from rest_framework import serializers

class GameCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Game
        fields = ['max_players', 'question_number', 'battle_duration', 'password']

    def validate_max_players(self, value):
        if value < 2:
            raise serializers.ValidationError("Max players must be at least 2.")
        return value

    def validate_question_number(self, value):
        if value < 1:
            raise serializers.ValidationError("Question number must be at least 1.")
        return value

    def validate_battle_duration(self, value):
        if value < 60:  # Minimum duration of 1 minute
            raise serializers.ValidationError("Battle duration must be at least 60 seconds.")
        return value


class GameLightSerializer(serializers.ModelSerializer):
    class Meta:
        model = Game
        fields = ['id', 'host', 'max_players', 'players', 'status', 'battle_duration', 'question_number', 'has_password']  # Include only essential fields
        depth = 1  # Use depth=1 to include related user info for host and players, kept light