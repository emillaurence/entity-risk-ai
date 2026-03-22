# entity-risk-ai
A Traceable Multi-Agent AI System for Ownership and Risk Investigation

## Setup

**Install dependencies**
```bash
pip install -r requirements.txt
```

**Configure environment**
```bash
cp .env.example .env
# Edit .env and fill in your Neo4j credentials
```

**Run Jupyter**
```bash
jupyter notebook
```

## Notebooks

Add the project root to `sys.path` at the top of each notebook so `src` imports work:

```python
import sys
sys.path.insert(0, "..")  # from notebooks/
```

## Project Structure

```
entity-risk-ai/
├── notebooks/          # Jupyter notebooks
├── src/
│   ├── config.py       # Environment config
│   └── storage/
│       └── neo4j_repository.py
├── .env.example
├── requirements.txt
└── README.md
```
