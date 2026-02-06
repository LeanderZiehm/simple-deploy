from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from fastapi.openapi.docs import get_swagger_ui_html
from sqlalchemy import create_engine, Column, Integer
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import subprocess
import time
import os
import requests
from datetime import datetime
import uuid

# -----------------------------
# Database setup
# -----------------------------
Base = declarative_base()
DB_FILE = "config.db"
engine = create_engine(f"sqlite:///{DB_FILE}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)

class Config(Base):
    __tablename__ = "config"
    id = Column(Integer, primary_key=True)
    swap_wait_seconds = Column(Integer, default=5)

Base.metadata.create_all(engine)

# Ensure at least one row for defaults
with SessionLocal() as session:
    if session.query(Config).count() == 0:
        session.add(Config(swap_wait_seconds=5))
        session.commit()

# -----------------------------
# FastAPI setup
# -----------------------------
app = FastAPI(
    title="Docker Deployment Webhook",
    description=(
        "A webhook endpoint for zero-downtime Docker container deployments. "
        "Only images matching a configured whitelist are allowed."
    ),
    version="0.0.3"
)

@app.get("/", include_in_schema=False)
async def custom_swagger_ui():
    return get_swagger_ui_html(openapi_url="/openapi.json", title="OCR API Docs")

# -----------------------------
# Configuration
# -----------------------------
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "supersecret")  # still required

ALLOWED_IMAGE_PREFIXES = [
    "ghcr.io/leanderziehm/",
]

NOTIFY_URL = os.environ.get("NOTIFY_URL", "https://notify.leanderziehm.com/notify/me")

# -----------------------------
# Models
# -----------------------------
class WebhookPayload(BaseModel):
    secret: str = Field(..., description="Webhook secret for authentication")
    image_url: str = Field(
        ...,
        example="ghcr.io/leanderziehm/excalidraw-selfhosted:21e74edf89ab143642401b60efa9f7eca28c8519",
        description="Full Docker image URL to deploy."
    )

class WebhookResponse(BaseModel):
    status: str = Field(..., description="Deployment status message.")

class ConfigResponse(BaseModel):
    swap_wait_seconds: int = Field(..., description="Seconds to wait before swapping containers.")

# -----------------------------
# Helper functions
# -----------------------------
def get_config():
    with SessionLocal() as session:
        return session.query(Config).first()

def notify_error(message: str):
    """Send a POST request to the notification API."""
    try:
        requests.post(NOTIFY_URL, json={"text": message}, timeout=5)
    except Exception as e:
        print(f"[ERROR] Failed to send notification: {e}")

def pull_and_swap_container(image_url: str):
    """Pull Docker image and perform zero-downtime container swap, with error notifications."""
    container_base_name = image_url.split("/")[-1].split(":")[0]
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    tmp_container = f"{container_base_name}_{timestamp}_{uuid.uuid4().hex[:6]}"

    swap_wait_seconds = get_config().swap_wait_seconds

    try:
        print(f"[INFO] Pulling image: {image_url}")
        subprocess.run(["podman", "pull", image_url], check=True)

        print(f"[INFO] Starting temporary container: {tmp_container}")
        subprocess.run([
            "podman", "run", "-d", "--name", tmp_container,
            "--restart", "always", "-p", "3000:3000",
            image_url
        ], check=True)

        print(f"[INFO] Waiting {swap_wait_seconds} seconds for container to stabilize")
        time.sleep(swap_wait_seconds)

        # Stop and remove existing container(s)
        existing_containers = subprocess.run(
            ["podman", "ps", "-aq", "-f", f"name={container_base_name}"],
            capture_output=True, text=True
        ).stdout.strip().splitlines()

        for container_id in existing_containers:
            print(f"[INFO] Stopping old container: {container_id}")
            subprocess.run(["podman", "stop", container_id], check=True)
            subprocess.run(["podman", "rm", container_id], check=True)

        print(f"[INFO] Renaming {tmp_container} -> {container_base_name}")
        subprocess.run(["podman", "rename", tmp_container, container_base_name], check=True)

        print("[INFO] Deployment completed successfully!")

    except subprocess.CalledProcessError as e:
        error_msg = f"Deployment failed for {image_url}: {e}"
        print(f"[ERROR] {error_msg}")
        notify_error(error_msg)

    except Exception as e:
        error_msg = f"Unexpected error during deployment of {image_url}: {e}"
        print(f"[ERROR] {error_msg}")
        notify_error(error_msg)

# -----------------------------
# Webhook endpoint
# -----------------------------
@app.post(
    "/webhook",
    response_model=WebhookResponse,
    summary="Deploy Docker image via webhook",
    description="Accepts a JSON payload with `secret` and `image_url`, deploys it with zero downtime. Only whitelisted images are allowed."
)
async def webhook(payload: WebhookPayload, background_tasks: BackgroundTasks):
    if payload.secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret.")

    image_url = payload.image_url
    if not any(image_url.startswith(prefix) for prefix in ALLOWED_IMAGE_PREFIXES):
        raise HTTPException(status_code=403, detail="Image not allowed by whitelist.")

    background_tasks.add_task(pull_and_swap_container, image_url)
    return WebhookResponse(status="Deployment started in background.")

# -----------------------------
# Endpoint to get/update swap wait seconds
# -----------------------------
@app.get("/config", response_model=ConfigResponse)
def get_swap_wait():
    cfg = get_config()
    return ConfigResponse(swap_wait_seconds=cfg.swap_wait_seconds)

@app.post("/config", response_model=ConfigResponse)
def set_swap_wait(swap_wait_seconds: int):
    with SessionLocal() as session:
        cfg = session.query(Config).first()
        cfg.swap_wait_seconds = swap_wait_seconds
        session.commit()
        return ConfigResponse(swap_wait_seconds=cfg.swap_wait_seconds)
