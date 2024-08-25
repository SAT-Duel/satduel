from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from django.contrib.auth import views as auth_views

from . import views
from . import user_views
from .user_views import CustomRegisterView
from . import trainer_views as trainer_view
from . import tournaments_views
from . import shop_views
from . import house_views

urlpatterns = [
    path('questions/', views.get_random_questions, name='get_random_questions'),
    path('get_question/<int:question_id>', views.get_question, name='get_question'),
    path('check_answer/', views.check_answer, name='check_answer'),
    path('get_answer/', views.get_answer, name='get_answer'),
    path('filter_questions/', views.list_questions, name='list_questions'),
    path('edit_question/<int:question_id>', views.edit_question, name='edit_question'),
    path('create_question/', views.create_question, name='create_question'),

    path('profile/', views.profile_view, name='profile'),
    path('profile/update_biography/', views.update_biography, name='update_biography'),

    path('profile/update_rankings/', views.update_ranking, name='update_ranking'),
    path('profile/update_streak/', views.update_streak, name='update_streak'),
    path('profile/search/', views.search_users, name='search_users'),
    path('profile/send_friend_request/', views.send_friend_request, name='send_friend_request'),
    path('profile/respond_friend_request/<int:request_id>/', views.respond_friend_request,
         name='respond_friend_request'),
    path('profile/friend_requests/', views.list_friend_requests, name='list_friend_requests'),
    path('profile/friends/', views.list_friends, name='list_friends'),
    path('profile/view_profile/<int:user_id>/', views.view_profile, name='view_profile'),
    path('profile/update-rating/', tournaments_views.update_rating, name='update-rating'),
    path('infinite_questions_profile/', views.infinite_questions_profile_view, name='infinite_questions_profile'),

    path('login/', user_views.login_view, name='login'),
    path('logout/', user_views.logout_view, name='logout'),
    path('register/', CustomRegisterView.as_view(), name='register'),

    path('match/', views.match, name='match'),
    path('match/questions/', views.get_match_questions, name='get_match_questions'),
    path('match/update/', views.update_match_question, name='update_match_question'),
    path('match/status/', views.get_room_status, name='get_room_status'),
    path('match/get_opponent_progress/', views.get_opponent_progres, name='get_opponent_progress'),
    path('match/rejoin/', views.rejoin_match, name='rejoin_match'),
    path('match/get_end_time/', views.get_end_time, name='get_end_time'),
    path('match/end_match/', views.end_match, name='end_match'),
    path('match/get_results/', views.get_results, name='get_results'),
    path('match/cancel_match/', views.cancel_match, name='cancel_match'),
    path('match/get_match_history/', views.get_match_history, name='get_match_history'),
    path('match/get_match_history/<int:user_id>/', views.get_match_history, name='get_match_history_with_user_id'),
    path('match/info/', views.get_match_info, name='get_match_info'),
    path('match/set_winner/', views.set_winner, name='set_winner'),
    path('match/set_score/', views.set_score, name='set_score'),

    path('trainer/infinite_question_stats/', trainer_view.get_infinite_question_stats,
         name='get_infinite_question_stats'),
    path('trainer/set_infinite_question_stats/', trainer_view.set_infinite_question_stats,
         name='set_infinite_question_stats'),
    path('trainer/power_sprint_stats/', trainer_view.get_power_sprint_stats, name='get_power_sprint_stats'),
    path('trainer/set_power_sprint_stats/', trainer_view.set_power_sprint_stats, name='set_power_sprint_stats'),
    path('trainer/survival_stats/', trainer_view.get_survival_stats, name='get_survival_stats'),
    path('trainer/set_survival_stats/', trainer_view.set_survival_stats, name='set_survival_stats'),

    path('tournaments/', tournaments_views.tournament_list, name='tournament-list'),
    path('tournaments/<int:pk>/', tournaments_views.tournament_detail, name='tournament-detail'),
    path('tournaments/<int:pk>/join/', tournaments_views.join_tournament, name='join-tournament'),
    path('tournaments/<int:pk>/get_participation_info/', tournaments_views.get_participation, name='get-participation'),
    path('tournaments/<int:pk>/questions/', tournaments_views.get_tournament_questions,
         name='get-tournament-questions'),
    path('tournaments/<int:pk>/leaderboard/', tournaments_views.tournament_leaderboard, name='tournament-leaderboard'),
    path('tournaments/<int:pk>/submit-answer/', tournaments_views.submit_answer, name='submit-answer'),
    path('tournaments/<int:pk>/finish/', tournaments_views.finish_participation, name='finish-participation'),
    path('tournaments/create/', tournaments_views.create_tournament, name='create-tournament'),
    path('tournaments/admin_create/', tournaments_views.create_tournament_admin, name='create-tournament-admin'),

    path('token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    path('buy_pet/', shop_views.buy_pet, name='buy_pet'),

    # Password reset
    path('password_reset/', user_views.PasswordResetRequestView.as_view(), name='password_reset'),
    path('reset/<uidb64>/<token>/', user_views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),

    path('csrf/', views.set_csrf_token),

    # House
    path('house/', house_views.get_house_map, name='get_house_map'),
]
