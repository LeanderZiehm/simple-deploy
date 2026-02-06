uv-run:
	uv run python -m uvicorn main:app --port 9999 --reload

install-uv:
# DOCS: https://docs.astral.sh/uv/getting-started/installation/
	curl -LsSf https://astral.sh/uv/install.sh | sh