from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from . import views
from . import user_views

urlpatterns = [
    path('questions/', views.get_random_questions, name='get_random_questions'),
    path('get_question/', views.get_question, name='get_question'),
    path('check_answer/', views.check_answer, name='check_answer'),
    path('get_answer/', views.get_answer, name='get_answer'),

    path('profile/', views.profile_view, name='profile'),
    path('profile/update_biography/', views.update_biography, name='update_biography'),

    path('login/', user_views.login_view, name='login'),
    path('logout/', user_views.logout_view, name='logout'),
    path('register/', user_views.register, name='register'),

    path('match/', views.match, name='match'),
    path('match/questions/', views.get_match_questions, name='get_match_questions'),
    path('match/update/', views.update_match_question, name='update_match_question'),
    path('match/status/', views.get_room_status, name='get_room_status'),
    path('match/get_opponent_progress/', views.get_opponent_progres, name='get_opponent_progress'),

    path('token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

]