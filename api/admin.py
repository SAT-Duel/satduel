from django.contrib import admin

from api.models import Question, Profile, Room, TrackedQuestion, FriendRequest, InfiniteQuestionStatistics, \
    PowerSprintStatistics, SurvivalStatistics, Tournament, TournamentParticipation, TournamentAnswer

# Register your models here.
admin.site.register(Question)
admin.site.register(Profile)
admin.site.register(Room)
admin.site.register(TrackedQuestion)
admin.site.register(FriendRequest)
admin.site.register(InfiniteQuestionStatistics)
admin.site.register(PowerSprintStatistics)
admin.site.register(SurvivalStatistics)
admin.site.register(Tournament)
admin.site.register(TournamentParticipation)
admin.site.register(TournamentAnswer)
