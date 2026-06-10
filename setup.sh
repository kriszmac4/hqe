#!/usr/bin/env bash
# HQE — One-command installer (optional)
# Sets up HQE with sensible defaults for Hermes users.

set -euo pipefail

echo "🔍 HQE — Hermes Query Engine setup"
echo ""

# Detect Hermes profile
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
if [ -d "$HERMES_HOME" ]; then
    echo "✓ Hermes detected at $HERMES_HOME"
else
    echo "⚠ Hermes not detected — HQE will work standalone"
fi

# Install Python package
if command -v uv &>/dev/null; then
    echo "Installing with uv..."
    uv pip install -e .
elif command -v pip &>/dev/null; then
    echo "Installing with pip..."
    pip install -e .
else
    echo "❌ Python/pip not found. Install Python 3.11+ first."
    exit 1
fi

# Create config directory
CONFIG_DIR="$HOME/.config/hqe"
mkdir -p "$CONFIG_DIR"
if [ ! -f "$CONFIG_DIR/config.yaml" ]; then
    cp config.example.yaml "$CONFIG_DIR/config.yaml"
    echo "✓ Default config created at $CONFIG_DIR/config.yaml"
fi

echo ""
echo "✅ HQE installed! Run 'hqe query \"your question\"' to start."
