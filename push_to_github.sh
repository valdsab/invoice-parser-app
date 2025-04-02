#!/bin/bash

# Get the GitHub token from environment variable
GITHUB_TOKEN=$GITHUB_ENTOS_INVOICE_PARSOR
REPO_NAME="invoice-parser-app"
REPO_DESCRIPTION="An advanced invoice processing application with OCR and Zoho Books integration"
USERNAME="valdsab"  # Username from the response we got

# Repository already exists, so we'll use it directly
REPO_URL="https://github.com/$USERNAME/$REPO_NAME"
REPO_CLONE_URL="https://github.com/$USERNAME/$REPO_NAME.git"

echo "Using existing repository: $REPO_URL"

# Check if origin remote exists
if git remote | grep -q "^origin$"; then
  echo "Remote 'origin' already exists, removing it first..."
  git remote remove origin
fi

# Set up Git remote
git remote add origin $REPO_CLONE_URL
echo "Remote 'origin' added."

# Create an auth.helper to use the token for pushing
git config --local credential.helper "!f() { echo username=x-access-token; echo password=$GITHUB_TOKEN; }; f"

# Push to GitHub
echo "Pushing code to GitHub..."
git push -u origin main

echo "Push complete! Visit your repository at: $REPO_URL"