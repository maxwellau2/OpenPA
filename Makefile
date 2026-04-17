.PHONY: install dev backend frontend test lint build clean deploy deploy-down slides

# Install all dependencies
install:
	cd backend && uv sync
	cd frontend && npm install

# Run both backend and frontend in parallel
dev: backend frontend

# Run backend only
backend:
	cd backend && uv run uvicorn services.rest_api:app --reload --host 0.0.0.0 --port 8000

# Run frontend only
frontend:
	cd frontend && npm run dev

# Run backend tests
test:
	cd backend && uv run pytest

# Lint frontend
lint:
	cd frontend && npm run lint

# Build frontend for production
build:
	cd frontend && npm run build

# Deploy with podman
deploy:
	podman compose up --build -d

# Stop deployment
deploy-down:
	podman compose down

# Copy slides to frontend public dir
slides:
	cp slides/index.html frontend/public/slides.html

# Clean generated files
clean:
	rm -rf backend/__pycache__ backend/**/__pycache__
	rm -rf frontend/.next frontend/out
