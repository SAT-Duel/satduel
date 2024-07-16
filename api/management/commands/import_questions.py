import json
import os
from django.core.management.base import BaseCommand
from api.models import Question

class Command(BaseCommand):
    help = 'Load questions from a JSON file into the database'

    def add_arguments(self, parser):
        parser.add_argument('file_path', type=str, help='The path to the JSON file')

    def handle(self, *args, **kwargs):
        file_path = kwargs['file_path']

        if not os.path.exists(file_path):
            self.stderr.write(self.style.ERROR('File not found'))
            return

        with open(file_path, 'r', encoding='utf-8') as file:
            data = json.load(file)

            for item in data:
                fields = item.get('fields', {})
                question = fields.get('question')
                choice_a = fields.get('choice_a')
                choice_b = fields.get('choice_b')
                choice_c = fields.get('choice_c')
                choice_d = fields.get('choice_d')
                answer = fields.get('answer')
                difficulty = fields.get('difficulty')
                question_type = fields.get('question_type')
                explanation = fields.get('explanation', '')

                try:
                    if answer and len(answer) == 1 and all([question, choice_a, choice_b, choice_c, choice_d]):
                        Question.objects.create(
                            question=question,
                            choice_a=choice_a,
                            choice_b=choice_b,
                            choice_c=choice_c,
                            choice_d=choice_d,
                            answer=answer,
                            difficulty=difficulty,
                            question_type=question_type,
                            explanation=explanation
                        )
                    else:
                        self.stderr.write(self.style.WARNING(f"Invalid entry found and skipped: {item}"))
                except Exception as e:
                    self.stderr.write(self.style.ERROR(f"Error occurred while importing: {e}"))
                    return

            self.stdout.write(self.style.SUCCESS('Successfully imported questions'))
