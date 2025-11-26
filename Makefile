# MCP Code Mode - Build and Test Commands

.PHONY: install install-dev install-js test test-py test-js lint format clean run help

# Default target
help:
	@echo "MCP Code Mode - Available Commands"
	@echo "=================================="
	@echo ""
	@echo "Setup:"
	@echo "  make install      - Install Python dependencies"
	@echo "  make install-dev  - Install Python dev dependencies"
	@echo "  make install-js   - Install JavaScript dependencies"
	@echo "  make install-all  - Install everything"
	@echo ""
	@echo "Testing:"
	@echo "  make test         - Run all tests"
	@echo "  make test-py      - Run Python tests only"
	@echo "  make test-js      - Run JavaScript tests only"
	@echo ""
	@echo "Code Quality:"
	@echo "  make lint         - Run linter (ruff)"
	@echo "  make format       - Format code (ruff)"
	@echo ""
	@echo "Run:"
	@echo "  make run          - Run the MCP server"
	@echo ""
	@echo "Maintenance:"
	@echo "  make clean        - Remove build artifacts"
	@echo ""
	@echo "CI:"
	@echo "  make ci           - Run all CI checks (install, lint, test)"

# Installation
install:
	uv pip install -e .

install-dev:
	uv pip install -e ".[dev]"

install-js:
	cd js && npm install

install-all: install-dev install-js

# Testing
test: test-py test-js

test-py:
	pytest tests/ -v

test-js:
	cd js && npm test

# Code quality
lint:
	ruff check mcp_code_mode/ tests/ server.py

format:
	ruff format mcp_code_mode/ tests/ server.py
	ruff check --fix mcp_code_mode/ tests/ server.py

# Run the server
run:
	python server.py

# Clean build artifacts
clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf .pytest_cache/
	rm -rf __pycache__/
	rm -rf mcp_code_mode/__pycache__/
	rm -rf tests/__pycache__/
	rm -rf js/node_modules/

# CI pipeline
ci: install-all lint test
	@echo ""
	@echo "✅ All CI checks passed!"

