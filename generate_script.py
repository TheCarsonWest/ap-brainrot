import os
from time import sleep
import argparse
import google.generativeai as genai
from openai import OpenAI
import re
# Set OpenAI API key from environment variable
"""client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

def ai_text(p):
    try:
        return client.chat.completions.create(
            model="gpt-4.1",
            messages=[{"role": "user", "content": p}],
            temperature=0.7,
            max_tokens=1000
        ).choices[0].message.content
    except Exception as e:
        print(f'Error: {e}')
        sleep(5)
        return ai_text(p)
"""
genai.configure(api_key=open('api.txt', 'r').read())
model = genai.GenerativeModel("gemini-2.5-flash")

def ai_text(p):
    try:
        return model.generate_content(p).text
    except Exception as e:
        print(f'Error: {e}')
        sleep(5)
        return ai_text(p)
    
def construct_prompt(topic_file, character_file):
    with open('single_prompt.txt', 'r', encoding='utf-8') as f:
        prompt = f.read()
    with open(topic_file, 'r', encoding='utf-8') as f:
        topic = f.read().strip()
    with open(character_file, 'r', encoding='utf-8') as f:
        character = f.read().strip()
    prompt = prompt.replace('{{topic}}', topic)
    prompt = prompt.replace('{{character}}', character)
    return prompt

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate prompt using topic and character files.")
    parser.add_argument('--topic_file', required=True, help='Path to the topic file')
    parser.add_argument('--character_file', required=True, help='Path to the character file')
    args = parser.parse_args()

    prompt = construct_prompt(args.topic_file, args.character_file)
    output_text = ai_text(prompt)
    print(output_text)
    replace_list = {
        "  "   : " ",
        'flip' : "fuck",
        "fuckp" : "fuck",
        "bruh": "bitch",
        "heck": "hell",
        "stuff":"shit",
        "hare brain":"harebrain",
        "harebrain":"retard",
        "A P U S H" : "AP US",
        "?":".",
        "!" : "."
    } # AI Swear filter bypass

    for r in replace_list:
        escaped_r = re.escape(r)  # Escape special characters in the key
        output_text = re.sub(escaped_r, replace_list[r], output_text, flags=re.IGNORECASE)
    
    output_text += "\n Follow APUSH Brainrot for more"  # Add the follow line at the end


    # Ensure the scripts directory exists
    os.makedirs('scripts', exist_ok=True)

    # Get the base name of the topic file (without directory)
    topic_filename = os.path.basename(args.topic_file)
    # Remove extension and add .txt
    base_name = os.path.splitext(topic_filename)[0]
    output_path = os.path.join('scripts', f"{base_name}.txt")

    # Write the original processed text
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(output_text)
