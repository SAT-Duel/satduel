from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount

from api.models import Question, Profile, Room, TrackedQuestion, DuelEmote, FriendRequest, UserStatistics, \
    PowerSprintStatistics, SurvivalStatistics, Tournament, TournamentParticipation, TournamentQuestion, Ranking, \
    Pet, Game, GameQuestion, PracticeActiveQuestion, PracticeAttempt, PracticeStats, PracticeTypeStats


# ---------------------------------------------------------------------------
# Rich user view: email verification + auth method at a glance
# ---------------------------------------------------------------------------

class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    fields = [
        'role', 'grade', 'country', 'elo_rating', 'is_bot',
        'avatar', 'avatar_icon', 'is_premium', 'premium_until', 'stripe_customer_id', 'stripe_subscription_id',
    ]
    extra = 0


class EmailAddressInline(admin.TabularInline):
    model = EmailAddress
    fields = ['email', 'verified', 'primary']
    extra = 0


class SocialAccountInline(admin.TabularInline):
    model = SocialAccount
    fields = ['provider', 'uid', 'date_joined']
    readonly_fields = ['provider', 'uid', 'date_joined']
    extra = 0


class UserAdmin(BaseUserAdmin):
    inlines = [ProfileInline, EmailAddressInline, SocialAccountInline]
    list_display = [
        'username', 'email', 'first_name', 'last_name',
        'email_verified', 'auth_method', 'date_joined', 'last_login', 'is_staff',
    ]
    list_filter = BaseUserAdmin.list_filter + ('date_joined',)
    ordering = ['-date_joined']

    @admin.display(boolean=True, description='Email verified')
    def email_verified(self, obj):
        return any(ea.verified for ea in obj.emailaddress_set.all())

    @admin.display(description='Login via')
    def auth_method(self, obj):
        providers = [sa.provider for sa in obj.socialaccount_set.all()]
        if not obj.has_usable_password():
            return ', '.join(providers) or 'social'
        return 'password' + (f' + {", ".join(providers)}' if providers else '')

    def get_queryset(self, request):
        # Prefetch to keep the changelist from doing N queries per row.
        return super().get_queryset(request).prefetch_related(
            'emailaddress_set', 'socialaccount_set',
        )


admin.site.unregister(User)
admin.site.register(User, UserAdmin)


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ['id', 'question_type', 'difficulty', 'answer', 'sp_elo_rating']
    list_filter = ['question_type', 'difficulty']
    search_fields = ['question']


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = [
        'user', 'role', 'grade', 'avatar', 'avatar_icon', 'elo_rating', 'is_bot',
        'is_premium', 'premium_until', 'stripe_customer_id', 'stripe_subscription_id',
    ]
    list_filter = ['role', 'grade', 'is_premium', 'is_bot']
    search_fields = ['user__username', 'user__email', 'stripe_customer_id', 'stripe_subscription_id']


@admin.register(PracticeAttempt)
class PracticeAttemptAdmin(admin.ModelAdmin):
    list_display = ['user', 'question', 'subject', 'correct', 'created_at']
    list_filter = ['subject', 'correct', 'created_at']
    search_fields = ['user__username']
    raw_id_fields = ['user', 'question']


@admin.register(PracticeStats)
class PracticeStatsAdmin(admin.ModelAdmin):
    list_display = ['user', 'subject', 'elo', 'answered', 'correct']
    list_filter = ['subject']
    search_fields = ['user__username']
    raw_id_fields = ['user']


@admin.register(PracticeTypeStats)
class PracticeTypeStatsAdmin(admin.ModelAdmin):
    list_display = ['user', 'question_type', 'solved', 'correct']
    list_filter = ['question_type']
    search_fields = ['user__username', 'question_type']
    raw_id_fields = ['user']


@admin.register(PracticeActiveQuestion)
class PracticeActiveQuestionAdmin(admin.ModelAdmin):
    list_display = ['user', 'lane', 'question']
    search_fields = ['user__username', 'lane']
    raw_id_fields = ['user', 'question']


admin.site.register(Room)
admin.site.register(TrackedQuestion)
admin.site.register(DuelEmote)
admin.site.register(FriendRequest)
admin.site.register(UserStatistics)
admin.site.register(PowerSprintStatistics)
admin.site.register(SurvivalStatistics)
admin.site.register(Tournament)
admin.site.register(TournamentParticipation)
admin.site.register(TournamentQuestion)
admin.site.register(Ranking)
admin.site.register(Pet)
admin.site.register(Game)
admin.site.register(GameQuestion)
