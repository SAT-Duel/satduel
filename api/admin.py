from django.contrib import admin

from api.models import Question, Profile, Room, TrackedQuestion, FriendRequest, UserStatistics, \
    PowerSprintStatistics, SurvivalStatistics, Tournament, TournamentParticipation, TournamentQuestion, Ranking, \
    Pet, House, Area, Game, GameQuestion, PersonalizedQuest, QuestTemplate

# Register your models here.
admin.site.register(Question)

@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'role', 'grade']
    list_filter = ['role', 'grade']
    search_fields = ['user__username']

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
admin.site.register(PersonalizedQuest)
admin.site.register(QuestTemplate)
