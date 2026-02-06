
run:
	set -o allexport && . ./.env && set +o allexport && uv run python -m uvicorn main:app --port 9090
