from rest_framework import serializers
from .models import Class, ClassParticipation, ProblemSet
from api.models import Question

class ClassSerializer(serializers.ModelSerializer):
    teacher = serializers.StringRelatedField(read_only=True)
    
    class Meta:
        model = Class
        fields = ['id', 'name', 'description', 'code', 'teacher', 'max_students', 'created_at']
        extra_kwargs = {
            'code': {'read_only': True},
            'max_students': {'required': False}
        }

class ProblemSetSerializer(serializers.ModelSerializer):
    questions = serializers.PrimaryKeyRelatedField(queryset=Question.objects.all(), many=True)
    
    class Meta:
        model = ProblemSet
        fields = ['id', 'title', 'description', 'questions', 'due_date', 'created_at']

class ClassParticipationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClassParticipation
        fields = ['user', 'classroom', 'role', 'joined_at'] 