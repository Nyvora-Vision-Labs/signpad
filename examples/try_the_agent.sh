#!/usr/bin/env bash
# Make sample forms and let the agent sign one, using the sample request email.
set -euo pipefail
cd "$(dirname "$0")/.."
signpad samples demo
signpad agent demo/sample_agreement.docx --signer "Alex Example" --request examples/request_email.txt
