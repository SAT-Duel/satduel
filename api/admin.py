from django.contrib import admin

from api.models import Question, Profile, Room, TrackedQuestion, FriendRequest, UserStatistics, \
    PowerSprintStatistics, SurvivalStatistics, Tournament, TournamentParticipation, TournamentQuestion, Ranking, \
    Pet, House, Area, Game, GameQuestion, Quest, UserQuest

# Register your models here.
admin.site.register(Question)
admin.site.register(Profile)
admin.site.register(Room)
admin.site.register(TrackedQuestion)
admin.site.register(FriendRequest)
admin.site.register(UserStatistics)
admin.site.register(PowerSprintStatistics)
admin.site.register(SurvivalStatistics)
admin.site.register(Tournament)
admin.site.register(TournamentParticipation)
admin.site.register(TournamentQuestion)
admin.site.register(Ranking)
admin.site.register(Pet)
admin.site.register(House)
admin.site.register(Area)
admin.site.register(Game)
admin.site.register(GameQuestion)
admin.site.register(Quest)
admin.site.register(UserQuest)
