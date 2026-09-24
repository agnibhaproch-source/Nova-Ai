#!/usr/bin/env bash
# Groq is the only LLM provider (docs/00 R1, docs/46 §4). Fails on any other provider SDK,
# LangChain/AI-SDK provider package, or provider endpoint anywhere under apps/.
set -euo pipefail
cd "$(dirname "$0")/.."
PKGS='openai|anthropic|google-generativeai|google-genai|mistralai|cohere|together|litellm|langchain-(openai|anthropic|google[a-z-]*|mistralai|cohere)|@ai-sdk/[a-z-]+|@anthropic-ai/[a-z-]+'
HOSTS='api\.openai\.com|api\.anthropic\.com|generativelanguage\.googleapis\.com|openrouter\.ai|api\.together|api\.mistral\.ai|api\.cohere'
fail=0
# Dependency declarations and lockfiles.
if grep -nE "^\s*\"($PKGS)(\[[^]]*\])?\s*([<>=~!;][^\"]*)?\",?\s*$" apps/*/pyproject.toml 2>/dev/null; then fail=1; fi
if grep -nE "^\s*\"($PKGS)\"\s*:" apps/web/package.json 2>/dev/null; then fail=1; fi
if grep -nE "^name = \"($PKGS)\"$" apps/*/uv.lock 2>/dev/null; then fail=1; fi
if grep -nE "^  /?($PKGS)@" pnpm-lock.yaml 2>/dev/null; then fail=1; fi
# Imports and endpoints in source.
if grep -rnE "^\s*(import|from) ($PKGS)\b|from ['\"]($PKGS)['\"]|$HOSTS" apps \
  --include=*.py --include=*.ts --include=*.tsx --include=*.js --include=*.yaml \
  --exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=.next; then fail=1; fi
if [ "$fail" -ne 0 ]; then echo "check_forbidden_providers: FAILED (Groq is the only allowed LLM provider)"; exit 1; fi
echo "check_forbidden_providers: OK (Groq only)"
