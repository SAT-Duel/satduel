from django.contrib import admin

from api.models import Question, Profile, Room, TrackedQuestion, FriendRequest

# Register your models here.
admin.site.register(Question)
admin.site.register(Profile)
admin.site.register(Room)
admin.site.register(TrackedQuestion)
admin.site.register(FriendRequest)