# Security

SignPad handles signatures, so a few guarantees are part of its design:

- **Signatures come only from the person.** The agent can ask for a signature through the signing pad; it has no tool that creates one. Please report any path that lets a signature be produced or reused without the person drawing it.
- **Local only.** The pad listens on `127.0.0.1`. Every API call needs a random per-session token and a local `Host` header, which stops other websites in the same browser from reading or submitting to it.
- **Originals are not modified.** Output always goes to a new file.
- **What leaves the machine:** document text (and PDF pages) and any request text you pass are sent to the Claude API. The drawn signature image is not.

To report a vulnerability, open a private security advisory on the repository rather than a public issue.
