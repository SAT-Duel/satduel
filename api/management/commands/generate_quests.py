from django.core.management.base import BaseCommand
from api.tasks import generate_user_quests

class Command(BaseCommand):
    help = 'Generate quests for all users'

    def handle(self, *args, **kwargs):
        self.stdout.write('Starting quest generation...')
        generate_user_quests()
        self.stdout.write(self.style.SUCCESS('Successfully generated quests')) 