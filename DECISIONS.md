# DECISIONS

- Public repo. Reason: free GitHub-hosted minutes. Source: workflow file comment.
- No third-party actions; plain git and python3. Reason: nothing to pin. Source: workflow file comment.
- Secrets (Telegram token and chat id) come only from Actions secrets, never files. Source: `check.py`.
- Send one message on down and one on back; keep up/down state on branch `state`. Reason: avoid message spam. Source: `check.py`.
