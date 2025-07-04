#!/usr/bin/env bash

# Install system dependencies
apt-get update && apt-get install -y ffmpeg

# (Optional) Print version for debugging
ffmpeg -version
