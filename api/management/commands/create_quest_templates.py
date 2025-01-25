# management/commands/create_quest_templates.py
from django.core.management.base import BaseCommand
from api.models import QuestTemplate

class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        templates = [
            # Daily quests
            {
                'goal_type': 'beginner',
                'period_type': 'daily',
                'base_target': 5,
                'min_coins': 10,
                'max_coins': 15
            },
            {
                'goal_type': 'intermediate',
                'period_type': 'daily',
                'base_target': 10,
                'min_coins': 15,
                'max_coins': 20
            },
            {
                'goal_type': 'advanced',
                'period_type': 'daily',
                'base_target': 20,
                'min_coins': 20,
                'max_coins': 25
            },
            {
                'goal_type': 'expert',
                'period_type': 'daily',
                'base_target': 40,
                'min_coins': 25,
                'max_coins': 30
            },
            # Weekly quests
            {
                'goal_type': 'beginner',
                'period_type': 'weekly',
                'base_target': 40,
                'min_coins': 100,
                'max_coins': 110,
            },
            {
                'goal_type': 'intermediate',
                'period_type': 'weekly',
                'base_target': 100,
                'min_coins': 150,
                'max_coins': 160,
            },
            {
                'goal_type': 'advanced',
                'period_type': 'weekly',
                'base_target': 150,
                'min_coins': 200,
                'max_coins': 210,
            },
            {
                'goal_type': 'advanced',
                'period_type': 'weekly',
                'base_target': 250,
                'min_coins': 250,
                'max_coins': 260,
            },
            # ... add more templates
        ]
        
        for template in templates:
            QuestTemplate.objects.get_or_create(**template)