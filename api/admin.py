from django.contrib import admin

from api.models import Question, Profile, Room, TrackedQuestion

# Register your models here.
admin.site.register(Question)
admin.site.register(Profile)
admin.site.register(Room)
admin.site.register(TrackedQuestion)