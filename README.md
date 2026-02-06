# Git Dashboard

## Setup

1. Install Python packages:

```bash
pip install -r requirements.txt
```
2. run: 
```
uvicorn main:app --port 9999 --reload
```

or 

```
python main.py
```

or 

# [uv](https://docs.astral.sh/uv/guides/integration/docker/#installing-uv)
```
uv run main.py 
```
or
```
uv run python -m uvicorn main:app --port 9999 --reload
```