# from django.test import TestCase
#
# # Create your tests here.
# from api.models import Question
#
# import re
#
#
# # Function to extract fields from the given text block
# def extract_fields(text_block):
#     # Regex patterns for each field
#     question_pattern = re.compile(r'"question": "(.*?)"')
#     choices_pattern = re.compile(r'"choices": {.*?"A": "(.*?)",.*?"B": "(.*?)",.*?"C": "(.*?)",.*?"D": "(.*?)"}',
#                                  re.DOTALL)
#     answer_pattern = re.compile(r'"correct_answer": "(.*?)"')
#     explanation_pattern = re.compile(r'"explanation": "(.*?)"')
#     domain_pattern = re.compile(r'"domain": "(.*?)"')
#
#     # Extracting the fields using regex
#     question = question_pattern.search(text_block).group(1)
#     choices = choices_pattern.search(text_block).groups()
#     answer = answer_pattern.search(text_block).group(1)
#     explanation = explanation_pattern.search(text_block).group(1)
#     domain = domain_pattern.search(text_block).group(1)
#
#     return question, choices, answer, explanation, domain
#
#
# # Read the entire text file
# with open('dsklfjsd', 'r') as file:
#     content = file.read()
#
# # Split the content into individual questions
# question_blocks = re.findall(r'{\s*"id".*?}', content, re.DOTALL)
#
# # Iterate through each question block and create Question objects
# for i, block in enumerate(question_blocks):
#     # Extract fields from the block
#     q, choices, e, h, g = extract_fields(block)
#     a, b, c, d = choices
#
#     # Assuming difficulty is assigned randomly or set to a default value
#     f = 1  # or any other logic to determine difficulty
#
#     # Create the Question object
#     Question.objects.create(
#         question=q,
#         choice_a=a,
#         choice_b=b,
#         choice_c=c,
#         choice_d=d,
#         answer=e,
#         difficulty=f,
#         question_type=g,
#         explanation=h
#     )

import json
from api.models import Question  # Replace `your_app` with the actual name of your Django app
import sqlite3
import os
import django
import json

# Set up Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'satduel.settings')
django.setup()

def import_questions_from_json(file_path):
    conn = sqlite3.connect('../db.sqlite3')  # Replace with your actual SQLite DB file path
    cursor = conn.cursor()
    with open(file_path, 'r') as f:
        data = json.load(f)

        for subject, questions in data.items():
            for question_data in questions:
                # Extract relevant fields
                question_text = question_data['question']['question']
                choice_a = question_data['question']['choices']['A']
                choice_b = question_data['question']['choices']['B']
                choice_c = question_data['question']['choices']['C']
                choice_d = question_data['question']['choices']['D']
                correct_answer = question_data['question']['correct_answer']
                explanation = question_data['question']['explanation']

                # Create Question object
                question_obj = Question(
                    question=question_text,
                    choice_a=choice_a,
                    choice_b=choice_b,
                    choice_c=choice_c,
                    choice_d=choice_d,
                    answer=correct_answer,
                    difficulty=3,  # Set difficulty level as needed
                    question_type=subject,  # Assign subject as question type
                    explanation=explanation
                )
                question_obj.save()

        conn.commit()
        conn.close()


# Usage example
if __name__ == "__main__":
    file_path = 'database.json'
    import_questions_from_json(file_path)
