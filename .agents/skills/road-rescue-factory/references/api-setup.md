# API setup guidance

For this project's current shared tasks, inspect `factory.py tasks keys-view` first. Existing trusted channels and slots are managed by `keys-save` and the dashboard password form; never request keys in chat or overwrite an existing pool merely to repeat setup. The steps below describe first-time official API setup, not a command to replace the configured TinySnow route/model. A packaged consumer already includes its SDK/runtime; use a missing-dependency repair only when the actual environment needs one.

1. Run `python factory.py setup-api`.
2. Direct the user to http<local-path>
3. Recommend configuring usage or budget alerts before bulk generation.
4. Keep the key outside chat, Markdown documentation, JSON, Python, logs, screenshots, and the delivery ZIP.
5. Run `python factory.py setup-api`; it creates a private project `.env` when missing and shows its path.
6. Ask the user to open `.env`, paste the key after `OPENAI_API_KEY=`, and save it. The program loads that value into the current process environment before creating the OpenAI client.
7. `.env` must remain excluded from Git and delivery ZIPs. Ship only `.env.example`.
8. Install the SDK only after the user agrees: `python -m pip install -r requirements.txt`.
9. Run `python factory.py setup-api --check`; no restart is required.
10. A successful check only means the environment is ready. It does not authorize a paid image request.

Never display, partially echo, or validate the key by pattern. Do not treat Codex or ChatGPT login as API authentication.
