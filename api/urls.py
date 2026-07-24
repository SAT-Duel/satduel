from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView
from api.views.user_views import CustomRegisterView
from api.views import views, user_views, tournaments_views, shop_views, duel_views, profile_views
from api.views import trainer_views as trainer_view
from api.views import onlineuser_views, auth_views, practice_views, billing_views, generation_views
from api.views import marketing_views
from api.views import party_views

urlpatterns = [
    path('questions/', views.get_random_questions, name='get_random_questions'),
    path('get_question/<int:question_id>', views.get_question, name='get_question'),
    path('check_answer/', views.check_answer, name='check_answer'),
    path('get_answer/', views.get_answer, name='get_answer'),
    path('filter_questions/', views.list_questions, name='list_questions'),
    path('edit_question/<int:question_id>', views.edit_question, name='edit_question'),
    path('create_question/', views.create_question, name='create_question'),
    path('question_reports/', views.create_question_report, name='create_question_report'),
    path('admin/question_reports/', views.list_question_reports, name='list_question_reports'),
    path('admin/question_reports/<int:report_id>/', views.delete_question_report, name='delete_question_report'),

    path('profile/', profile_views.profile_view, name='profile'),
    path('account/delete/', auth_views.delete_account, name='account_delete'),
    path('account/username/', profile_views.update_username, name='account_username'),
    path('profile/update_streak/', profile_views.update_streak, name='update_streak'),
    path('profile/search/', profile_views.search_users, name='search_users'),
    path('profile/send_friend_request/', profile_views.send_friend_request, name='send_friend_request'),
    path('profile/respond_friend_request/<int:request_id>/', profile_views.respond_friend_request,
         name='respond_friend_request'),
    path('profile/friend_requests/', profile_views.list_friend_requests, name='list_friend_requests'),
    path('profile/friends/', profile_views.list_friends, name='list_friends'),
    path('profile/view_profile/<int:user_id>/', profile_views.view_profile, name='view_profile'),
    path('infinite_questions_profile/', profile_views.infinite_questions_profile_view, name='infinite_questions_profile'),
    path('leaderboard/', profile_views.leaderboard_view, name='leaderboard'),

    path('login/', user_views.login_view, name='login'),
    path('logout/', user_views.logout_view, name='logout'),
    path('register/', CustomRegisterView.as_view(), name='register'),

    # Unified auth (single-request JWT login + Google + profile completion)
    path('auth/login/', auth_views.login_view, name='auth_login'),
    path('auth/google/', auth_views.google_login, name='auth_google'),
    path('auth/sat_exam_dates/', auth_views.sat_exam_dates, name='sat_exam_dates'),
    path('auth/complete_profile/', auth_views.complete_profile, name='auth_complete_profile'),
    path('auth/set_password/', auth_views.set_password, name='auth_set_password'),

    path('match/', duel_views.match, name='match'),
    path('match/questions/', duel_views.get_match_questions, name='get_match_questions'),
    path('match/update/', duel_views.update_match_question, name='update_match_question'),
    path('match/status/', duel_views.get_room_status, name='get_room_status'),
    path('match/get_opponent_progress/', duel_views.get_opponent_progres, name='get_opponent_progress'),
    path('match/rejoin/', duel_views.rejoin_match, name='rejoin_match'),
    path('match/get_end_time/', duel_views.get_end_time, name='get_end_time'),
    path('match/end_match/', duel_views.end_match, name='end_match'),
    path('match/get_results/', duel_views.get_results, name='get_results'),
    path('match/cancel_match/', duel_views.cancel_match, name='cancel_match'),
    path('match/get_match_history/', duel_views.get_match_history, name='get_match_history'),
    path('match/get_match_history/<int:user_id>/', duel_views.get_match_history, name='get_match_history_with_user_id'),
    path('match/info/', duel_views.get_match_info, name='get_match_info'),
    path('match/emotes/', duel_views.duel_emotes, name='duel_emotes'),

    path('trainer/infinite_question_stats/', trainer_view.get_infinite_question_stats,
         name='get_infinite_question_stats'),

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
    path('tournaments/get_history/', tournaments_views.tournament_history, name='tournament-history'),
    path('tournaments/get_history/<int:id>/', tournaments_views.tournament_history, name='tournament-history'),
    path('tournaments/join_from_code/', tournaments_views.join_from_code, name='join-tournament-from-code'),
    path('tournaments/my_tournaments/', tournaments_views.get_my_tournaments, name='get_my_tournaments'),

    path('token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', auth_views.AccountTokenRefreshView.as_view(), name='api_token_refresh'),

    path('buy_pet/', shop_views.buy_pet, name='buy_pet'),

    # Password reset
    path('password_reset/', user_views.PasswordResetRequestView.as_view(), name='password_reset'),
    path('reset/<uidb64>/<token>/', user_views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),

    path('user_streak/', views.get_user_streak, name='user-streak'),

    path('online_users/', onlineuser_views.get_online_users, name='get_online_users'),
    path('update_online_status/', onlineuser_views.update_online_status, name='update_online_status'),
    path('remove_online_user/', onlineuser_views.remove_online_user, name='remove_online_user'),

    # Adaptive practice (quota-enforced)
    path('practice/next/', practice_views.next_question, name='practice_next'),
    path('practice/status/', practice_views.practice_status, name='practice_status'),
    path('practice/history/', practice_views.practice_history, name='practice_history'),
    path('practice/saved/', practice_views.saved_questions, name='saved_questions'),
    path('practice/saved/status/', practice_views.saved_question_status, name='saved_question_status'),
    path('practice/saved/<int:question_id>/', practice_views.unsave_question, name='unsave_question'),

    # Full-length practice tests
    path('practice_test/save/', practice_views.save_test_result, name='save_test_result'),
    path('practice_test/history/', practice_views.test_history, name='practice_test_history'),

    # Billing
    path('billing/create_checkout_session/', billing_views.create_checkout_session, name='billing_create_checkout_session'),
    path('billing/create_portal_session/', billing_views.create_portal_session, name='billing_create_portal_session'),
    path('billing/webhook/', billing_views.stripe_webhook, name='stripe_webhook'),

    path('marketing/resend_webhook/', marketing_views.resend_webhook, name='resend_webhook'),

    # Admin: AI question generation
    path('admin/generation/taxonomy/', generation_views.generation_taxonomy, name='generation_taxonomy'),
    path('admin/generation/generate/', generation_views.generation_generate, name='generation_generate'),
    path('admin/generation/import/', generation_views.generation_import, name='generation_import'),

    # Party Mode (Kahoot-style live rooms)
    path('party/create/', party_views.create_party, name='party_create'),
    path('party/join/', party_views.join_party, name='party_join'),
    path('party/<int:room_id>/state/', party_views.party_state, name='party_state'),
    path('party/<int:room_id>/start/', party_views.start_party, name='party_start'),
    path('party/<int:room_id>/answer/', party_views.answer_party_question, name='party_answer'),
    path('party/<int:room_id>/next/', party_views.next_party_question, name='party_next'),
    path('party/<int:room_id>/teams/', party_views.update_party_teams, name='party_teams'),
    path('party/<int:room_id>/wager/', party_views.place_party_wager, name='party_wager'),
    path('party/<int:room_id>/gold/answer/', party_views.gold_rush_answer, name='party_gold_answer'),
    path('party/<int:room_id>/gold/chest/', party_views.gold_rush_chest, name='party_gold_chest'),
    path('party/<int:room_id>/leave/', party_views.leave_party, name='party_leave'),

]
