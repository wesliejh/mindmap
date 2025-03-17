# MindMap

Mindmaps are fun, beautiful, and succinct infographics that can help you remember important information with quick reference. I love 'em, and now you can envelop them in your process by taking this code and ingesting it into your pipeline. Fun way to do so, is to have this as an accompanying tool in your RAG architecture.

Below are instructions to get started with cloning the repository and setting up the environment.

## Prerequisites

Before you begin, ensure you have the following installed:
- [Git](https://git-scm.com/)
- [Conda](https://docs.conda.io/en/latest/) (Anaconda or Miniconda)

## Getting Started

### 1. Clone the Repository
To get a local copy of the project, run the following command in your terminal:

```bash
git clone https://github.com/wesliejh/mindmap.git
cd mindmap
```

### 2. Create a Conda Environment
Set up a virtual environment using Conda to manage dependencies:
```bash
conda create -n mindmap python=3.9
conda activate mindmap
```
Replace python=3.9 with your preferred Python version if different.

### 3. Install Dependencies
Install the required packages listed in the project (assumes you have a requirements.txt or similar):
```bash
pip install -r requirements.txt
```

If you use a different dependency management file (e.g., environment.yml), adjust the command accordingly:
```bash
conda env update --file environment.yml
```

### 4. Complete credentials.txt

Make sure to enter applicable API keys, with no quotes, for OpenAI or Anthropic. You can also run this completely local by leveraging Ollama. For best results, I recommend OpenAI or Anthropic, as smaller local models have yielded unpredictable results due to issues with structured outputs.


### 5. Run the Project

```bash
python mindmap.py
```
