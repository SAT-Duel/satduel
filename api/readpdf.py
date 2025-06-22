import re
import json
import fitz  # PyMuPDF


def condense_whitespace(text):
    # Replace multiple whitespace characters (spaces, tabs, newlines) with a single space
    return re.sub(r'\s+', ' ', text).strip()


def extract_questions(text):
    # Split the text into individual questions
    questions = re.split(r'Question ID [a-z0-9]+', text)[1:]  # Skip the first empty split

    parsed_questions = []

    for q in questions:
        question_data = {}
        question_data['fields'] = {}

        # Extract question text
        question_match = re.search(r'ID: ([a-z0-9]+)\n(.*?)\nA\.', q, re.DOTALL)
        if question_match:
            question_data['fields']['question'] = condense_whitespace(question_match.group(2).strip().replace('\n', ' '))

        # Extract choices
        choices = re.findall(r'([A-D])\.\s*(.*?)(?=\n[A-D]\.|$|ID:\s)', q, re.DOTALL)
        for letter, choice in choices:
            question_data['fields'][f'choice_{letter.lower()}'] = condense_whitespace(choice.strip().replace('\n', ' '))

        # Extract correct answer
        answer_match = re.search(r'Correct Answer: ([A-D])', q)
        if answer_match:
            question_data['fields']['answer'] = answer_match.group(1)

        # Extract explanation
        explanation_match = re.search(r'Rationale\n(.*?)\nQuestion Dif', q, re.DOTALL)
        if explanation_match:
            question_data['fields']['explanation'] = condense_whitespace(explanation_match.group(1).strip().replace('\n', ' '))

        # Extract difficulty
        difficulty_match = re.search(r'Question Difficulty: (\w+)', q)
        if difficulty_match:
            question_data['fields']['difficulty'] = condense_whitespace(difficulty_match.group(1).replace('\n', ' '))

        # Set question type (if needed)

        parsed_questions.append(question_data)

    return parsed_questions


def clean_text(text):
    # Regular expression to match the entire block from Domain to Skill, including everything up to Difficulty followed by a number.number pattern
    match = re.search(r'Domain\s*(.*?)\s*Skill\s*(.*?)\s*Difficulty', text, re.DOTALL)
    if match:
        # Extract text after "Skill" and before "Difficulty"
        extracted_text = match.group(2).strip()

        # Remove the entire block from Domain to Skill, including everything up to Difficulty
        text = text.replace(match.group(0), '')

        return text, extracted_text
    return text, None


# Extract text from PDF
pdf_file_path = 'pdfs/Inferences (Level 2).pdf'
doc = fitz.open(pdf_file_path)
text = ""
for page in doc:
    text += page.get_text()

# Clean the text to remove the Domain and Skill block
cleaned_text, skill_text = clean_text(text)
skill_text = skill_text.replace('\n', ' ')
skill_text = re.sub(r'\s+', ' ', skill_text)
cleaned_text = cleaned_text.replace('''
Assessment
SAT
Test
Reading and Writing
''', '')
print(cleaned_text)

# Output the extracted skill text if needed
if skill_text:
    print(f"Extracted Skill Text: {skill_text}")

# Parse questions
questions_data = extract_questions(cleaned_text)

# Convert difficulty to integer
difficulty_map = {'Easy': 1, 'Medium': 3, 'Hard': 5}
for q in questions_data:
    q['fields']['difficulty'] = difficulty_map.get(q['fields']['difficulty'], 1)  # Default to 1 if not found
    q['model'] = 'api.question'
    q['fields']['question_type'] = skill_text

# Convert to JSON
questions_json = json.dumps(questions_data, indent=4)

# Save to a file
with open('questions.json', 'w') as f:
    f.write(questions_json)

print("JSON data has been created and saved as 'questions.json'")
