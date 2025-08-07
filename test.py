import time
from google import genai
from google.genai import types

client = genai.Client(api_key=open('api.txt', 'r').read())


def ai_text(p, think=-1):
    """Generate text using Gemini API with retry logic."""
    try:
        if think > 1:
            return client.models.generate_content(
                model="gemini-2.5-flash",
                contents=p,
                config=types.GenerateContentConfig(
                    thinking_config=types.ThinkingConfig(thinking_budget=think)
                    # Turn off thinking:
                    # thinking_config=types.ThinkingConfig(thinking_budget=0)
                    # Turn on dynamic thinking:
                    # thinking_config=types.ThinkingConfig(thinking_budget=-1)
                ),
            ).text
        else:
            return client.models.generate_content(contents=p,model="gemini-2.5-flash").text
    except Exception as e:
        print(f'Error in ai_text: {e}')
        time.sleep(5)
        return ai_text(p, think)
    
prompt = """
Generate a comprehensive SVG diagram of Weak Acid + Strong Base Titration Graph. Respond only with code in an svg code block, do not use comments within your code in order to save space. Include ample padding so that no text overlaps with anything. If the diagram include a graph, include all of the important points. Use the foreignObject tag when creating text boxes so that you can use text wrapping, and to make sure no text overlaps with any object on the screen, and by making sure that the bounds(x,y,y+length,x+width) of the divs inside foreign Objects do not overlaps. In general, try not to make too many text boxes within close proximity of each other.
"""
print(ai_text(prompt, think=3000))  # Example usage, can be removed in production