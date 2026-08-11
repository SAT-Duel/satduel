import json
import os
from django.core.management.base import BaseCommand, CommandError
from api.models import DEFAULT_TEST_PREP, Question, TestPrep, TestSection

class Command(BaseCommand):
    help = 'Load questions from a JSON file into the database'

    def add_arguments(self, parser):
        parser.add_argument('file_path', type=str, help='The path to the JSON file')
        parser.add_argument('--test-prep', default=DEFAULT_TEST_PREP, help='Test code, e.g. sat or act')
        parser.add_argument('--subject', help='Section code, required outside legacy SAT imports')

    def handle(self, *args, **kwargs):
        file_path = kwargs['file_path']
        test_prep = kwargs['test_prep'].lower()
        subject = (kwargs.get('subject') or '').lower()

        if not TestPrep.objects.filter(code=test_prep).exists():
            raise CommandError(f'Unknown test prep: {test_prep}')
        if subject and not TestSection.objects.filter(test_prep_id=test_prep, code=subject).exists():
            raise CommandError(f'Unknown section {subject!r} for {test_prep.upper()}')
        if test_prep != DEFAULT_TEST_PREP and not subject:
            raise CommandError('--subject is required for non-SAT question banks')

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
                source = fields.get(
                    'source',
                    Question.SOURCE_SAT_QUESTION_BANK
                    if test_prep == DEFAULT_TEST_PREP else Question.SOURCE_OFFICIAL_QUESTION_BANK,
                )

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
                            explanation=explanation,
                            source=source,
                            test_prep_id=test_prep,
                            subject=subject or 'english',
                        )
                    else:
                        self.stderr.write(self.style.WARNING(f"Invalid entry found and skipped: {item}"))
                except Exception as e:
                    self.stderr.write(self.style.ERROR(f"Error occurred while importing: {e}"))
                    return

            self.stdout.write(self.style.SUCCESS('Successfully imported questions'))
