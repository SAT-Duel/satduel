from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from .models import Class, ClassParticipation, ProblemSet
from .serializers import ClassSerializer, ProblemSetSerializer, ClassParticipationSerializer

# Create your views here.

class ClassListCreateView(generics.ListCreateAPIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = ClassSerializer

    def get_queryset(self):
        return Class.objects.filter(
            classparticipation__user=self.request.user
        ).distinct()

    def perform_create(self, serializer):
        classroom = serializer.save(teacher=self.request.user)
        ClassParticipation.objects.create(
            user=self.request.user,
            classroom=classroom,
            role='TEACHER'
        )

class JoinClassView(generics.CreateAPIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def create(self, request, *args, **kwargs):
        code = request.data.get('code')
        try:
            classroom = Class.objects.get(code=code)
            if ClassParticipation.objects.filter(user=request.user, classroom=classroom).exists():
                return Response({'detail': 'Already joined this classes'}, status=status.HTTP_400_BAD_REQUEST)
            
            ClassParticipation.objects.create(
                user=request.user,
                classroom=classroom,
                role='STUDENT'
            )
            return Response({'detail': 'Successfully joined classes'}, status=status.HTTP_201_CREATED)
        except Class.DoesNotExist:
            return Response({'detail': 'Invalid classes code'}, status=status.HTTP_404_NOT_FOUND)

class ProblemSetCreateView(generics.CreateAPIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = ProblemSetSerializer

    def perform_create(self, serializer):
        classroom = generics.get_object_or_404(Class, id=self.kwargs['class_id'], teacher=self.request.user)
        serializer.save(classroom=classroom)

class ClassDetailView(generics.RetrieveAPIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = ClassSerializer
    queryset = Class.objects.all()
