# Capability routing

| Current environment | Available path | What to tell the user |
|---|---|---|
| Local files + Python | Status, audit, prompt inspection, tasks assemble with explicit count/phone | Free and offline |
| Codex with image generation | Small preview from `effective_prompt` | Native preview path; separate from batch API |
| Python + OpenAI package + API key | Licensed batch generation | Paid; scoped production instruction is authorization (no second confirmation) |
| Existing trusted relay + key | Shared tasks plan/start on the configured route | Scoped production instruction covers that route; no repeated trust confirmation |
| New relay | Setup and scoped network testing | Explicit third-party trust confirmation before configuration or testing |
| Maintainer credentials + signing key | Software or data-only rule releases | Use the corresponding independent release skill; ordinary editing is not publishing authorization |
| Plain chat without local tools | Explanation and prompt review only | Cannot operate the folder directly |

Never infer that ChatGPT or Codex authentication is an OpenAI API key. Detect each capability separately.

`tasks plan` blocks are authoritative for a shared task. API/key availability alone is insufficient when phone/service data or required vision auditing is missing. Shared business_ktv background production is currently blocked; native Agent previews and existing-image overlays are separate capabilities.
