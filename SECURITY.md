# Security Policy

## Reporting a vulnerability

Please **do not** open a public issue for security problems.

Report them privately through [GitHub Security Advisories](https://github.com/emrebardak/FileConverter/security/advisories/new). You'll get an acknowledgement within a few days.

## How the app handles sensitive data

- **API keys** are stored in Windows Credential Manager through `keyring`, or read from the `NVIDIA_API_KEY` environment variable. They are never written to plain-text files, never logged, and never bundled into the `.exe`.
- **Your documents** are converted locally. Only the summarizer sends a document's extracted text to the NVIDIA API, and only when you click **Summarize**.
- **Temporary files** live in a per-session temp folder that is deleted when the app closes.
