from django.urls import path
from .views import ClassListCreateView, JoinClassView, ProblemSetCreateView, ClassDetailView

urlpatterns = [
    path('', ClassListCreateView.as_view(), name='classes-list'),
    path('join/', JoinClassView.as_view(), name='join-classes'),
    path('<int:pk>/', ClassDetailView.as_view(), name='classes-detail'),
    path('<int:class_id>/problem-sets/', ProblemSetCreateView.as_view(), name='problem-set-create'),
] 