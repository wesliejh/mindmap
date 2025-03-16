import json
import logging
import os
import re
from textwrap import dedent
from datetime import datetime
import gradio as gr
import ollama
import requests

# Constants
OUTPUT_DIR = os.path.join(os.getcwd(), "mindmap_output")
DOWNLOADS_DIR = os.path.expanduser("~/Downloads")
CREDENTIALS_FILE = "credentials.txt"

# This is the template to produce the mindmap using markmap
HTML_TEMPLATE = dedent("""\
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="X-UA-Compatible" content="ie=edge">
<title>Markmap</title>
<style>
* {{
  margin: 0;
  padding: 0;
}}
#mindmap {{
  display: block;
  width: 100vw;
  height: 100vh;
}}
</style>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/markmap-toolbar@0.18.10/dist/style.css">
</head>
<body>
<svg id="mindmap" class="markmap mindmap"></svg>
<script src="https://cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/markmap-view@0.18.10/dist/browser/index.js"></script>
<script src="https://cdn.jsdelivr.net/npm/markmap-toolbar@0.18.10/dist/index.js"></script>
<script>
(() => {{
  setTimeout(() => {{
    const {{markmap: x, mm: K}} = window;
    const toolbar = new x.Toolbar();
    toolbar.attach(K);
    const toolbarElement = toolbar.render();
    toolbarElement.setAttribute("style", "position:absolute;bottom:20px;right:20px");
    document.body.append(toolbarElement);
  }});
}})();
</script>
<script>
((b, L, T, D) => {{
  const H = b();
  window.mm = H.Markmap.create("svg#mindmap", (L || H.deriveOptions)(D), T);
}})(() => window.markmap, null, {0});
</script>
</body>
</html>
""")

# Progress HTML
PROGRESS_HTML = dedent("""\
<div style="display: flex; justify-content: center; align-items: center; height: 100px;">
    <div style="border: 8px solid #f3f3f3; border-top: 8px solid #3498db; border-radius: 50%; width: 50px; height: 50px; animation: spin 1s linear infinite;"></div>
</div>
<style>
@keyframes spin {
    0% { transform: rotate(0deg); }
    100% { transform: rotate(360deg); }
}
</style>
""")

MINDMAP_PROMPT_TEMPLATE = dedent("""\
Context: Generate a sample PlantUML mindmap based on the provided question and context above. 
Only include context relevant to the question to produce the mindmap, but be as detailed as possible. 

Use the template like this:
@startmindmap
* Title
** Item A
*** Item B
**** Item C
*** Item D
@endmindmap
""")

SYSTEM_PROMPT = dedent("""\
You are an AI assistant that generates structured mindmaps in PlantUML format.
Your response MUST be a valid PlantUML mindmap starting with '@startmindmap' and ending with '@endmindmap'.
Use proper indentation for hierarchy. Do not include ANY text outside the PlantUML syntax.
""")

# Setup
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)
logger.debug(f"Output directory: {OUTPUT_DIR}")

# Utility Functions
def read_credentials(file_path=CREDENTIALS_FILE):
    """Read API keys and models from credentials.txt, aggregating multiple models."""
    credentials = {
        "openai": {"api_key": "", "models": []},
        "anthropic": {"api_key": "", "models": []},
        "ollama": {"api_key": "", "models": []}
    }
    try:
        if not os.path.exists(file_path):
            logger.error(f"Credentials file {file_path} not found.")
            return credentials
        with open(file_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    key, value = line.split("=", 1)
                    provider, setting = key.strip().split("_", 1)
                    if provider in credentials:
                        if setting == "api_key":
                            credentials[provider]["api_key"] = value.strip()
                        elif setting == "model":
                            credentials[provider]["models"].append(value.strip())
        logger.info(f"Credentials loaded from {file_path}")
        for provider, creds in credentials.items():
            logger.debug(f"{provider}: models={creds['models']}, api_key={'***' if creds['api_key'] else 'not set'}")
    except Exception as e:
        logger.error(f"Error loading credentials: {e}")
    return credentials

CREDENTIALS = read_credentials()

# Conversion Functions
def convert_uml_to_markdown(plantuml_text: str) -> str:
    """Convert PlantUML to Markdown."""
    if not isinstance(plantuml_text, str) or not plantuml_text.strip():
        logger.error(f"Invalid input: {plantuml_text}")
        return ""
    match = re.search(r'@startmindmap(.*?)@endmindmap', plantuml_text, re.DOTALL)
    if not match:
        logger.warning("No valid mindmap format found")
        return ""
    lines = match.group(1).strip().split('\n')
    markdown_lines = []
    for line in lines:
        if not line.strip() or line.strip().startswith("'"):
            continue
        match = re.search(r'^(\s*[*+\-]+\s+)(.*)', line)
        if match:
            level = match.group(1).count('*') + match.group(1).count('+') + match.group(1).count('-')
            content = match.group(2).strip()
            markdown_lines.append('#' * level + ' ' + content)
    return '\n'.join(markdown_lines)

def create_node(content, tag="h1", line_num=1):
    """Helper function to create a node with the right structure"""
    return {
        "content": content,
        "children": [],
        "payload": {"tag": tag, "lines": f"{line_num},{line_num+1}"}
    }

def markdown_to_markmap_json(markdown: str) -> dict:
    """Convert Markdown to Markmap JSON format with correct hierarchy."""
    if not markdown.strip():
        return {"content": "", "children": [], "payload": {"tag": "h1", "lines": "1,2"}, "colorFreezeLevel": 2}
    
    lines = markdown.strip().split('\n')
    if not lines:
        return {"content": "", "children": [], "payload": {"tag": "h1", "lines": "1,2"}, "colorFreezeLevel": 2}
    
    nodes_by_level = {}
    
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
            
        level = 0
        for char in line:
            if char == '#':
                level += 1
            else:
                break
                
        if level == 0:
            continue
            
        content = line[level:].strip()
        
        node = create_node(content, f"h{level}", i + 1)
        
        nodes_by_level[level] = node
        
        if level > 1 and level - 1 in nodes_by_level:
            parent = nodes_by_level[level - 1]
            parent["children"].append(node)
    
    # Get the root node (h1)
    if 1 in nodes_by_level:
        root = nodes_by_level[1]
        root["colorFreezeLevel"] = 2
        return root
    else:
        return {"content": "Mindmap", "children": [], "payload": {"tag": "h1", "lines": "1,2"}, "colorFreezeLevel": 2}

# API Interaction Functions
def get_ollama_response(content: str, model: str) -> str:
    """Interact with Ollama API (no API key required)."""
    try:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Generate a PlantUML mindmap based on this content:\n\n{content}\n\n{MINDMAP_PROMPT_TEMPLATE}"}
        ]
        response = ollama.chat(model=model, messages=messages)
        return response["message"]["content"]
    except Exception as e:
        logger.error(f"Ollama error: {e}")
        raise

def get_anthropic_response(content: str, model: str, api_key: str) -> str:
    """Interact with Anthropic API using provided API key."""
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01"
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": f"Generate a PlantUML mindmap based on this content:\n\n{content}\n\n{MINDMAP_PROMPT_TEMPLATE}"}],
        "system": SYSTEM_PROMPT,
        "max_tokens": 4000
    }
    try:
        response = requests.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload)
        response.raise_for_status()
        return response.json()["content"][0]["text"]
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP Error: {e.response.status_code} - {e.response.text}")
        raise Exception(f"Anthropic API error: {e.response.status_code} - {e.response.text}")
    except Exception as e:
        logger.error(f"Anthropic API error: {e}")
        raise

def get_openai_response(content: str, model: str, api_key: str) -> str:
    """Interact with OpenAI API using provided API key."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Generate a PlantUML mindmap based on this content:\n\n{content}\n\n{MINDMAP_PROMPT_TEMPLATE}"}
        ],
        "temperature": 0.7
    }
    try:
        response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"OpenAI API error: {e}")
        raise

# Generate Mindmap Function
def generate_mindmap(content: str, model_choice: str):
    """Generate an interactive HTML file with Markmap and toolbar."""
    logger.info("Starting mindmap generation")
    yield None, PROGRESS_HTML, None, "Generating mindmap..."
    
    try:
        if not content.strip():
            yield None, None, None, "Please enter some content to convert into a mindmap."
            return
        
        provider, model = model_choice.split(":", 1)
        if provider not in CREDENTIALS:
            yield None, None, None, f"Error: Unknown provider '{provider}'"
            return
        
        api_key = CREDENTIALS[provider]["api_key"]
        available_models = CREDENTIALS[provider]["models"]
        
        if not available_models:
            yield None, None, None, f"Error: No models specified for {provider} in credentials.txt"
            return
        if model not in available_models:
            yield None, None, None, f"Error: Model '{model}' not found for {provider} in credentials.txt"
            return
        
        if provider == "openai" and not api_key:
            yield None, None, None, "Error: OpenAI API key not provided in credentials.txt"
            return
        elif provider == "anthropic" and not api_key:
            yield None, None, None, "Error: Anthropic API key not provided in credentials.txt"
            return
        
        plantuml_text = {
            "openai": lambda c, m: get_openai_response(c, m, api_key),
            "anthropic": lambda c, m: get_anthropic_response(c, m, api_key),
            "ollama": get_ollama_response
        }[provider](content, model)
        
        # Extract PlantUML content
        match = re.search(r'@startmindmap(.*?)@endmindmap', plantuml_text, re.DOTALL)
        if not match:
            yield None, None, None, "Error: Could not extract valid mindmap content from the API response."
            return
            
        plantuml_text = "@startmindmap" + match.group(1) + "@endmindmap"
        logger.debug(f"PlantUML Text: {plantuml_text}")
        
        markdown = convert_uml_to_markdown(plantuml_text)
        logger.debug(f"Markdown: {markdown}")
        if not markdown.strip():
            yield None, None, None, "Error: Could not convert content to mindmap format."
            return
        
        markmap_json = markdown_to_markmap_json(markdown)
        logger.debug(f"Generated JSON: {json.dumps(markmap_json)}")
        
        # Generate HTML content with embedded Markmap data
        html_content = HTML_TEMPLATE.format(json.dumps(markmap_json))
        
        # Create a timestamp for the filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"mindmap_{timestamp}.html"
        
        # Save the HTML content to a file for download
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        file_path = os.path.join(OUTPUT_DIR, filename)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        
        # Create an iframe with srcdoc to embed the HTML content directly
        safe_html_content = html_content.replace("'", "&#39;")
        
        iframe_html = f"""
        <iframe id="mindmap-iframe" srcdoc='{safe_html_content}' style="width: 100%; height: 90vh; border: none; display: block; box-sizing: border-box; background-color: white;"></iframe>
        """
        
        yield iframe_html, None, file_path, ""
        
    except Exception as e:
        logger.error(f"Error generating mindmap: {e}", exc_info=True)
        yield None, None, None, f"Error: {str(e)}"

# This is pulled from the credentials.txt and will pull all models into the dropdown selection menu
def get_model_choices():
    """Aggregate all provider-model combinations from credentials."""
    choices = []
    for provider, creds in CREDENTIALS.items():
        for model in creds["models"]:
            choices.append(f"{provider}:{model}")
    return choices

# Gradio Interface
with gr.Blocks(title="Mindmap Generator", css="footer {visibility: hidden}") as demo:
    gr.Markdown("# Interactive Mindmap Generator")
    
    with gr.Row():
        with gr.Column(scale=2, min_width=400):
            with gr.Group():
                input_text = gr.Textbox(label="Paste your content here", lines=10)
                model_dropdown = gr.Dropdown(
                    choices=get_model_choices(),
                    label="Select Model",
                    value=f"ollama:{CREDENTIALS['ollama']['models'][0]}" if CREDENTIALS["ollama"]["models"] else None,
                    allow_custom_value=False
                )
                convert_btn = gr.Button("Generate Mindmap", variant="primary")
        
        with gr.Column(scale=3):
            with gr.Group():
                mindmap_output = gr.HTML(label="Mindmap")
                progress_output = gr.HTML(label="Progress")
                download_output = gr.File(label="Download HTML File", visible=True)
                status = gr.Markdown()
    
    convert_btn.click(
        fn=generate_mindmap,
        inputs=[input_text, model_dropdown],
        outputs=[mindmap_output, progress_output, download_output, status]
    )

if __name__ == "__main__":
    demo.launch()