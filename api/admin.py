from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount

from api.account_deletion import delete_user_account
from api.models import Announcement, PendingRegistration, Question, QuestionReport, Profile, SATExamDate, Room, TrackedQuestion, DuelEmote, FriendRequest, UserStatistics, \
    SurvivalStatistics, Tournament, TournamentParticipation, TournamentQuestion, \
    PracticeActiveQuestion, PracticeAttempt, PracticeStats, PracticeTest, PracticeTestAttempt, PracticeTestModule, PracticeTypeStats, \
    TestPrep, TestPrepUserStats, TestSection, \
    PartyRoom, PartyPlayer


# ---------------------------------------------------------------------------
# Rich user view: email verification + auth method at a glance
# ---------------------------------------------------------------------------

class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    fields = [
        'role', 'grade', 'grade_last_promoted_year', 'country', 'active_test_prep', 'elo_rating', 'is_bot',
        'avatar', 'avatar_icon', 'is_premium', 'premium_until', 'stripe_customer_id', 'stripe_subscription_id',
        'username_finalized', 'grade_selected',
        'sat_exam_date', 'sat_exam_date_selected', 'marketing_opt_in', 'terms_accepted_at',
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

    def get_deleted_objects(self, objs, request):
        deleted, counts, _perms_needed, protected = super().get_deleted_objects(objs, request)
        # Permission to delete a User includes its cascade-owned rows. Django's
        # default preview otherwise blocks staff who lack delete permission for
        # every registered stats/profile model.
        return deleted, counts, set(), protected

    def delete_model(self, request, obj):
        delete_user_account(obj)

    def delete_queryset(self, request, queryset):
        for user in queryset:
            delete_user_account(user)


admin.site.unregister(User)
admin.site.register(User, UserAdmin)


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ['id', 'test_prep', 'subject', 'question_type', 'source', 'difficulty', 'answer', 'sp_elo_rating']
    list_filter = ['test_prep', 'subject', 'question_type', 'source', 'difficulty']
    search_fields = ['question']


@admin.register(QuestionReport)
class QuestionReportAdmin(admin.ModelAdmin):
    list_display = ['question', 'reporter', 'reason', 'created_at']
    list_filter = ['reason', 'created_at']
    search_fields = ['question__question', 'reporter__username', 'details']
    raw_id_fields = ['question', 'reporter']


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ['message', 'is_active', 'updated_at']
    readonly_fields = ['updated_at']


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = [
        'user', 'role', 'grade', 'grade_last_promoted_year', 'grade_selected', 'username_finalized', 'active_test_prep', 'avatar', 'avatar_icon', 'elo_rating', 'is_bot',
        'is_premium', 'premium_until', 'stripe_customer_id', 'stripe_subscription_id',
        'marketing_opt_in',
    ]
    list_filter = [
        'role', 'grade', 'grade_selected', 'username_finalized', 'active_test_prep',
        'is_premium', 'is_bot', 'marketing_opt_in',
    ]
    search_fields = ['user__username', 'user__email', 'stripe_customer_id', 'stripe_subscription_id']


@admin.register(PendingRegistration)
class PendingRegistrationAdmin(admin.ModelAdmin):
    list_display = ['email', 'grade', 'email_sent_at', 'created_at', 'updated_at']
    search_fields = ['email']
    readonly_fields = ['verification_token', 'terms_accepted_at', 'email_sent_at', 'created_at', 'updated_at']
    fields = [
        'email', 'grade', 'verification_token', 'terms_accepted_at',
        'next_path', 'email_sent_at', 'created_at', 'updated_at',
    ]


@admin.register(SATExamDate)
class SATExamDateAdmin(admin.ModelAdmin):
    list_display = ['date', 'active']
    list_editable = ['active']
    list_filter = ['active']
    ordering = ['date']


@admin.register(PracticeAttempt)
class PracticeAttemptAdmin(admin.ModelAdmin):
    list_display = ['user', 'test_prep', 'question', 'subject', 'correct', 'created_at']
    list_filter = ['test_prep', 'subject', 'correct', 'created_at']
    search_fields = ['user__username']
    raw_id_fields = ['user', 'question']


@admin.register(PracticeTestModule)
class PracticeTestModuleAdmin(admin.ModelAdmin):
    list_display = ['name', 'test_prep', 'subject', 'route', 'question_count', 'created_by', 'created_at']
    list_filter = ['test_prep', 'subject', 'route', 'created_at']
    search_fields = ['name', 'created_by__username']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(PracticeTest)
class PracticeTestAdmin(admin.ModelAdmin):
    list_display = ['name', 'test_prep', 'premium_only', 'active', 'created_by', 'created_at']
    list_filter = ['test_prep', 'premium_only', 'active', 'created_at']
    search_fields = ['name', 'created_by__username']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(PracticeTestAttempt)
class PracticeTestAttemptAdmin(admin.ModelAdmin):
    list_display = [
        'user', 'practice_test', 'status', 'total_score',
        'contributes_to_calibration', 'created_at', 'completed_at',
    ]
    list_filter = ['status', 'contributes_to_calibration', 'practice_test']
    search_fields = ['user__username', 'practice_test__name']
    raw_id_fields = ['user', 'practice_test']
    readonly_fields = ['created_at', 'updated_at', 'completed_at']


@admin.register(PracticeStats)
class PracticeStatsAdmin(admin.ModelAdmin):
    list_display = ['user', 'test_prep', 'subject', 'elo', 'answered', 'correct']
    list_filter = ['test_prep', 'subject']
    search_fields = ['user__username']
    raw_id_fields = ['user']


@admin.register(PracticeTypeStats)
class PracticeTypeStatsAdmin(admin.ModelAdmin):
    list_display = ['user', 'test_prep', 'subject', 'question_type', 'solved', 'correct']
    list_filter = ['test_prep', 'subject', 'question_type']
    search_fields = ['user__username', 'question_type']
    raw_id_fields = ['user']


@admin.register(PracticeActiveQuestion)
class PracticeActiveQuestionAdmin(admin.ModelAdmin):
    list_display = ['user', 'test_prep', 'lane', 'question']
    search_fields = ['user__username', 'lane']
    raw_id_fields = ['user', 'question']


admin.site.register(Room)
admin.site.register(TrackedQuestion)
admin.site.register(DuelEmote)
admin.site.register(FriendRequest)
admin.site.register(UserStatistics)
admin.site.register(SurvivalStatistics)
admin.site.register(Tournament)
admin.site.register(TournamentParticipation)
admin.site.register(TournamentQuestion)


@admin.register(TestPrep)
class TestPrepAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'active', 'display_order']
    list_editable = ['active', 'display_order']


@admin.register(TestSection)
class TestSectionAdmin(admin.ModelAdmin):
    list_display = ['test_prep', 'code', 'name', 'active', 'display_order']
    list_filter = ['test_prep', 'active']
    list_editable = ['active', 'display_order']


@admin.register(TestPrepUserStats)
class TestPrepUserStatsAdmin(admin.ModelAdmin):
    list_display = ['user', 'test_prep', 'duel_elo', 'max_streak']
    list_filter = ['test_prep']
    search_fields = ['user__username']
    raw_id_fields = ['user']


class PartyPlayerInline(admin.TabularInline):
    model = PartyPlayer
    fields = ['user', 'score', 'last_seen', 'answers']
    readonly_fields = ['last_seen']
    extra = 0


@admin.register(PartyRoom)
class PartyRoomAdmin(admin.ModelAdmin):
    list_display = ['code', 'host', 'status', 'subject', 'difficulty',
                    'num_questions', 'player_count', 'created_at']
    list_filter = ['status', 'subject', 'difficulty', 'created_at']
    search_fields = ['code', 'host__username']
    ordering = ['-created_at']
    inlines = [PartyPlayerInline]

    @admin.display(description='Players')
    def player_count(self, obj):
        return obj.players.count()


@admin.register(PartyPlayer)
class PartyPlayerAdmin(admin.ModelAdmin):
    list_display = ['user', 'room', 'score', 'last_seen']
    search_fields = ['user__username', 'room__code']
    ordering = ['-id']
