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
    path('profile/search/', views.search_users, name='search_users'),
    path('profile/send_friend_request/', views.send_friend_request, name='send_friend_request'),
    path('profile/respond_friend_request/<int:request_id>/', views.respond_friend_request, name='respond_friend_request'),
    path('profile/friend_requests/', views.list_friend_requests, name='list_friend_requests'),
    path('profile/friends/', views.list_friends, name='list_friends'),
    path('profile/view_profile/<int:user_id>/', views.view_profile, name='view_profile'),

    path('login/', user_views.login_view, name='login'),
    path('logout/', user_views.logout_view, name='logout'),
    path('register/', user_views.register, name='register'),

    path('match/', views.match, name='match'),
    path('match/questions/', views.get_match_questions, name='get_match_questions'),
    path('match/update/', views.update_match_question, name='update_match_question'),
    path('match/status/', views.get_room_status, name='get_room_status'),
    path('match/get_opponent_progress/', views.get_opponent_progres, name='get_opponent_progress'),
    path('match/rejoin/', views.rejoin_match, name='rejoin_match'),

    path('token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

]