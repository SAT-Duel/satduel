import re
import json
from pdfminer.high_level import extract_text
import fitz

def extract_questions(text):
    # Split the text into individual questions
    questions = re.split(r'Question ID [a-z0-9]+', text)[1:]  # Skip the first empty split

    parsed_questions = []

    for q in questions:
        question_data = {}
        question_data['fields'] = {}
        # Extract question ID
        # id_match = re.search(r'([a-z0-9]+)', q)
        # if id_match:
        #     question_data['fields']['id'] = id_match.group(1)

        # Extract question text
        question_match = re.search(r'ID: ([a-z0-9]+)\n(.*?)\nA\.', q, re.DOTALL)
        if question_match:
            question_data['fields']['question'] = question_match.group(2).strip()

        # Extract choices
        choices = re.findall(r'([A-D])\.\s*(.*?)(?=\n[A-D]\.|$|Correct Answer)', q, re.DOTALL)
        for letter, choice in choices:
            question_data['fields'][f'choice_{letter.lower()}'] = choice.strip().replace('\n','')

        # Extract correct answer
        answer_match = re.search(r'Correct Answer: ([A-D])', q)
        if answer_match:
            question_data['fields']['answer'] = answer_match.group(1)

        # Extract difficulty


        # Extract explanation
        explanation_match = re.search(r'Rationale\n(.*?)\nQuestion Dif', q, re.DOTALL)
        if explanation_match:
            question_data['fields']['explanation'] = explanation_match.group(1).strip().replace('\n','')

        difficulty_match = re.search(r'Question Difficulty: (\w+)', q)
        if difficulty_match:
            question_data['fields']['difficulty'] = difficulty_match.group(1).replace('\n','')

        # Set question type

        parsed_questions.append(question_data)

    return parsed_questions


# Extract text from PDF
# pdf_file_path = 'test.pdf'
# text = extract_text(pdf_file_path)

pdf_file_path = 'test1.pdf'
doc = fitz.open(pdf_file_path)
text = ""
for page in doc:
    text += page.get_text()
text=text.replace('''Assessment
SAT
Test
Reading and Writing
Domain
Craft and Structure
Skill
Cross-Text
Connections
Difficulty
''', '')
print(text)

# Parse questions
questions_data = extract_questions(text)
print(questions_data)
# Convert difficulty to integer
difficulty_map = {'Easy': 1, 'Medium': 2, 'Hard': 3}
for q in questions_data:
    q['fields']['difficulty'] = difficulty_map.get(q['fields']['difficulty'], 1)  # Default to 1 if not found
    q['model'] = 'api.question'
# Convert to JSON
questions_json = json.dumps(questions_data, indent=4)

# Save to a file
with open('questions.json', 'w') as f:
    f.write(questions_json)

print("JSON data has been created and saved as 'questions.json'")