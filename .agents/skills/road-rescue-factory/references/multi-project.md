# Multi-project workflow

Use `MULTI_PROJECT_ARCHITECTURE.md` as the data-model reference.

For every new project, capture: category, group structure, output ratio, cover reference, detail reference, required visible text, user-confirmed business facts, negative patterns, and sample approval. Keep project-specific assets below `projects/PROJECT_ID/`.

Do not generate a batch merely because a reference was supplied. The sequence is reference analysis → reverse prompt → 1–2 samples → feedback → explicit approval → batch-size choice → deterministic prompt generation where possible → paid image authorization.

For generated text in images, tell the user that model rendering may be imperfect. A prompt that contains the correct phone number is not proof that the resulting pixels contain it correctly.
